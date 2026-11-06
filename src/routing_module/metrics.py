"""Metrics tracking for routing module execution: routed, dropped, cycles."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class RoutingMetrics:
    """Tracks routing performance metrics: routed, dropped, and cycles.

    Attributes:
        routed: Number of events successfully routed or bypassed.
        dropped: Number of events dropped.
        cycles: Total elapsed simulation cycles.
        mode_routed: Count of routed events broken down by mode.
        mode_dropped: Count of dropped events broken down by mode.
        drop_reasons: Count of dropped events broken down by reason.
    """

    routed: int = 0
    dropped: int = 0
    cycles: int = 0
    mode_routed: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    mode_dropped: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    drop_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_routed(self, cycle: int, mode: int, layer: int) -> None:
        """Record a successfully routed event."""
        self.routed += 1
        self.mode_routed[mode] += 1
        if cycle >= self.cycles:
            self.cycles = cycle + 1

    def record_dropped(self, cycle: int, mode: int, layer: int, reason: str = "") -> None:
        """Record a dropped event."""
        self.dropped += 1
        self.mode_dropped[mode] += 1
        if reason:
            self.drop_reasons[reason] += 1
        if cycle >= self.cycles:
            self.cycles = cycle + 1

    def step_cycle(self, count: int = 1) -> None:
        """Advance simulation cycles."""
        self.cycles += count

    @property
    def total_events(self) -> int:
        """Total events processed."""
        return self.routed + self.dropped

    @property
    def delivery_rate(self) -> float:
        """Fraction of total events routed (0.0 to 1.0)."""
        tot = self.total_events
        return (self.routed / tot) if tot > 0 else 0.0

    @property
    def drop_rate(self) -> float:
        """Fraction of total events dropped (0.0 to 1.0)."""
        tot = self.total_events
        return (self.dropped / tot) if tot > 0 else 0.0

    def get_summary(self) -> Dict[str, Any]:
        """Return a dictionary summary of all metrics."""
        return {
            "routed": self.routed,
            "dropped": self.dropped,
            "cycles": self.cycles,
            "total_events": self.total_events,
            "delivery_rate": self.delivery_rate,
            "drop_rate": self.drop_rate,
            "mode_routed": dict(self.mode_routed),
            "mode_dropped": dict(self.mode_dropped),
            "drop_reasons": dict(self.drop_reasons),
        }

    def format_table(self) -> str:
        """Return a formatted text table summarizing the metrics."""
        tot = self.total_events
        d_rate = self.delivery_rate * 100.0
        dr_rate = self.drop_rate * 100.0
        lines = [
            "+-----------------------------------------------+",
            "|           ROUTING MODULE METRICS              |",
            "+----------------------+------------------------+",
            f"| Total Cycles         | {self.cycles:<22} |",
            f"| Total Events         | {tot:<22} |",
            f"| Routed Events        | {self.routed:<22} |",
            f"| Dropped Events       | {self.dropped:<22} |",
            f"| Delivery Rate        | {d_rate:>6.1f}%                 |",
            f"| Drop Rate            | {dr_rate:>6.1f}%                 |",
            "+----------------------+------------------------+",
        ]
        if self.mode_routed or self.mode_dropped:
            lines.append("| Mode Breakdown (Mode: Routed / Dropped)       |")
            all_modes = sorted(set(list(self.mode_routed.keys()) + list(self.mode_dropped.keys())))
            for m in all_modes:
                r = self.mode_routed.get(m, 0)
                d = self.mode_dropped.get(m, 0)
                lines.append(f"|   Mode {m:<14} | {r:<10} / {d:<9} |")
            lines.append("+-----------------------------------------------+")
        if self.drop_reasons:
            lines.append("| Drop Reason Breakdown                         |")
            for reason, cnt in sorted(self.drop_reasons.items()):
                lines.append(f"|   {reason:<18} | {cnt:<22} |")
            lines.append("+-----------------------------------------------+")
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metric counters."""
        self.routed = 0
        self.dropped = 0
        self.cycles = 0
        self.mode_routed.clear()
        self.mode_dropped.clear()
        self.drop_reasons.clear()
