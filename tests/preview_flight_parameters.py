"""Isolated browser QA using local source files. No SSH or device commands."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import wb_board
import wb_flight_parameters

ROOT=Path('F:/UAV/代码/liftrace-controlwork')

def main():
    with tempfile.TemporaryDirectory(prefix='flight_parameter_ui_') as directory:
        server.PROFILE_DIR=directory;wb_board.DEFAULT_PROFILE_DIR=directory
        config=wb_board.load_config(str(Path(__file__).resolve().parents[1]/'workbench.yaml'))
        config['connection']['board_root']=str(ROOT)
        wb=server.Workbench(config,{'transport':'local','allow_local_commands':False})
        wb.connection.update(state='ok',detail='离线界面验证；未连接板端')
        scope={};exec(wb_flight_parameters.READ_SOURCE,scope)
        def fixture_read(workbench,body):
            group=next(g for g in config['groups'] if g['id']==body['group_id'])
            folder='competition' if group.get('channel')=='competition' else group['folder']
            source=body.get('competition_config') or wb_board.substitute(group.get('site_config','{site_dir}/test_area.yaml'),wb_board.group_variables(config,group))
            data=scope['read_current_files'](str(ROOT),source,folder,body.get('speed_profile'),body.get('site_geometry'))
            return dict(data,ok=True,group_id=group['id'],source=source,description='离线界面验证：读取本机源码配置，未连接板端')
        wb_flight_parameters.read=fixture_read
        def refuse(*args,**kwargs):raise ValueError('离线界面验证禁止设备命令')
        wb.board.run=refuse;wb.start_trial=refuse;wb.connect=refuse
        server.Handler.workbench=wb
        http=server.WorkbenchHTTPServer(('127.0.0.1',8897),server.Handler)
        print('Offline parameter preview: http://127.0.0.1:8897',flush=True)
        try:http.serve_forever()
        except KeyboardInterrupt:pass
        finally:http.server_close()

if __name__=='__main__':main()
