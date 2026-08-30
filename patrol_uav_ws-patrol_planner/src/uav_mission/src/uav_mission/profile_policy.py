"""Competition profile loading and validation for the navigation mission.

This module deliberately has no ROS dependency so profile behavior can be
validated before a node starts publishing flight goals.
"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, Iterable, Tuple

import yaml


@dataclass(frozen=True)
class CompetitionProfile:
    """A closed set of task classes and their rule weights."""

    name: str
    weights: Dict[str, float]
    interrupt_top_k: int
    required_deliveries: int = 3

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("profile name must not be empty")
        if not self.weights:
            raise ValueError("profile must contain at least one class")
        for class_name, weight in self.weights.items():
            if not str(class_name).strip():
                raise ValueError("profile class name must not be empty")
            if not math.isfinite(float(weight)) or float(weight) <= 0.0:
                raise ValueError("profile weights must be finite and positive")
        if int(self.interrupt_top_k) != self.interrupt_top_k:
            raise ValueError("interrupt_top_k must be an integer")
        if self.interrupt_top_k <= 0 or self.interrupt_top_k > len(self.weights):
            raise ValueError("interrupt_top_k is outside the class range")
        if int(self.required_deliveries) != self.required_deliveries:
            raise ValueError("required_deliveries must be an integer")
        if self.required_deliveries <= 0:
            raise ValueError("required_deliveries must be positive")

    @property
    def interrupt_classes(self) -> Tuple[str, ...]:
        ranked = sorted(
            self.weights,
            key=lambda class_name: (-self.weights[class_name], class_name),
        )
        return tuple(ranked[:self.interrupt_top_k])

    def allows(self, class_name: str) -> bool:
        return class_name in self.weights

    def weight(self, class_name: str) -> float:
        try:
            return float(self.weights[class_name])
        except KeyError as exc:
            raise ValueError("class is not in profile: %s" % class_name) from exc


def _coerce_weights(raw_classes) -> Dict[str, float]:
    if not isinstance(raw_classes, dict):
        raise ValueError("profile classes must be a mapping")
    return {str(name): float(weight) for name, weight in raw_classes.items()}


def load_profile(path, profile_name: str) -> CompetitionProfile:
    """Load one named profile and fail closed for unknown names."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        raise ValueError("unknown competition profile: %s" % profile_name)
    raw = profiles[profile_name]
    if not isinstance(raw, dict):
        raise ValueError("profile entry must be a mapping")
    return CompetitionProfile(
        name=profile_name,
        weights=_coerce_weights(raw.get("classes")),
        interrupt_top_k=int(raw.get("interrupt_top_k", 0)),
        required_deliveries=int(raw.get("required_deliveries", 3)),
    )


def ensure_exact_classes(profile: CompetitionProfile,
                         expected: Iterable[str]) -> None:
    """Raise when a profile accidentally gains or loses a formal class."""

    expected_set = set(expected)
    actual_set = set(profile.weights)
    if actual_set != expected_set:
        raise ValueError(
            "profile classes mismatch: expected=%s actual=%s" %
            (sorted(expected_set), sorted(actual_set))
        )
