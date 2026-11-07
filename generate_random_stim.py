#!/usr/bin/env python3
"""Generates a seeded random stimulus of ~300 events exercising all 4 routing modes,
random commits, random route tables (valid and invalid addresses), and staging.

Outputs tb/stimulus.hex for Verilog RTL simulation and out/py_trace.txt from
the golden Python reference model.
"""

import os
import random
import sys

from routing_module import RoutingModule, StimulusGenerator
from routing_module.stimulus import StimCommand, StimEvent
from convert_stim import convert


def generate_random_stimulus(seed: int = 42, target_events: int = 300) -> StimulusGenerator:
    rng = random.Random(seed)
    gen = StimulusGenerator()

    # Track currently mapped addresses for Mode 1 AER
    mapped_addresses = []
    current_cycle = 0
    event_count = 0

    # Ensure all 4 modes are visited multiple times
    modes_sequence = [0, 1, 2, 3] * 4  # 16 phases
    rng.shuffle(modes_sequence)
    # Ensure every mode appears at least twice
    for m in [0, 1, 2, 3]:
        if m not in modes_sequence[:4]:
            modes_sequence.insert(0, m)

    phase_idx = 0
    while event_count < target_events:
        mode = modes_sequence[phase_idx % len(modes_sequence)]
        phase_idx += 1

        # Configuration commands for this phase
        gen.add_command("set_routing_mode", mode)

        # Active layers (1, 2, or 3)
        num_layers = rng.randint(1, 3)
        gen.add_command("set_active_layers", num_layers)

        # Active neurons per layer
        for lyr in range(3):
            k = rng.randint(2, 8)
            gen.add_command("set_active_neurons", lyr, k)

        # Mode-specific configuration
        if mode == 1:
            # Stage random route table entries
            num_routes = rng.randint(4, 8)
            phase_mapped = []
            for _ in range(num_routes):
                addr = rng.randint(10, 500)
                mask = rng.randint(1, 255)
                gen.add_command("load_route_table", addr, mask)
                phase_mapped.append(addr)
            # Add one entry with mask=0 (invalid address in table)
            zero_addr = rng.randint(501, 700)
            gen.add_command("load_route_table", zero_addr, 0)
            mapped_addresses.extend(phase_mapped)

        elif mode == 2:
            # TDM slot schedule (slots 0..3)
            num_slots = rng.randint(2, 4)
            for s in range(num_slots):
                assigned_layer = rng.randint(0, num_layers - 1)
                gen.add_command("set_tdm_schedule", s, assigned_layer)

        elif mode == 3:
            # Bypass configuration
            for lyr in range(3):
                bypass_en = rng.choice([True, False, False])
                gen.add_command("set_layer_bypass", lyr, 1 if bypass_en else 0)

        # Random commit timing:
        # 30% of the time, inject 1-2 events BEFORE commit to test staging between inputs!
        if rng.random() < 0.3 and event_count < target_events:
            pre_events = rng.randint(1, 2)
            for _ in range(pre_events):
                src = rng.randint(0, 7)
                dst = rng.choice([None, rng.randint(0, 7)])
                lyr = rng.randint(0, 1)
                gen.add_event(cycle=current_cycle, src=src, dst=dst, layer=lyr)
                current_cycle += 1
                event_count += 1

        # Commit staged configuration
        gen.add_command("commit")

        # Number of events to generate in this phase
        events_in_phase = min(rng.randint(15, 25), target_events - event_count)

        for _ in range(events_in_phase):
            if mode == 0:
                # Mode 0: Static crossbar
                src = rng.randint(0, 15)
                dst = rng.choice([None, rng.randint(0, 7)])
                # Mostly active layers, occasionally inactive layer
                lyr = rng.randint(0, num_layers) if num_layers < 3 else rng.randint(0, 2)
                gen.add_event(cycle=current_cycle, src=src, dst=dst, layer=lyr)

            elif mode == 1:
                # Mode 1: AER
                # 50% valid address, 50% invalid / unmapped address
                if mapped_addresses and rng.random() < 0.5:
                    src = rng.choice(mapped_addresses)
                else:
                    src = rng.randint(800, 1020)  # unmapped
                lyr = rng.randint(0, num_layers - 1)
                gen.add_event(cycle=current_cycle, src=src, dst=None, layer=lyr)

            elif mode == 2:
                # Mode 2: TDM
                src = rng.randint(0, 7)
                dst = rng.randint(0, 7)
                slot = rng.randint(0, 3)
                lyr = rng.randint(0, 2)
                gen.add_event(cycle=current_cycle, src=src, dst=dst, layer=lyr, slot=slot)

            elif mode == 3:
                # Mode 3: Bypass / Early exit
                src = rng.randint(0, 7)
                dst = rng.randint(0, 7)
                early_exit = rng.choice([True, False, False])
                lyr = rng.randint(0, num_layers - 1)
                gen.add_event(cycle=current_cycle, src=src, dst=dst, layer=lyr, early_exit=early_exit)

            current_cycle += 1
            event_count += 1

    return gen


def main():
    seed = 42
    target_events = 300
    hex_path = "tb/stimulus.hex"
    py_trace_path = "out/py_trace.txt"

    print(f"Generating seeded random stimulus (seed={seed}, target_events={target_events})...")
    gen = generate_random_stimulus(seed=seed, target_events=target_events)

    event_count = sum(1 for item in gen.items if isinstance(item, StimEvent))
    cmd_count = sum(1 for item in gen.items if isinstance(item, StimCommand))
    print(f"Stimulus created: {cmd_count} commands, {event_count} events across all 4 modes.")

    convert(gen, hex_path=hex_path, py_trace_path=py_trace_path)


if __name__ == "__main__":
    main()
