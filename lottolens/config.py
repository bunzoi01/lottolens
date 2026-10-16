"""User-adjustable settings, stored in the database's kv table."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields

DEFAULT_WEIGHTS = {"frequency": 0.30, "hot": 0.25, "overdue": 0.20, "pair": 0.15, "random": 0.10}


@dataclass
class Settings:
    window: str = "2"  # "1" | "2" | "5" | "10" | "all"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    hot_lookback: int = 25
    hot_z_threshold: float = 1.0  # explanation: "hot" if z >= this
    overdue_threshold: float = 1.5  # explanation: "overdue" if current gap >= this x average gap
    n_candidates: int = 50_000
    n_combos: int = 10
    sum_central: float = 0.70  # keep sums inside the central 70% of historical sums
    odd_min: int = 2
    odd_max: int = 4
    low_min: int = 2
    low_max: int = 4
    max_run: int = 2  # longest run of consecutive numbers allowed
    min_decades: int = 3
    max_overlap: int = 2  # no two combos share more than this many numbers
    max_uses: int = 3  # no number in more than this many combos
    lottonumbers_enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        s = cls()
        if not data:
            return s
        names = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k in names:
                setattr(s, k, v)
        s.weights = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (s.weights or {}).items() if k in DEFAULT_WEIGHTS}}
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    def normalised_weights(self) -> dict[str, float]:
        total = sum(max(0.0, w) for w in self.weights.values())
        if total <= 0:
            return {k: 1 / len(self.weights) for k in self.weights}
        return {k: max(0.0, w) / total for k, w in self.weights.items()}

    def algorithm_params(self) -> dict:
        """The settings that change suggestions (data-source toggles excluded)."""
        d = self.to_dict()
        d.pop("lottonumbers_enabled")
        d["weights"] = {k: round(v, 4) for k, v in self.normalised_weights().items()}
        return d

    def params_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.algorithm_params(), sort_keys=True).encode()).hexdigest()[:12]


def load_settings(db) -> Settings:
    return Settings.from_dict(db.kv_get("settings"))


def save_settings(db, settings: Settings) -> None:
    db.kv_set("settings", settings.to_dict())
