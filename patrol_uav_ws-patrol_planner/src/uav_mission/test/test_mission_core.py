#!/usr/bin/env python3

import unittest
from dataclasses import replace

from uav_mission.mission_core import (
    CandidateSnapshot,
    CandidateStatus,
    MissionConfig,
    MissionCore,
    MissionPhase,
    ResultEvent,
    SlotStatus,
    validate_candidate,
)
from uav_mission.profile_policy import CompetitionProfile


NSEC = 1_000_000_000


def competition_profile():
    return CompetitionProfile(
        name="r2026",
        weights={
            "tent": 1.0,
            "pillbox": 1.5,
            "bridge": 2.0,
            "panzer": 2.5,
            "red_cross": 10.0,
        },
        interrupt_top_k=3,
        required_deliveries=3,
    )


def candidate(target_id=1, class_name="bridge", now=100.0, x=1.0,
              y=0.0, map_quality=0.8, class_confidence=0.9):
    first_seen = int((now - 1.0) * NSEC)
    last_seen = int((now - 0.1) * NSEC)
    return CandidateSnapshot(
        target_id=target_id,
        class_name=class_name,
        class_confidence=class_confidence,
        geometry_confidence=0.85,
        map_quality=map_quality,
        x=x,
        y=y,
        z=0.0,
        map_frame="camera_init",
        state=2,
        consecutive_observe_count=3,
        map_valid=True,
        association_valid=True,
        reject_reason="",
        transform_age_sec=0.1,
        first_seen_ns=first_seen,
        last_seen_ns=last_seen,
    )


def result_for(action, event_seq, status="PROGRESS", stage="PLANNER",
               terminal=False, retryable=False, payload_committed=False,
               reason="progress", executor_id="executor-a"):
    return ResultEvent(
        mission_id="mission-1",
        executor_id=executor_id,
        event_seq=event_seq,
        decision_seq=action.decision_seq,
        command=action.command,
        has_target=True,
        target_id=action.candidate_key.target_id,
        target_first_seen_ns=action.candidate_key.first_seen_ns,
        target_class=action.target_class,
        attempt=action.attempt,
        payload_slot=action.payload_slot,
        status=status,
        stage=stage,
        terminal=terminal,
        retryable=retryable,
        payload_committed=payload_committed,
        reason=reason,
        evidence_source="deterministic_test",
    )


def release_ack(action, event_seq):
    return result_for(
        action,
        event_seq,
        status="PROGRESS",
        stage="RELEASE",
        terminal=False,
        retryable=False,
        payload_committed=True,
        reason="release_ack_success",
    )


class MissionCoreTest(unittest.TestCase):
    def make_core(self, config=None):
        core = MissionCore(competition_profile(), config)
        core.start("mission-1", 100.0)
        return core

    def dispatch(self, core, item, now=100.0, route_complete=False):
        accepted = core.ingest([item], now)
        self.assertTrue(accepted[0].accepted, accepted[0].reason)
        action = core.choose(now, (0.0, 0.0), route_complete)
        self.assertIsNotNone(action)
        self.assertEqual(action.command, "APPROACH")
        return action

    def finish_delivery(self, core, action, event_seq):
        accepted, reason, _ = core.apply_result(
            release_ack(action, event_seq), 101.0)
        self.assertTrue(accepted, reason)
        accepted, reason, next_action = core.apply_result(
            result_for(
                action,
                event_seq + 1,
                status="SUCCEEDED",
                stage="RECOVERY",
                terminal=True,
                reason="recovery_complete",
            ),
            102.0,
        )
        self.assertTrue(accepted, reason)
        return next_action

    def test_profile_interrupt_order_excludes_tank(self):
        profile = competition_profile()
        self.assertEqual(
            profile.interrupt_classes,
            ("red_cross", "panzer", "bridge"),
        )
        self.assertFalse(profile.allows("tank"))

    def test_candidate_contract_rejects_unsafe_variants(self):
        profile = competition_profile()
        config = MissionConfig()
        base = candidate()
        cases = (
            (replace(base, class_name="tank"), "profile_excluded"),
            (replace(base, state=3), "state_not_confirmed"),
            (replace(base, state=4), "state_not_confirmed"),
            (replace(base, consecutive_observe_count=2), "streak_too_short"),
            (replace(base, map_frame="map"), "map_frame_mismatch"),
            (replace(base, association_valid=False), "association_invalid"),
            (replace(base, last_seen_ns=99 * NSEC), "candidate_stale"),
            (replace(base, transform_age_sec=0.6), "transform_stale"),
            (replace(base, map_quality=1.1), "quality_out_of_range"),
            (replace(base, first_seen_ns=101 * NSEC),
             "source_stamp_order_invalid"),
        )
        for unsafe, expected in cases:
            with self.subTest(expected=expected):
                actual = validate_candidate(unsafe, 100.0, profile, config)
                self.assertFalse(actual.accepted)
                self.assertEqual(actual.reason, expected)

        legal_zero_id = validate_candidate(
            replace(base, target_id=0), 100.0, profile, config)
        self.assertTrue(legal_zero_id.accepted, legal_zero_id.reason)

    def test_low_weight_waits_then_coverage_fallback_prefers_weight(self):
        core = self.make_core()
        outcomes = core.ingest([
            candidate(1, "tent"),
            candidate(2, "pillbox", x=2.0),
        ], 100.0)
        self.assertTrue(all(item.accepted for item in outcomes))
        self.assertIsNone(core.choose(100.0, (0.0, 0.0)))
        action = core.choose(100.0, (0.0, 0.0), route_complete=True)
        self.assertEqual(action.target_class, "pillbox")
        self.assertEqual(action.reason, "coverage_complete_fallback")

    def test_high_weight_interrupt_and_no_execution_preemption(self):
        core = self.make_core()
        action = self.dispatch(core, candidate(1, "bridge"))
        self.assertEqual(action.reason, "high_weight_search_interrupt")
        core.ingest([candidate(2, "red_cross", now=100.1)], 100.1)
        self.assertIsNone(core.choose(100.1, (0.0, 0.0)))
        self.assertEqual(core.active_action, action)

    def test_best_candidate_per_class_competes(self):
        core = self.make_core()
        core.ingest([
            candidate(1, "bridge", x=0.2, map_quality=0.6),
            candidate(2, "bridge", x=3.0, map_quality=0.9),
            candidate(3, "panzer", x=5.0, map_quality=0.5),
        ], 100.0)
        ranked = core.queue.ranked(100.0, (0.0, 0.0))
        self.assertEqual([entry.snapshot.target_id for entry in ranked], [3, 2])

    def test_retry_cooldown_then_second_attempt(self):
        core = self.make_core()
        action = self.dispatch(core, candidate(1, "bridge"))
        accepted, reason, resume = core.apply_result(
            result_for(
                action,
                1,
                status="FAILED",
                stage="PLANNER",
                terminal=True,
                retryable=True,
                reason="planner_failed",
            ),
            101.0,
        )
        self.assertTrue(accepted, reason)
        self.assertEqual(resume.command, "RESUME")
        entry = core.queue.entries[action.candidate_key]
        self.assertEqual(entry.status, CandidateStatus.COOLDOWN)
        self.assertEqual(core.slots[0].status, SlotStatus.FREE)
        self.assertIsNone(core.choose(120.9, (0.0, 0.0)))
        retry = core.choose(121.0, (0.0, 0.0))
        self.assertEqual(retry.command, "APPROACH")
        self.assertEqual(retry.attempt, 2)

    def test_dynamic_budget_dispatches_in_guard_window(self):
        core = self.make_core()
        core.ingest([candidate(1, "tent", now=540.0, x=0.0)], 540.0)
        self.assertTrue(core.should_stop_search(540.0, (0.0, 0.0)))
        action = core.choose(540.0, (0.0, 0.0))
        self.assertEqual(action.command, "APPROACH")
        self.assertEqual(action.reason, "time_budget_fallback")

    def test_infeasible_candidate_returns_without_reservation(self):
        core = self.make_core()
        item = candidate(1, "tent", now=551.0, x=0.0)
        core.ingest([item], 551.0)
        action = core.choose(551.0, (0.0, 0.0))
        self.assertEqual(action.command, "RETURN_HOME")
        self.assertEqual(action.reason, "time_budget_no_feasible_candidate")
        self.assertEqual(core.queue.entries[item.key].status,
                         CandidateStatus.PENDING)

    def test_hard_return_at_510_seconds(self):
        core = self.make_core()
        action = core.choose(610.0, (0.0, 0.0))
        self.assertEqual(action.command, "RETURN_HOME")
        self.assertEqual(action.reason, "forced_return_deadline")
        rejected = core.ingest([candidate(now=610.0)], 610.0)
        self.assertFalse(rejected[0].accepted)
        self.assertEqual(rejected[0].reason,
                         "mission_not_accepting_candidates")

    def test_invalid_commit_does_not_consume_event_sequence(self):
        core = self.make_core()
        action = self.dispatch(core, candidate())
        invalid = replace(release_ack(action, 1), terminal=True)
        accepted, reason, _ = core.apply_result(invalid, 101.0)
        self.assertFalse(accepted)
        self.assertEqual(reason, "invalid_payload_commit_event")
        accepted, reason, _ = core.apply_result(release_ack(action, 1), 101.0)
        self.assertTrue(accepted, reason)
        self.assertEqual(core.committed_slots, 1)

    def test_duplicate_and_out_of_order_results_are_idempotent(self):
        core = self.make_core()
        action = self.dispatch(core, candidate())
        progress = result_for(action, 2)
        self.assertTrue(core.apply_result(progress, 100.1)[0])
        accepted, reason, _ = core.apply_result(progress, 100.2)
        self.assertFalse(accepted)
        self.assertEqual(reason, "event_duplicate_or_out_of_order")
        accepted, reason, _ = core.apply_result(
            replace(progress, event_seq=1), 100.3)
        self.assertFalse(accepted)
        self.assertEqual(reason, "event_duplicate_or_out_of_order")

    def test_success_without_commit_can_be_corrected_same_sequence(self):
        core = self.make_core()
        action = self.dispatch(core, candidate())
        invalid = result_for(
            action, 1, status="SUCCEEDED", stage="RECOVERY",
            terminal=True, reason="done")
        accepted, reason, _ = core.apply_result(invalid, 101.0)
        self.assertFalse(accepted)
        self.assertEqual(reason, "success_without_payload_commit")
        corrected = replace(
            invalid,
            status="FAILED",
            stage="PLANNER",
            retryable=False,
            reason="planner_failed",
        )
        self.assertTrue(core.apply_result(corrected, 101.0)[0])

    def test_release_commit_survives_recovery_failure(self):
        core = self.make_core()
        action = self.dispatch(core, candidate())
        self.assertTrue(core.apply_result(release_ack(action, 1), 101.0)[0])
        wrong_stage = result_for(
            action, 2, status="FAILED", stage="ALIGNMENT", terminal=True,
            reason="recovery_failed")
        accepted, reason, _ = core.apply_result(wrong_stage, 102.0)
        self.assertFalse(accepted)
        self.assertEqual(reason, "committed_terminal_stage_invalid")
        failed = replace(wrong_stage, stage="RECOVERY")
        accepted, reason, next_action = core.apply_result(failed, 102.0)
        self.assertTrue(accepted, reason)
        self.assertEqual(next_action.command, "RETURN_HOME")
        self.assertTrue(core.mission_failed)
        self.assertEqual(core.committed_slots, 1)
        self.assertEqual(core.queue.entries[action.candidate_key].status,
                         CandidateStatus.SUCCEEDED)

    def test_three_commits_immediately_return(self):
        core = self.make_core()
        event_seq = 1
        for index, class_name in enumerate(
                ("bridge", "panzer", "red_cross"), start=1):
            action = self.dispatch(
                core,
                candidate(index, class_name, now=100.0 + index),
                now=100.0 + index,
            )
            next_action = self.finish_delivery(core, action, event_seq)
            event_seq += 2
        self.assertEqual(core.committed_slots, 3)
        self.assertEqual(next_action.command, "RETURN_HOME")
        self.assertEqual(next_action.reason, "required_deliveries_complete")
        self.assertEqual(core.phase, MissionPhase.RETURN_HOME)

    def test_executor_change_and_target_identity_mismatch_fail_closed(self):
        core = self.make_core()
        action = self.dispatch(core, candidate())
        first = result_for(action, 1)
        self.assertTrue(core.apply_result(first, 100.1)[0])
        changed = result_for(action, 2, executor_id="executor-b")
        accepted, reason, _ = core.apply_result(changed, 100.2)
        self.assertFalse(accepted)
        self.assertEqual(reason, "executor_changed")
        mismatch = replace(result_for(action, 2),
                           target_first_seen_ns=1)
        accepted, reason, _ = core.apply_result(mismatch, 100.2)
        self.assertFalse(accepted)
        self.assertEqual(reason, "target_mismatch")
        command_mismatch = replace(result_for(action, 2), command="ALIGN")
        accepted, reason, _ = core.apply_result(command_mismatch, 100.2)
        self.assertFalse(accepted)
        self.assertEqual(reason, "command_mismatch")
        missing_flag = replace(result_for(action, 2), has_target=False)
        accepted, reason, _ = core.apply_result(missing_flag, 100.2)
        self.assertFalse(accepted)
        self.assertEqual(reason, "result_target_flag_missing")

    def test_return_land_lifecycle(self):
        core = self.make_core()
        action = core.choose(610.0, (0.0, 0.0))
        self.assertEqual(action.command, "RETURN_HOME")
        land = core.mark_return_arrived()
        self.assertEqual(land.command, "LAND")
        core.mark_landed()
        self.assertEqual(core.phase, MissionPhase.COMPLETE)


if __name__ == "__main__":
    unittest.main()
