#!/usr/bin/env python3
"""Converts Python stimulus (commands and events) into a 64-bit hex file for $readmemh.

Also executes the stimulus using the reference Python RoutingModule to generate
the golden reference trace out/py_trace.txt.
"""

import argparse
import os
import sys

from routing_module import RoutingModule, StimulusGenerator
from routing_module.stimulus import StimCommand, StimEvent

# Command opcodes matching RTL
CMD_SET_MODE    = 1
CMD_SET_LAYERS  = 2
CMD_SET_NEURONS = 3
CMD_LOAD_ROUTE  = 4
CMD_SET_TDM     = 5
CMD_SET_BYPASS  = 6
CMD_COMMIT      = 7
CMD_EOF         = 127  # 7'h7F sentinel


def pack_command(cmd_type: int, arg0: int = 0, arg1: int = 0) -> str:
    """Pack a configuration command into a 16-hex-digit 64-bit string."""
    val = ((cmd_type & 0x7F) << 56) | ((arg0 & 0xFFFF) << 40) | ((arg1 & 0xFFFFFF) << 16)
    return f"{val:016x}"


def pack_event(
    cycle: int,
    src: int,
    dst: int = None,
    layer: int = 0,
    early_exit: bool = False,
    slot: int = None,
) -> str:
    """Pack a spike stimulus event into a 16-hex-digit 64-bit string."""
    d = 0xFF if dst is None else (dst & 0xFF)
    s = 0x7F if slot is None else (slot & 0x7F)
    ee = 1 if early_exit else 0
    val = (1 << 63)
    val |= ((cycle & 0x7FFFFFFF) << 32)
    val |= ((src & 0xFFF) << 20)
    val |= (d << 12)
    val |= ((layer & 0xF) << 8)
    val |= (ee << 7)
    val |= s
    return f"{val:016x}"


def get_demo_stimulus() -> StimulusGenerator:
    """Build the exact multi-mode scenario from demo.py."""
    gen = StimulusGenerator()

    # Phase 1: Mode 0 - Static Crossbar with Enable Masks
    gen.add_command("set_routing_mode", 0)
    gen.add_command("set_active_layers", 2)
    gen.add_command("set_active_neurons", 0, 8)
    gen.add_command("set_active_neurons", 1, 4)
    gen.add_command("commit")

    gen.add_event(cycle=0, src=0, dst=0, layer=0)
    gen.add_event(cycle=1, src=1, dst=1, layer=0)
    gen.add_event(cycle=2, src=2, dst=5, layer=0)
    gen.add_event(cycle=3, src=3, dst=2, layer=1)
    gen.add_event(cycle=4, src=4, dst=6, layer=1)
    gen.add_event(cycle=5, src=5, dst=None, layer=2)

    # Phase 2: Mode 1 - AER Multicast & Lookup
    gen.add_command("set_routing_mode", 1)
    gen.add_command("set_active_layers", 3)
    gen.add_command("set_active_neurons", 0, 8)
    gen.add_command("set_active_neurons", 1, 8)
    gen.add_command("set_active_neurons", 2, 8)
    gen.add_command("load_route_table", 100, 0x15)
    gen.add_command("load_route_table", 101, 0x80)
    gen.add_command("load_route_table", 102, 0xFF)

    # Spike arriving prior to commit (must route in Mode 0)
    gen.add_event(cycle=6, src=0, dst=0, layer=0)

    gen.add_command("commit")
    gen.add_event(cycle=7, src=100, dst=None, layer=0)
    gen.add_event(cycle=8, src=101, dst=None, layer=0)
    gen.add_event(cycle=9, src=999, dst=None, layer=0)
    gen.add_event(cycle=10, src=102, dst=None, layer=1)

    # Phase 3: Mode 2 - TDM Neuron Reuse
    gen.add_command("set_routing_mode", 2)
    gen.add_command("set_tdm_schedule", 0, 0)
    gen.add_command("set_tdm_schedule", 1, 1)
    gen.add_command("set_tdm_schedule", 2, 2)
    gen.add_command("commit")

    gen.add_event(cycle=11, src=0, dst=2, layer=0, slot=0)
    gen.add_event(cycle=12, src=1, dst=2, layer=1, slot=0)
    gen.add_event(cycle=13, src=2, dst=5, layer=1, slot=1)
    gen.add_event(cycle=14, src=3, dst=7, layer=2, slot=2)

    # Phase 4: Mode 3 - Layer Bypass & Early Exit
    gen.add_command("set_routing_mode", 3)
    gen.add_command("set_layer_bypass", 1, 1)
    gen.add_command("commit")

    gen.add_event(cycle=15, src=0, dst=0, layer=0, early_exit=True)
    gen.add_event(cycle=16, src=1, dst=3, layer=1, early_exit=False)
    gen.add_event(cycle=17, src=2, dst=4, layer=0, early_exit=False)
    gen.add_command("set_active_neurons", 0, 4)
    gen.add_command("commit")
    gen.add_event(cycle=18, src=3, dst=7, layer=0, early_exit=False)

    return gen


def convert(gen: StimulusGenerator, hex_path: str, py_trace_path: str):
    """Write hex file for Verilog $readmemh and run Python reference to generate py_trace."""
    os.makedirs(os.path.dirname(os.path.abspath(hex_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(py_trace_path)), exist_ok=True)

    hex_lines = []

    for item in gen.items:
        if isinstance(item, StimCommand):
            cname = item.name
            args = item.args
            if cname == "set_routing_mode":
                hex_lines.append(pack_command(CMD_SET_MODE, arg0=args[0]))
            elif cname == "set_active_layers":
                hex_lines.append(pack_command(CMD_SET_LAYERS, arg0=args[0]))
            elif cname == "set_active_neurons":
                hex_lines.append(pack_command(CMD_SET_NEURONS, arg0=args[0], arg1=args[1]))
            elif cname == "load_route_table":
                hex_lines.append(pack_command(CMD_LOAD_ROUTE, arg0=args[0], arg1=args[1]))
            elif cname == "set_tdm_schedule":
                hex_lines.append(pack_command(CMD_SET_TDM, arg0=args[0], arg1=args[1]))
            elif cname == "set_layer_bypass":
                hex_lines.append(pack_command(CMD_SET_BYPASS, arg0=args[0], arg1=1 if args[1] else 0))
            elif cname == "commit":
                hex_lines.append(pack_command(CMD_COMMIT))
        elif isinstance(item, StimEvent):
            hex_lines.append(
                pack_event(
                    cycle=item.cycle,
                    src=item.src,
                    dst=item.dst,
                    layer=item.layer,
                    early_exit=item.early_exit,
                    slot=item.slot,
                )
            )

    # Append EOF sentinel and pad to 2048 words for clean $readmemh loading
    hex_lines.append(pack_command(CMD_EOF))
    while len(hex_lines) < 2048:
        hex_lines.append(pack_command(CMD_EOF))

    # Write hex file
    with open(hex_path, "w", encoding="utf-8") as f:
        for line in hex_lines:
            f.write(line + "\n")

    print(f"Wrote {len(hex_lines)} hex entries to {hex_path}")

    # Run Python reference simulation to generate reference trace
    router = RoutingModule()
    gen.execute(router)
    router.trace_writer.write_csv(py_trace_path)
    # Ensure Unix line endings (\n) matching Verilog $fdisplay
    with open(py_trace_path, "rb") as f:
        content = f.read().replace(b"\r\n", b"\n")
    with open(py_trace_path, "wb") as f:
        f.write(content)
    print(f"Generated Python reference trace: {py_trace_path} ({len(router.trace_writer.records)} events)")


def main():
    parser = argparse.ArgumentParser(description="Convert Python stimulus to Verilog hex")
    parser.add_argument("--stim", type=str, default="", help="Path to input .stim file")
    parser.add_argument("--demo", action="store_true", default=True, help="Use demo scenario")
    parser.add_argument("--hex-out", type=str, default="tb/stimulus.hex", help="Output hex file")
    parser.add_argument("--trace-out", type=str, default="out/py_trace.txt", help="Output reference trace file")
    args = parser.parse_args()

    if args.stim:
        gen = StimulusGenerator.load_from_file(args.stim)
    else:
        gen = get_demo_stimulus()

    convert(gen, args.hex_out, args.trace_out)


if __name__ == "__main__":
    main()
