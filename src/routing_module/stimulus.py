"""Stimulus generator and parser for the Reconfigurable Neuron-Synapse Routing Module."""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union, TextIO
import re

from .core import RoutingModule, SpikeEvent
from .error_codes import ErrorCode


@dataclass
class StimCommand:
    """A staged configuration command in a stimulus file."""

    name: str
    args: List[Union[int, str]]

    def to_line(self) -> str:
        arg_str = " ".join(hex(a) if isinstance(a, int) and a > 9 and "mask" in self.name.lower() else str(a) for a in self.args)
        return f"CMD {self.name} {arg_str}".strip()


@dataclass
class StimEvent:
    """A spike stimulus entry in a stimulus file."""

    cycle: int
    src: int
    dst: Optional[int] = None
    layer: int = 0
    early_exit: bool = False
    slot: Optional[int] = None

    def to_line(self) -> str:
        dst_str = str(self.dst) if self.dst is not None else "-"
        slot_str = str(self.slot) if self.slot is not None else "-"
        exit_str = "1" if self.early_exit else "0"
        return f"EVENT {self.cycle} {self.src} {dst_str} {self.layer} {exit_str} {slot_str}"


class StimulusGenerator:
    """Creates, writes, and executes stimulus scripts containing commands and spike events."""

    def __init__(self):
        self.items: List[Union[StimCommand, StimEvent]] = []

    def add_command(self, name: str, *args: Union[int, str]) -> "StimulusGenerator":
        """Add a configuration command."""
        self.items.append(StimCommand(name=name, args=list(args)))
        return self

    def add_event(
        self,
        cycle: int,
        src: int,
        dst: Optional[int] = None,
        layer: int = 0,
        early_exit: bool = False,
        slot: Optional[int] = None,
    ) -> "StimulusGenerator":
        """Add a spike event."""
        self.items.append(
            StimEvent(
                cycle=cycle,
                src=src,
                dst=dst,
                layer=layer,
                early_exit=early_exit,
                slot=slot,
            )
        )
        return self

    def write_to_file(self, target: Union[str, TextIO]) -> None:
        """Write all staged commands and events to a stimulus file."""

        def _write(f):
            f.write("# Reconfigurable Neuron-Synapse Routing Stimulus File\n")
            f.write("# Format:\n")
            f.write("#   CMD <command_name> <arg1> <arg2> ...\n")
            f.write("#   EVENT <cycle> <src> <dst> <layer> <early_exit> <slot>\n\n")
            for item in self.items:
                f.write(item.to_line() + "\n")

        if isinstance(target, str):
            with open(target, "w", encoding="utf-8") as f:
                _write(f)
        else:
            _write(target)

    @classmethod
    def load_from_file(cls, source: Union[str, TextIO]) -> "StimulusGenerator":
        """Parse a stimulus file and return a StimulusGenerator instance."""
        gen = cls()

        def _parse(lines):
            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                tokens = line.split()
                directive = tokens[0].upper()
                if directive == "CMD":
                    cmd_name = tokens[1]
                    args = []
                    for t in tokens[2:]:
                        if t.startswith("0x") or t.startswith("0X"):
                            args.append(int(t, 16))
                        elif t.isdigit() or (t.startswith("-") and t[1:].isdigit()):
                            args.append(int(t))
                        elif t.lower() in ("true", "false"):
                            args.append(1 if t.lower() == "true" else 0)
                        else:
                            args.append(t)
                    gen.add_command(cmd_name, *args)
                elif directive == "EVENT":
                    cycle = int(tokens[1])
                    src = int(tokens[2])
                    dst = int(tokens[3]) if tokens[3] != "-" else None
                    layer = int(tokens[4]) if len(tokens) > 4 else 0
                    early_exit = bool(int(tokens[5])) if len(tokens) > 5 and tokens[5] != "-" else False
                    slot = int(tokens[6]) if len(tokens) > 6 and tokens[6] != "-" else None
                    gen.add_event(cycle, src, dst, layer, early_exit, slot)

        if isinstance(source, str):
            with open(source, "r", encoding="utf-8") as f:
                _parse(f)
        else:
            _parse(source)

        return gen

    def execute(self, router: RoutingModule) -> None:
        """Execute all commands and events in order against a RoutingModule."""
        for item in self.items:
            if isinstance(item, StimCommand):
                method = getattr(router, item.name, None)
                if method is None:
                    raise AttributeError(f"RoutingModule has no method named '{item.name}'")
                method(*item.args)
            elif isinstance(item, StimEvent):
                router.route(
                    src=item.src,
                    dst=item.dst,
                    layer=item.layer,
                    cycle=item.cycle,
                    early_exit=item.early_exit,
                    slot=item.slot,
                )

    # -------------------------------------------------------------------------
    # Benchmark Stimulus Generators
    # -------------------------------------------------------------------------

    @classmethod
    def generate_mode0_static_crossbar(cls) -> "StimulusGenerator":
        """Generate stimulus exercising Mode 0: layer enable masks and neuron enable masks."""
        gen = cls()
        # Enable 2 layers (layers 0 and 1; layer 2 disabled)
        gen.add_command("set_routing_mode", 0)
        gen.add_command("set_active_layers", 2)
        # Layer 0: all 8 neurons enabled
        gen.add_command("set_active_neurons", 0, 8)
        # Layer 1: only first 4 neurons enabled (neurons 0..3)
        gen.add_command("set_active_neurons", 1, 4)
        gen.add_command("commit")

        # Events:
        # Layer 0 (active), dst 0..3 (active) -> ROUTED
        gen.add_event(cycle=0, src=0, dst=0, layer=0)
        gen.add_event(cycle=1, src=1, dst=1, layer=0)
        gen.add_event(cycle=2, src=2, dst=5, layer=0)  # neuron 5 is enabled on layer 0 -> ROUTED

        # Layer 1 (active), dst 2 (active) -> ROUTED
        gen.add_event(cycle=3, src=0, dst=2, layer=1)
        # Layer 1 (active), dst 6 (masked out, only 0..3 active) -> DROPPED (NEURON_MASKED)
        gen.add_event(cycle=4, src=1, dst=6, layer=1)

        # Layer 2 (disabled, active_layers=2) -> DROPPED (LAYER_DISABLED)
        gen.add_event(cycle=5, src=0, dst=0, layer=2)
        return gen

    @classmethod
    def generate_mode1_aer(cls) -> "StimulusGenerator":
        """Generate stimulus exercising Mode 1: source LUT lookup, multicast dst mask, invalid addr drop."""
        gen = cls()
        gen.add_command("set_routing_mode", 1)
        gen.add_command("set_active_layers", 3)
        gen.add_command("set_active_neurons", 0, 8)
        # Mappings:
        # src 10 -> multicast to neurons 0, 2, 4 (mask 0b00010101 = 0x15)
        gen.add_command("load_route_table", 10, 0x15)
        # src 20 -> unicast to neuron 7 (mask 0x80)
        gen.add_command("load_route_table", 20, 0x80)
        # src 30 -> all 8 neurons broadcast (mask 0xFF)
        gen.add_command("load_route_table", 30, 0xFF)
        gen.add_command("commit")

        # Events:
        # src 10 (mapped) -> ROUTED multicast
        gen.add_event(cycle=0, src=10, layer=0)
        # src 20 (mapped) -> ROUTED unicast
        gen.add_event(cycle=1, src=20, layer=0)
        # src 99 (unmapped / invalid address) -> DROPPED (INVALID_ADDR)
        gen.add_event(cycle=2, src=99, layer=0)
        # src 30 (mapped broadcast) -> ROUTED
        gen.add_event(cycle=3, src=30, layer=0)
        return gen

    @classmethod
    def generate_mode2_tdm(cls) -> "StimulusGenerator":
        """Generate stimulus exercising Mode 2: shared physical pool, TDM schedule, slot matching."""
        gen = cls()
        gen.add_command("set_routing_mode", 2)
        gen.add_command("set_active_layers", 3)
        for lyr in range(3):
            gen.add_command("set_active_neurons", lyr, 8)
        # Schedule: Slot 0 -> Layer 0, Slot 1 -> Layer 1, Slot 2 -> Layer 2
        gen.add_command("set_tdm_schedule", 0, 0)
        gen.add_command("set_tdm_schedule", 1, 1)
        gen.add_command("set_tdm_schedule", 2, 2)
        gen.add_command("commit")

        # Events:
        # Cycle 0 (slot 0): Layer 0 -> Matches slot 0 -> ROUTED to physical neuron
        gen.add_event(cycle=0, src=0, dst=3, layer=0, slot=0)
        # Cycle 0 (slot 0): Layer 1 -> Slot mismatch (slot 0 is layer 0) -> DROPPED
        gen.add_event(cycle=0, src=1, dst=3, layer=1, slot=0)
        # Cycle 1 (slot 1): Layer 1 -> Matches slot 1 -> ROUTED
        gen.add_event(cycle=1, src=2, dst=5, layer=1, slot=1)
        # Cycle 2 (slot 2): Layer 2 -> Matches slot 2 -> ROUTED
        gen.add_event(cycle=2, src=3, dst=1, layer=2, slot=2)
        return gen

    @classmethod
    def generate_mode3_bypass(cls) -> "StimulusGenerator":
        """Generate stimulus exercising Mode 3: early exit and layer bypass."""
        gen = cls()
        gen.add_command("set_routing_mode", 3)
        gen.add_command("set_active_layers", 3)
        for lyr in range(3):
            gen.add_command("set_active_neurons", lyr, 8)
        # Set Layer 1 to bypass mode
        gen.add_command("set_layer_bypass", 1, 1)
        gen.add_command("commit")

        # Events:
        # Cycle 0: Early exit directly from Layer 0 -> ROUTED (EARLY_EXIT)
        gen.add_event(cycle=0, src=0, dst=0, layer=0, early_exit=True)
        # Cycle 1: Event to Layer 1 (configured as bypass) -> ROUTED (BYPASS_LAYER_1)
        gen.add_event(cycle=1, src=1, dst=2, layer=1, early_exit=False)
        # Cycle 2: Standard route to Layer 0 -> ROUTED
        gen.add_event(cycle=2, src=2, dst=4, layer=0, early_exit=False)
        return gen

    @classmethod
    def generate_midrun_reconfiguration(cls) -> "StimulusGenerator":
        """Generate stimulus exercising mid-run reconfiguration across all 4 modes."""
        gen = cls()

        # Phase 1: Mode 0 (Static Crossbar)
        gen.add_command("set_routing_mode", 0)
        gen.add_command("set_active_layers", 3)
        gen.add_command("set_active_neurons", 0, 8)
        gen.add_command("set_active_neurons", 1, 4)  # only 0..3 active
        gen.add_command("commit")
        gen.add_event(cycle=0, src=0, dst=0, layer=0)
        gen.add_event(cycle=1, src=1, dst=5, layer=1)  # dropped (masked)
        gen.add_event(cycle=2, src=2, dst=2, layer=1)  # routed

        # Phase 2: Mid-run reconfigure to Mode 1 (AER)
        gen.add_command("set_routing_mode", 1)
        gen.add_command("load_route_table", 101, 0x07)  # multicast to 0, 1, 2
        gen.add_command("load_route_table", 102, 0x80)  # unicast to 7
        gen.add_command("commit")
        gen.add_event(cycle=3, src=101, layer=0)  # routed multicast
        gen.add_event(cycle=4, src=999, layer=0)  # unmapped -> dropped

        # Phase 3: Mid-run reconfigure to Mode 2 (TDM)
        gen.add_command("set_routing_mode", 2)
        gen.add_command("set_tdm_schedule", 0, 0)
        gen.add_command("set_tdm_schedule", 1, 1)
        gen.add_command("commit")
        gen.add_event(cycle=5, src=0, dst=2, layer=0, slot=0)  # routed (slot 0 == layer 0)
        gen.add_event(cycle=6, src=1, dst=2, layer=1, slot=0)  # dropped (slot mismatch)
        gen.add_event(cycle=7, src=2, dst=3, layer=1, slot=1)  # routed (slot 1 == layer 1)

        # Phase 4: Mid-run reconfigure to Mode 3 (Bypass / Early exit)
        gen.add_command("set_routing_mode", 3)
        gen.add_command("set_layer_bypass", 1, 1)
        gen.add_command("commit")
        gen.add_event(cycle=8, src=0, dst=1, layer=0, early_exit=True)  # early exit
        gen.add_event(cycle=9, src=2, dst=2, layer=1)                   # bypassed
        return gen
