"""Trace writer and trace record structures for routing module execution."""

import csv
import io
from dataclasses import dataclass, field
from typing import List, Optional, Union, TextIO


@dataclass(frozen=True)
class TraceRecord:
    """A single routing event trace record.

    Attributes:
        cycle: Simulation cycle index.
        mode: Routing mode in effect during the event.
        src: Source neuron or address identifier.
        dst: Destination neuron identifier, multicast mask, or target list.
        status: Routing outcome ("ROUTED", "DROPPED", "BYPASSED").
        layer: Target or processing layer index.
        reason: Optional diagnostic string explaining drops or bypasses.
    """

    cycle: int
    mode: int
    src: int
    dst: Union[int, str, List[int]]
    status: str
    layer: int
    reason: str = ""

    def as_tuple(self) -> tuple:
        """Return the core trace tuple (cycle, mode, src, dst, status, layer)."""
        return (self.cycle, self.mode, self.src, self.dst, self.status, self.layer)


class TraceWriter:
    """Collects and writes cycle-by-cycle routing execution traces."""

    def __init__(self):
        self._records: List[TraceRecord] = []

    def log(
        self,
        cycle: int,
        mode: int,
        src: int,
        dst: Union[int, str, List[int]],
        status: str,
        layer: int,
        reason: str = "",
    ) -> TraceRecord:
        """Log a new trace record and append to history."""
        rec = TraceRecord(
            cycle=cycle,
            mode=mode,
            src=src,
            dst=dst,
            status=status,
            layer=layer,
            reason=reason,
        )
        self._records.append(rec)
        return rec

    @property
    def records(self) -> List[TraceRecord]:
        """Return a copy of all logged records."""
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        """Clear all logged records."""
        self._records.clear()

    def write_csv(self, target: Union[str, TextIO]) -> None:
        """Write trace records to a CSV file or file-like object."""
        fieldnames = ["cycle", "mode", "src", "dst", "status", "layer", "reason"]
        
        def _write(f):
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self._records:
                dst_repr = hex(r.dst) if isinstance(r.dst, int) and r.dst > 9 else str(r.dst)
                writer.writerow(
                    {
                        "cycle": r.cycle,
                        "mode": r.mode,
                        "src": r.src,
                        "dst": dst_repr,
                        "status": r.status,
                        "layer": r.layer,
                        "reason": r.reason,
                    }
                )

        if isinstance(target, str):
            with open(target, "w", newline="", encoding="utf-8") as f:
                _write(f)
        else:
            _write(target)

    def format_table(self, limit: Optional[int] = 20) -> str:
        """Format traces as a readable ASCII table."""
        if not self._records:
            return "No traces logged."

        records_to_show = self._records[:limit] if limit else self._records
        header = f"{'Cycle':<7} | {'Mode':<5} | {'Src':<5} | {'Dst':<10} | {'Status':<9} | {'Layer':<6} | {'Reason':<16}"
        sep = "-" * len(header)
        lines = [header, sep]
        for r in records_to_show:
            dst_str = hex(r.dst) if isinstance(r.dst, int) and r.dst > 9 else str(r.dst)
            lines.append(
                f"{r.cycle:<7} | {r.mode:<5} | {r.src:<5} | {dst_str:<10} | {r.status:<9} | {r.layer:<6} | {r.reason:<16}"
            )
        if limit and len(self._records) > limit:
            lines.append(f"... ({len(self._records) - limit} more records truncated)")
        return "\n".join(lines)
