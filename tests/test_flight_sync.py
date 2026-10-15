"""Real file fixtures and local stdlib-reader execution; never SSH/ROS/flight."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wb_flight_sync as sync


class FlightSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.run = self.base / 'board' / 'logs' / 'board_run'
        self.run.mkdir(parents=True)
        self.board = SimpleNamespace(root=str(self.base / 'board'),
            target=SimpleNamespace(host='fixture@board', port=22, transport='ssh', password='private'),
            config={'connection': {'board_python': sys.executable}})
        self.worker = sync.FlightSync(self.base / 'profile')
        with patch('threading.Thread.start'):
            self.worker.start(self.board, 'mod08', 1024)
        # Skip only throttling; exercise the exact remote script and wire framing.
        self.delay = patch.object(self.worker.stop, 'wait', return_value=False)
        self.delay.start()
        self.transport = patch('wb_flight_sync.run_bytes', side_effect=self.local_reader)
        self.transport.start()
        self.worker.job['run'] = 'board_run'

    def tearDown(self):
        self.delay.stop(); self.transport.stop(); self.tmp.cleanup()

    @staticmethod
    def local_reader(target, command, timeout):
        result = subprocess.run(shlex.split(command), capture_output=True, timeout=timeout)
        return result.returncode, result.stdout

    def listing(self):
        return self.worker._request('list')[0]['files']

    def staging(self, name):
        return Path(self.worker.job['local_directory']) / (name + '.part')

    def test_mapping_archive_is_excluded_from_default_sync(self):
        mapping_dir=self.run/'mapping';mapping_dir.mkdir()
        (mapping_dir/'freedom_00001.bag').write_bytes(b'large raw map')
        (mapping_dir/'manifest.json').write_text('{}')
        (self.run/'regular.log').write_text('existing flight log')
        self.assertEqual([row['path'] for row in self.listing()],['regular.log'])

    def test_incremental_transfer_only_reads_missing_bytes(self):
        source = self.run / 'flight.bag.active'
        source.write_bytes(b'A' * 200000)
        self.worker._live(self.listing())
        self.assertEqual(self.staging('flight.bag').read_bytes(), source.read_bytes())
        with source.open('ab') as writer:
            writer.write(b'B' * 50000)
        with patch.object(self.worker, '_request', wraps=self.worker._request) as request:
            self.worker._live(self.listing())
        self.assertEqual(request.call_args.kwargs['offset'], 200000)
        self.assertEqual(request.call_args.kwargs['length'], 50000)
        self.assertEqual(self.staging('flight.bag').read_bytes(), source.read_bytes())
        self.assertFalse(self.staging('flight.bag').with_suffix('').exists())

    def test_close_rename_repairs_header_and_middle_chunk_rewrites(self):
        active = self.run / 'flight.bag.active'
        active.write_bytes(b'A' * (2*sync.BLOCK + 123))
        items = self.listing()
        for _ in range(3):
            self.worker._live(items)
        with active.open('r+b') as stream:
            stream.write(b'FINAL_HEADER')
            stream.seek(sync.BLOCK + 23); stream.write(b'FINAL_CHUNK_HEADER')
        closed = active.with_suffix(''); active.rename(closed)
        with patch.object(self.worker, '_request', wraps=self.worker._request) as request:
            self.assertTrue(self.worker._finalize(self.listing()[0]))
        copied = Path(self.worker.job['local_directory']) / 'flight.bag'
        self.assertEqual(copied.read_bytes(), closed.read_bytes())
        # The unchanged final block is verified locally, never retransmitted.
        reads = [c.kwargs['offset'] for c in request.call_args_list if c.args[0] == 'read']
        self.assertNotIn(2*sync.BLOCK, reads)
        self.assertFalse(self.staging('flight.bag').exists())
        self.assertEqual(self.worker.job['files']['flight.bag']['sha256'], hashlib.sha256(closed.read_bytes()).hexdigest())

    def test_active_suffix_and_open_writer_are_never_published(self):
        active = self.run / 'flight.bag.active'; active.write_bytes(b'active')
        self.assertFalse(self.worker._finalize(self.listing()[0]))
        closed = active.with_suffix(''); active.rename(closed)
        with closed.open('ab'):
            self.assertFalse(self.worker._finalize(self.listing()[0]))
        self.assertFalse((Path(self.worker.job['local_directory']) / 'flight.bag').exists())

    def test_truncation_and_replacement_restart_staging(self):
        source = self.run / 'flight.bag.active'; source.write_bytes(b'A'*200)
        self.worker._live(self.listing())
        source.write_bytes(b'B'*20)
        self.worker._live(self.listing())
        self.assertEqual(self.staging('flight.bag').read_bytes(), b'B'*20)
        replacement = self.run / 'replacement'; replacement.write_bytes(b'C'*50)
        replacement.replace(source)
        self.worker._live(self.listing())
        self.assertEqual(self.staging('flight.bag').read_bytes(), b'C'*50)

    def test_corrupt_or_partial_wire_packet_does_not_advance_offset(self):
        source = self.run / 'flight.bag.active'; source.write_bytes(b'fixture')
        items = self.listing()
        def truncated(target, command, timeout):
            code, output = self.local_reader(target, command, timeout)
            return code, output[:-5]
        with patch('wb_flight_sync.run_bytes', side_effect=truncated):
            with self.assertRaises(ValueError): self.worker._live(items)
        self.assertEqual(self.worker.job['files']['flight.bag']['received'], 0)
        self.assertEqual(self.staging('flight.bag').stat().st_size, 0)

    def test_failure_preserves_partial_and_retries_stop_after_five(self):
        source = self.run / 'flight.bag.active'; source.write_bytes(b'fixture')
        self.worker._live(self.listing())
        with patch('wb_flight_sync.run_bytes', return_value=(124, b'')) as transport:
            self.worker._run()
        self.assertEqual(transport.call_count, 5)
        self.assertEqual(self.worker.job['state'], 'paused')
        self.assertEqual(self.staging('flight.bag').read_bytes(), b'fixture')

    def test_resume_after_restart_keeps_offset_and_rejects_other_board(self):
        source = self.run / 'flight.bag.active'; source.write_bytes(b'fixture')
        self.worker._live(self.listing()); self.worker._save()
        restored = sync.FlightSync(self.base/'profile'); restored.restore()
        self.assertEqual(restored.job['state'], 'paused')
        other = copy.deepcopy(self.board); other.target.host = 'other@board'
        with self.assertRaises(ValueError): restored.resume(other, restored.job['id'])
        with patch('threading.Thread.start'):
            restored.resume(self.board, restored.job['id'])
        self.assertEqual(restored.job['files']['flight.bag']['received'], 7)
        self.assertTrue(restored.ended.is_set())
        self.assertNotIn('private', json.dumps(restored.job))

    def test_path_scope_symlinks_and_other_runs_rejected(self):
        for value in ('../private','/etc/passwd','C:/logs','a//b','a\\b','a/.hidden','a\nfile'):
            with self.assertRaises(ValueError): sync.relative(value)
        secret = self.base/'secret'; secret.write_bytes(b'private')
        (self.run/'link.bag').symlink_to(secret)
        other = self.base/'board'/'logs'/'old_run';other.mkdir();(other/'old.bag').write_bytes(b'old')
        self.assertEqual(self.listing(), [])
        with self.assertRaises(ValueError):
            self.worker._request('read', path='link.bag', identity=[0,0], offset=0, length=1)
        self.worker.job['run'] = None
        with patch.object(self.worker, 'active', return_value=True):
            self.worker.bind(str(self.base/'outside'))
            self.assertIsNone(self.worker.job['run'])
            self.worker.bind(str(self.run))
            self.assertEqual(self.worker.job['run'], 'board_run')

    def test_metadata_log_updates_and_nested_files_are_verified(self):
        recording = self.run/'recording';recording.mkdir()
        path = recording/'run_metadata.json';path.write_bytes(b'{"recording":true}')
        self.worker._live(self.listing())
        path.write_bytes(b'{"recording":false,"closed":true}')
        self.assertTrue(self.worker._finalize(self.listing()[0]))
        self.assertEqual((Path(self.worker.job['local_directory'])/'recording/run_metadata.json').read_bytes(), path.read_bytes())

    def test_default_off_and_preview_or_invalid_options_rejected(self):
        self.assertEqual(sync.options({}), (False, 256))
        for body in ({'sync_logs':'yes'}, {'sync_logs':True,'mode':'preview'},
                     {'sync_logs':True,'check_config':True}, {'sync_logs':True,'sync_rate_kib':0}):
            with self.assertRaises(ValueError): sync.options(body)

    def test_tagged_recorder_located_before_ready_without_selecting_old_runs(self):
        source = self.run/'flight.bag.active'; source.write_bytes(b'fixture')
        code = "import sys;f=open(sys.argv[1],'ab');print('ready',flush=True);sys.stdin.read()"
        child = subprocess.Popen([sys.executable, '-c', code, str(source)],
            env=dict(os.environ, WB_FLIGHT_SYNC_ID=self.worker.job['id']),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.worker.job['run'] = None
            self.assertEqual(self.worker._request('locate')[0]['run'], 'board_run')
            original = self.worker.job['id']; self.worker.job['id'] = 'b'*32
            self.assertIsNone(self.worker._request('locate')[0]['run'])
            self.worker.job['id'] = original
        finally:
            child.communicate('', timeout=5)

    def test_finished_run_publishes_only_verified_files(self):
        source = self.run/'flight.bag'; source.write_bytes(b'fixture')
        self.worker.ended.set()
        self.worker._run()
        self.assertEqual(self.worker.job['state'], 'complete')
        self.assertEqual((Path(self.worker.job['local_directory'])/'flight.bag').read_bytes(), b'fixture')


class FlightEntryIntegrationTests(unittest.TestCase):
    def setUp(self):
        import server
        import wb_board
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, 'PROFILE_DIR', self.tmp.name),
                        patch.object(wb_board, 'DEFAULT_PROFILE_DIR', self.tmp.name)]
        for item in self.patches: item.start()
        self.workbench = server.Workbench(wb_board.load_config(), {'transport': 'ssh'})
        self.workbench.connection['state'] = 'ok'
        # Servo preflight was added after these fixtures; keep this suite offline.
        self.servo_probe=patch.object(self.workbench.servo_debug,'assert_idle')
        self.servo_probe.start()
        self.addCleanup(self.servo_probe.stop)

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def body(self, **extra):
        return dict(group_id='mod08', mode='flight', real_release=False, confirm='启动试飞', **extra)

    def test_default_flight_and_preview_do_not_start_sync(self):
        session = SimpleNamespace(snapshot=lambda: {'state':'running'})
        with patch.object(self.workbench.sessions, 'open', return_value=session), \
             patch.object(self.workbench.flight_sync, 'start') as start:
            self.workbench._start_trial(self.body())
            self.assertFalse(self.workbench.trial['sync_logs']); start.assert_not_called()
            self.workbench._start_trial(dict(group_id='mod08',mode='preview'))
            start.assert_not_called()

    def test_enabled_flight_keeps_entry_and_tracks_directory_and_exit(self):
        session = SimpleNamespace(snapshot=lambda: {'state':'running'})
        with patch.object(self.workbench.sessions, 'open', return_value=session) as opened, \
             patch('threading.Thread.start'):
            result = self.workbench._start_trial(self.body(sync_logs=True, sync_rate_kib=512))
        command = opened.call_args.args[2]
        self.assertIn(result['trial']['command'], command)
        self.assertTrue(command.startswith('export WB_FLIGHT_SYNC_ID='+result['trial']['sync_id']))
        run = self.workbench.board.root+'/logs/board_fixture'
        with patch.object(self.workbench.flight_sync, 'active', return_value=True):
            self.workbench._on_output('trial', 1, 'READY: '+run+'\n')
        self.assertEqual(self.workbench.flight_sync.job['run'], 'board_fixture')
        self.workbench._on_state('trial', {'state':'exited','exit_code':0})
        self.assertTrue(self.workbench.flight_sync.ended.is_set())

    def test_preflight_rejection_and_sync_failure_leave_flight_boundary_intact(self):
        with patch.object(self.workbench.sessions, 'open') as opened:
            with self.assertRaises(ValueError):
                self.workbench._start_trial(dict(group_id='mod08',mode='preview',sync_logs=True))
            opened.assert_not_called()
        session = SimpleNamespace(snapshot=lambda: {'state':'running'})
        with patch.object(self.workbench.sessions, 'open', return_value=session) as opened, \
             patch.object(self.workbench.flight_sync, 'start', side_effect=OSError('disk full')):
            result = self.workbench._start_trial(self.body(sync_logs=True))
        self.assertTrue(result['ok']); opened.assert_called_once()
        self.assertIsNone(result['trial']['sync_id'])


if __name__ == '__main__': unittest.main()
