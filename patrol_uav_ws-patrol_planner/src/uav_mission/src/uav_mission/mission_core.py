"""Pure navigation mission policy for candidate scheduling and results.

ROS message conversion, clocks and publishers stay in the runtime node.  The
core only consumes immutable facts and explicit timestamps, which makes every
queue and retry transition deterministic and replayable.
"""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .profile_policy import CompetitionProfile


CONFIRMED_STATE = 2


class CandidateStatus(Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COOLDOWN = "COOLDOWN"
    SUCCEEDED = "SUCCEEDED"
    EXHAUSTED = "EXHAUSTED"
    SKIPPED = "SKIPPED"


class MissionPhase(Enum):
    INIT = "INIT"
    SEARCH = "SEARCH"
    EXECUTING = "EXECUTING"
    RETURN_HOME = "RETURN_HOME"
    LAND = "LAND"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class SlotStatus(Enum):
    FREE = "FREE"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"


@dataclass(frozen=True, order=True)
class CandidateKey:
    target_id: int
    first_seen_ns: int


@dataclass(frozen=True)
class CandidateSnapshot:
    target_id: int
    class_name: str
    class_confidence: float
    geometry_confidence: float
    map_quality: float
    x: float
    y: float
    z: float
    map_frame: str
    state: int
    consecutive_observe_count: int
    map_valid: bool
    association_valid: bool
    reject_reason: str
    transform_age_sec: float
    first_seen_ns: int
    last_seen_ns: int

    @property
    def key(self) -> CandidateKey:
        return CandidateKey(int(self.target_id), int(self.first_seen_ns))


@dataclass
class CandidateEntry:
    snapshot: CandidateSnapshot
    status: CandidateStatus = CandidateStatus.PENDING
    attempts: int = 0
    cooldown_until: float = 0.0
    last_result: str = ""
    payload_slot: int = 0
    reachable: Optional[bool] = None


@dataclass
class PayloadSlot:
    index: int
    status: SlotStatus = SlotStatus.FREE
    candidate_key: Optional[CandidateKey] = None


@dataclass(frozen=True)
class CandidateValidation:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class CoreAction:
    command: str
    reason: str
    decision_seq: int
    candidate_key: Optional[CandidateKey] = None
    target_class: str = ""
    attempt: int = 0
    payload_slot: int = 0


@dataclass(frozen=True)
class ResultEvent:
    mission_id: str
    executor_id: str
    event_seq: int
    decision_seq: int
    command: str
    has_target: bool
    target_id: int
    target_first_seen_ns: int
    target_class: str
    attempt: int
    payload_slot: int
    status: str
    stage: str
    terminal: bool
    retryable: bool
    payload_committed: bool
    reason: str
    evidence_source: str

    @property
    def candidate_key(self) -> CandidateKey:
        return CandidateKey(int(self.target_id), int(self.target_first_seen_ns))


@dataclass
class MissionConfig:
    mission_frame: str = "camera_init"
    candidate_max_age: float = 0.5
    transform_max_age: float = 0.5
    min_streak: int = 3
    max_target_z: float = 4.0
    max_attempts: int = 2
    retry_cooldown: float = 20.0
    mission_timeout: float = 600.0
    forced_return_at: float = 510.0
    return_land_reserve: float = 90.0
    delivery_reserve_per_slot: float = 60.0
    path_factor: float = 1.5
    nominal_speed: float = 1.0
    decision_guard: float = 15.0
    home_xy: Tuple[float, float] = (0.0, 0.0)

    def __post_init__(self):
        positive = {
            "candidate_max_age": self.candidate_max_age,
            "transform_max_age": self.transform_max_age,
            "max_target_z": self.max_target_z,
            "max_attempts": self.max_attempts,
            "retry_cooldown": self.retry_cooldown,
            "mission_timeout": self.mission_timeout,
            "forced_return_at": self.forced_return_at,
            "return_land_reserve": self.return_land_reserve,
            "delivery_reserve_per_slot": self.delivery_reserve_per_slot,
            "path_factor": self.path_factor,
            "nominal_speed": self.nominal_speed,
        }
        for name, value in positive.items():
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError("%s must be finite and positive" % name)
        if self.min_streak <= 0:
            raise ValueError("min_streak must be positive")
        if int(self.min_streak) != self.min_streak:
            raise ValueError("min_streak must be an integer")
        if int(self.max_attempts) != self.max_attempts:
            raise ValueError("max_attempts must be an integer")
        if not math.isfinite(float(self.decision_guard)) or self.decision_guard < 0.0:
            raise ValueError("decision_guard must be finite and non-negative")
        if self.forced_return_at >= self.mission_timeout:
            raise ValueError("forced_return_at must precede mission_timeout")
        if (self.mission_timeout - self.forced_return_at <
                self.return_land_reserve):
            raise ValueError(
                "forced return must preserve the return/landing reserve")
        if (len(self.home_xy) != 2 or
                not all(math.isfinite(float(value)) for value in self.home_xy)):
            raise ValueError("home_xy must contain two finite coordinates")


def validate_candidate(candidate: CandidateSnapshot, now: float,
                       profile: CompetitionProfile,
                       config: MissionConfig) -> CandidateValidation:
    """Apply the formal fail-closed candidate admission contract."""

    if not profile.allows(candidate.class_name):
        return CandidateValidation(False, "profile_excluded")
    if int(candidate.state) != CONFIRMED_STATE:
        return CandidateValidation(False, "state_not_confirmed")
    if int(candidate.consecutive_observe_count) < config.min_streak:
        return CandidateValidation(False, "streak_too_short")
    if not candidate.map_valid:
        return CandidateValidation(False, "map_invalid")
    if candidate.map_frame != config.mission_frame:
        return CandidateValidation(False, "map_frame_mismatch")
    if not candidate.association_valid:
        return CandidateValidation(False, "association_invalid")
    if candidate.reject_reason:
        return CandidateValidation(False, "candidate_rejected")
    numeric = (
        candidate.class_confidence,
        candidate.geometry_confidence,
        candidate.map_quality,
        candidate.x,
        candidate.y,
        candidate.z,
        candidate.transform_age_sec,
        now,
    )
    if not all(math.isfinite(float(value)) for value in numeric):
        return CandidateValidation(False, "non_finite_value")
    if candidate.first_seen_ns <= 0 or candidate.last_seen_ns <= 0:
        return CandidateValidation(False, "invalid_source_stamp")
    if candidate.first_seen_ns > candidate.last_seen_ns:
        return CandidateValidation(False, "source_stamp_order_invalid")
    age = float(now) - float(candidate.last_seen_ns) / 1.0e9
    if age < 0.0 or age > config.candidate_max_age:
        return CandidateValidation(False, "candidate_stale")
    if (candidate.transform_age_sec < 0.0 or
            candidate.transform_age_sec > config.transform_max_age):
        return CandidateValidation(False, "transform_stale")
    if candidate.map_quality < 0.0:
        return CandidateValidation(False, "map_quality_invalid")
    confidence_values = (
        candidate.class_confidence,
        candidate.geometry_confidence,
        candidate.map_quality,
    )
    if any(value < 0.0 or value > 1.0 for value in confidence_values):
        return CandidateValidation(False, "quality_out_of_range")
    if candidate.z > config.max_target_z:
        return CandidateValidation(False, "target_above_height_limit")
    return CandidateValidation(True, "accepted")


class CandidateQueue:
    """Persistent, result-driven candidate queue for one mission session."""

    def __init__(self, profile: CompetitionProfile, config: MissionConfig):
        self.profile = profile
        self.config = config
        self.entries: Dict[CandidateKey, CandidateEntry] = {}
        self.delivered_classes = set()

    def ingest(self, candidate: CandidateSnapshot,
               now: float) -> CandidateValidation:
        validation = validate_candidate(candidate, now, self.profile,
                                        self.config)
        if not validation.accepted:
            return validation
        key = candidate.key
        existing = self.entries.get(key)
        if existing is None:
            self.entries[key] = CandidateEntry(snapshot=candidate)
            return validation
        if candidate.last_seen_ns <= existing.snapshot.last_seen_ns:
            return CandidateValidation(False, "observation_not_newer")
        if existing.status in (CandidateStatus.SUCCEEDED,
                               CandidateStatus.EXHAUSTED,
                               CandidateStatus.SKIPPED):
            return CandidateValidation(False, "candidate_terminal")
        existing.snapshot = candidate
        return validation

    def refresh_cooldowns(self, now: float) -> None:
        for entry in self.entries.values():
            if (entry.status == CandidateStatus.COOLDOWN and
                    now >= entry.cooldown_until and
                    entry.attempts < self.config.max_attempts):
                entry.status = CandidateStatus.PENDING
                entry.payload_slot = 0

    def _rank_key(self, entry: CandidateEntry,
                  current_xy: Tuple[float, float]):
        snapshot = entry.snapshot
        distance = math.hypot(
            snapshot.x - current_xy[0], snapshot.y - current_xy[1])
        reachability = 0 if entry.reachable is True else (
            1 if entry.reachable is None else 2)
        return (
            -self.profile.weight(snapshot.class_name),
            reachability,
            -snapshot.map_quality,
            -snapshot.class_confidence,
            distance,
            snapshot.first_seen_ns,
            snapshot.target_id,
        )

    def ranked(self, now: float, current_xy: Tuple[float, float],
               allowed_classes: Optional[Iterable[str]] = None
               ) -> List[CandidateEntry]:
        self.refresh_cooldowns(now)
        allowed = set(allowed_classes) if allowed_classes is not None else None
        pending = [
            entry for entry in self.entries.values()
            if entry.status == CandidateStatus.PENDING
            and entry.snapshot.class_name not in self.delivered_classes
            and (allowed is None or entry.snapshot.class_name in allowed)
            and entry.reachable is not False
        ]
        # Only the best candidate for each formal class may compete for a slot.
        best_by_class: Dict[str, CandidateEntry] = {}
        for entry in pending:
            class_name = entry.snapshot.class_name
            current = best_by_class.get(class_name)
            if (current is None or
                    self._rank_key(entry, current_xy) <
                    self._rank_key(current, current_xy)):
                best_by_class[class_name] = entry
        return sorted(
            best_by_class.values(),
            key=lambda item: self._rank_key(item, current_xy),
        )

    def reserve(self, key: CandidateKey, payload_slot: int) -> CandidateEntry:
        entry = self.entries[key]
        if entry.status != CandidateStatus.PENDING:
            raise ValueError("candidate is not pending")
        entry.status = CandidateStatus.EXECUTING
        entry.attempts += 1
        entry.payload_slot = int(payload_slot)
        return entry

    def fail(self, key: CandidateKey, retryable: bool, now: float,
             reason: str) -> CandidateEntry:
        entry = self.entries[key]
        if entry.status != CandidateStatus.EXECUTING:
            raise ValueError("candidate is not executing")
        entry.last_result = reason
        entry.payload_slot = 0
        if retryable and entry.attempts < self.config.max_attempts:
            entry.status = CandidateStatus.COOLDOWN
            entry.cooldown_until = now + self.config.retry_cooldown
        else:
            entry.status = CandidateStatus.EXHAUSTED
        return entry

    def commit(self, key: CandidateKey, payload_slot: int,
               reason: str) -> CandidateEntry:
        entry = self.entries[key]
        if entry.status != CandidateStatus.EXECUTING:
            raise ValueError("candidate is not executing")
        if entry.payload_slot != int(payload_slot):
            raise ValueError("payload slot mismatch")
        entry.status = CandidateStatus.SUCCEEDED
        entry.last_result = reason
        self.delivered_classes.add(entry.snapshot.class_name)
        return entry


class MissionCore:
    """Deterministic target scheduling and result reducer."""

    def __init__(self, profile: CompetitionProfile,
                 config: Optional[MissionConfig] = None):
        self.profile = profile
        self.config = config or MissionConfig()
        self.queue = CandidateQueue(profile, self.config)
        self.phase = MissionPhase.INIT
        self.mission_id = ""
        self.started_at = 0.0
        self.decision_seq = 0
        self.active_action: Optional[CoreAction] = None
        self.active_committed = False
        self.executor_id: Optional[str] = None
        self.last_event_seq: Dict[str, int] = {}
        self.slots = [PayloadSlot(index=index) for index in
                      range(1, profile.required_deliveries + 1)]
        self.mission_failed = False

    def start(self, mission_id: str, now: float) -> None:
        if self.phase != MissionPhase.INIT:
            raise RuntimeError("mission has already started")
        if not mission_id.strip():
            raise ValueError("mission_id must not be empty")
        if not math.isfinite(float(now)) or float(now) < 0.0:
            raise ValueError("mission start time must be finite and non-negative")
        self.mission_id = mission_id
        self.started_at = float(now)
        self.phase = MissionPhase.SEARCH

    @property
    def committed_slots(self) -> int:
        return sum(slot.status == SlotStatus.COMMITTED for slot in self.slots)

    @property
    def remaining_slots(self) -> int:
        return len(self.slots) - self.committed_slots

    def ingest(self, candidates: Sequence[CandidateSnapshot],
               now: float) -> List[CandidateValidation]:
        if self.phase not in (MissionPhase.SEARCH, MissionPhase.EXECUTING):
            return [
                CandidateValidation(False, "mission_not_accepting_candidates")
                for _ in candidates
            ]
        return [self.queue.ingest(candidate, now) for candidate in candidates]

    def _next_free_slot(self) -> Optional[PayloadSlot]:
        return next((slot for slot in self.slots
                     if slot.status == SlotStatus.FREE), None)

    def _elapsed(self, now: float) -> float:
        return max(0.0, float(now) - self.started_at)

    def _new_action(self, command: str, reason: str,
                    entry: Optional[CandidateEntry] = None,
                    slot: Optional[PayloadSlot] = None) -> CoreAction:
        self.decision_seq += 1
        action = CoreAction(
            command=command,
            reason=reason,
            decision_seq=self.decision_seq,
            candidate_key=(entry.snapshot.key if entry else None),
            target_class=(entry.snapshot.class_name if entry else ""),
            attempt=(entry.attempts if entry else 0),
            payload_slot=(slot.index if slot else 0),
        )
        self.active_action = action
        return action

    def _return_action(self, reason: str) -> CoreAction:
        self.phase = MissionPhase.RETURN_HOME
        return self._new_action("RETURN_HOME", reason)

    def _delivery_work_eta(self, entries: Sequence[CandidateEntry],
                           current_xy: Tuple[float, float]) -> float:
        point = current_xy
        travel_distance = 0.0
        for entry in entries:
            target = (entry.snapshot.x, entry.snapshot.y)
            travel_distance += math.hypot(
                target[0] - point[0], target[1] - point[1])
            point = target
        travel_sec = (self.config.path_factor * travel_distance /
                      self.config.nominal_speed)
        return (travel_sec +
                len(entries) * self.config.delivery_reserve_per_slot)

    def _delivery_eta(self, entries: Sequence[CandidateEntry],
                      current_xy: Tuple[float, float]) -> float:
        point = current_xy if not entries else (
            entries[-1].snapshot.x, entries[-1].snapshot.y)
        return_distance = math.hypot(
            self.config.home_xy[0] - point[0],
            self.config.home_xy[1] - point[1],
        )
        return (self._delivery_work_eta(entries, current_xy) +
                self.config.path_factor * return_distance /
                self.config.nominal_speed +
                self.config.return_land_reserve)

    def should_stop_search(self, now: float,
                           current_xy: Tuple[float, float]) -> bool:
        ranked = self.queue.ranked(now, current_xy)
        if not ranked:
            return False
        planned = ranked[:self.remaining_slots]
        elapsed = self._elapsed(now)
        mission_remaining = self.config.mission_timeout - elapsed
        delivery_remaining = self.config.forced_return_at - elapsed
        return (
            mission_remaining <=
            self._delivery_eta(planned, current_xy) +
            self.config.decision_guard or
            delivery_remaining <=
            self._delivery_work_eta(planned, current_xy) +
            self.config.decision_guard
        )

    def _candidate_fits(self, entry: CandidateEntry, now: float,
                        current_xy: Tuple[float, float]) -> bool:
        elapsed = self._elapsed(now)
        return (
            elapsed + self._delivery_work_eta([entry], current_xy) <=
            self.config.forced_return_at and
            elapsed + self._delivery_eta([entry], current_xy) <=
            self.config.mission_timeout
        )

    def choose(self, now: float, current_xy: Tuple[float, float],
               route_complete: bool = False) -> Optional[CoreAction]:
        if (not math.isfinite(float(now)) or len(current_xy) != 2 or
                not all(math.isfinite(float(value)) for value in current_xy)):
            raise ValueError("choose requires a finite clock and position")
        if float(now) < self.started_at:
            raise ValueError("mission clock moved before its start")
        if self.phase != MissionPhase.SEARCH:
            return None
        if self.committed_slots >= self.profile.required_deliveries:
            return self._return_action("required_deliveries_complete")
        if self._elapsed(now) >= self.config.forced_return_at:
            return self._return_action("forced_return_deadline")

        interrupt = self.queue.ranked(
            now, current_xy, self.profile.interrupt_classes)
        fallback = self.queue.ranked(now, current_xy)
        entry = None
        reason = ""
        if interrupt and self._candidate_fits(interrupt[0], now, current_xy):
            entry = interrupt[0]
            reason = "high_weight_search_interrupt"
        elif route_complete or self.should_stop_search(now, current_xy):
            if fallback and self._candidate_fits(fallback[0], now, current_xy):
                entry = fallback[0]
                reason = ("coverage_complete_fallback" if route_complete
                          else "time_budget_fallback")
            else:
                return self._return_action(
                    "coverage_complete_insufficient_candidates" if
                    route_complete else "time_budget_no_feasible_candidate")
        if entry is None:
            return None

        slot = self._next_free_slot()
        if slot is None:
            return self._return_action("no_free_payload_slot")
        self.queue.reserve(entry.snapshot.key, slot.index)
        slot.status = SlotStatus.RESERVED
        slot.candidate_key = entry.snapshot.key
        self.phase = MissionPhase.EXECUTING
        self.active_committed = False
        return self._new_action("APPROACH", reason, entry, slot)

    def _validate_result_identity(self, event: ResultEvent) -> str:
        if event.mission_id != self.mission_id:
            return "mission_mismatch"
        if not event.executor_id.strip():
            return "executor_missing"
        if self.executor_id is not None and self.executor_id != event.executor_id:
            return "executor_changed"
        if event.event_seq <= 0:
            return "event_seq_invalid"
        previous_seq = self.last_event_seq.get(event.executor_id, -1)
        if event.event_seq <= previous_seq:
            return "event_duplicate_or_out_of_order"
        if self.active_action is None:
            return "no_active_decision"
        action = self.active_action
        if event.decision_seq != action.decision_seq:
            return "decision_mismatch"
        if event.command != action.command:
            return "command_mismatch"
        if not event.has_target:
            return "result_target_flag_missing"
        if action.candidate_key is None:
            return "active_decision_has_no_target"
        if event.candidate_key != action.candidate_key:
            return "target_mismatch"
        if event.target_class != action.target_class:
            return "class_mismatch"
        if event.attempt != action.attempt:
            return "attempt_mismatch"
        if event.payload_slot != action.payload_slot:
            return "payload_slot_mismatch"
        return "accepted"

    def _record_result_sequence(self, event: ResultEvent) -> None:
        if self.executor_id is None:
            self.executor_id = event.executor_id
        self.last_event_seq[event.executor_id] = event.event_seq

    def apply_result(self, event: ResultEvent,
                     now: float) -> Tuple[bool, str, Optional[CoreAction]]:
        if not math.isfinite(float(now)):
            raise ValueError("result clock must be finite")
        if float(now) < self.started_at:
            raise ValueError("mission clock moved before its start")
        reason = self._validate_result_identity(event)
        if reason != "accepted":
            return False, reason, None
        action = self.active_action
        key = action.candidate_key
        slot = self.slots[action.payload_slot - 1]

        if event.payload_committed:
            if not (event.status == "PROGRESS" and
                    event.stage == "RELEASE" and
                    not event.terminal and
                    not event.retryable and
                    bool(event.evidence_source.strip()) and
                    event.reason == "release_ack_success"):
                return False, "invalid_payload_commit_event", None
            self._record_result_sequence(event)
            if not self.active_committed:
                self.queue.commit(key, slot.index, event.reason)
                slot.status = SlotStatus.COMMITTED
                self.active_committed = True
            return True, "payload_committed", None

        if not event.terminal:
            if event.status not in ("ACCEPTED", "STARTED", "PROGRESS"):
                return False, "nonterminal_status_invalid", None
            self._record_result_sequence(event)
            return True, "progress_recorded", None

        if event.status not in (
                "SUCCEEDED", "FAILED", "REJECTED", "CANCELLED",
                "TIMED_OUT"):
            return False, "terminal_status_invalid", None

        if self.active_committed:
            if event.stage != "RECOVERY":
                return False, "committed_terminal_stage_invalid", None
            self._record_result_sequence(event)
            self.active_action = None
            if event.status != "SUCCEEDED":
                self.mission_failed = True
                return True, "committed_recovery_failed", self._return_action(
                    "committed_recovery_failed")
            if self.committed_slots >= self.profile.required_deliveries:
                return True, "required_deliveries_complete", self._return_action(
                    "required_deliveries_complete")
            self.phase = MissionPhase.SEARCH
            return True, "delivery_complete", self._new_action(
                "RESUME", "delivery_complete_resume_search")

        if event.status == "SUCCEEDED":
            return False, "success_without_payload_commit", None
        self._record_result_sequence(event)
        self.queue.fail(key, event.retryable, now, event.reason)
        slot.status = SlotStatus.FREE
        slot.candidate_key = None
        self.active_action = None
        self.phase = MissionPhase.SEARCH
        return True, "candidate_failed", self._new_action(
            "RESUME", "candidate_failed_resume_search")

    def mark_return_arrived(self) -> CoreAction:
        if self.phase != MissionPhase.RETURN_HOME:
            raise RuntimeError("mission is not returning")
        self.phase = MissionPhase.LAND
        return self._new_action("LAND", "return_home_reached")

    def mark_landed(self) -> None:
        if self.phase != MissionPhase.LAND:
            raise RuntimeError("mission is not landing")
        self.phase = MissionPhase.COMPLETE
