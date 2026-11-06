#!/usr/bin/env python3
"""Demonstration of the Reconfigurable Neuron-Synapse Routing Module.

Executes all 4 modes, demonstrates mid-run dynamic reconfiguration,
prints structured readable tables, and saves an analytical matplotlib plot.
"""

import sys
import os

# Use non-interactive backend for headless headless execution
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from routing_module import (
    RoutingModule,
    ErrorCode,
    MODE_STATIC_CROSSBAR,
    MODE_AER,
    MODE_TDM,
    MODE_BYPASS,
)


def run_demo():
    print("=" * 80)
    print("      RECONFIGURABLE NEURON-SYNAPSE ROUTING MODULE DEMONSTRATION")
    print("=" * 80)
    print("Architecture: 3 Hidden Layers (Layers 0, 1, 2) x 8 Neurons (0..7)")
    print("Physical Resources: 8 Shared Physical Neurons")
    print()

    router = RoutingModule()
    phase_transitions = []  # list of (cycle, phase_name, mode)

    # -------------------------------------------------------------------------
    # Phase 1: Mode 0 - Static Crossbar with Layer & Neuron Enable Masks
    # -------------------------------------------------------------------------
    print(">>> Phase 1: Mode 0 - Static Crossbar with Enable Masks")
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.set_active_layers(2)          # Layers 0 and 1 active; Layer 2 disabled
    router.set_active_neurons(0, 8)       # Layer 0: all 8 neurons enabled
    router.set_active_neurons(1, 4)       # Layer 1: only neurons 0..3 enabled
    router.commit()
    phase_transitions.append((0, "Mode 0: Static Crossbar", MODE_STATIC_CROSSBAR))

    # Cycle 0..5 events:
    router.route(src=0, dst=0, layer=0, cycle=0)   # Routed (Layer 0, N0 enabled)
    router.route(src=1, dst=1, layer=0, cycle=1)   # Routed (Layer 0, N1 enabled)
    router.route(src=2, dst=5, layer=0, cycle=2)   # Routed (Layer 0, N5 enabled)
    router.route(src=3, dst=2, layer=1, cycle=3)   # Routed (Layer 1, N2 enabled)
    router.route(src=4, dst=6, layer=1, cycle=4)   # Dropped (Layer 1, N6 masked)
    router.route(src=5, dst=0, layer=2, cycle=5)   # Dropped (Layer 2 disabled)

    # -------------------------------------------------------------------------
    # Phase 2: Mid-Run Reconfiguration to Mode 1 - AER Multicast & Lookup
    # -------------------------------------------------------------------------
    print(">>> Phase 2: Mid-Run Reconfiguration to Mode 1 - AER")
    # Demonstrate staged configuration between inputs:
    # Stage Mode 1 and route table entries
    router.set_routing_mode(MODE_AER)
    router.set_active_layers(3)           # All 3 layers active
    router.set_active_neurons(0, 8)
    router.set_active_neurons(1, 8)
    router.set_active_neurons(2, 8)
    router.load_route_table(src=100, dst_mask=0x15)  # Multicast to neurons 0, 2, 4 (0b00010101)
    router.load_route_table(src=101, dst_mask=0x80)  # Unicast to neuron 7 (0b10000000)
    router.load_route_table(src=102, dst_mask=0xFF)  # Broadcast to all 8 neurons

    # Input arrives BEFORE commit: must still route according to active config (Mode 0)!
    pre_commit_rec = router.route(src=0, dst=0, layer=0, cycle=6)[0]
    print(f"  [Inter-spike check] Staged Mode=1, Active Mode={pre_commit_rec.mode} (Executed in Mode 0 prior to commit)")

    # Now commit mid-run:
    router.commit()
    phase_transitions.append((7, "Mode 1: AER Multicast", MODE_AER))

    # Events in Mode 1:
    router.route(src=100, layer=0, cycle=7)  # Routed: Multicast (0x15)
    router.route(src=101, layer=0, cycle=8)  # Routed: Unicast (0x80)
    router.route(src=999, layer=0, cycle=9)  # Dropped: Unmapped address (INVALID_ADDR)
    router.route(src=102, layer=1, cycle=10) # Routed: Broadcast (0xFF)

    # -------------------------------------------------------------------------
    # Phase 3: Mid-Run Reconfiguration to Mode 2 - TDM Neuron Reuse
    # -------------------------------------------------------------------------
    print(">>> Phase 3: Mid-Run Reconfiguration to Mode 2 - TDM Neuron Reuse")
    router.set_routing_mode(MODE_TDM)
    # Configure 3-slot cyclic schedule:
    # Slot 0 -> Layer 0, Slot 1 -> Layer 1, Slot 2 -> Layer 2
    router.set_tdm_schedule(slot=0, layer=0)
    router.set_tdm_schedule(slot=1, layer=1)
    router.set_tdm_schedule(slot=2, layer=2)
    router.commit()
    phase_transitions.append((11, "Mode 2: TDM Reuse", MODE_TDM))

    # Events in Mode 2:
    # Slot 0: Layer 0 requested -> Slot matches -> Routed to physical neuron
    router.route(src=0, dst=2, layer=0, cycle=11, slot=0)
    # Slot 0: Layer 1 requested -> Slot mismatch -> Dropped
    router.route(src=1, dst=2, layer=1, cycle=12, slot=0)
    # Slot 1: Layer 1 requested -> Slot matches -> Routed to physical neuron
    router.route(src=2, dst=5, layer=1, cycle=13, slot=1)
    # Slot 2: Layer 2 requested -> Slot matches -> Routed to physical neuron
    router.route(src=3, dst=7, layer=2, cycle=14, slot=2)

    # -------------------------------------------------------------------------
    # Phase 4: Mid-Run Reconfiguration to Mode 3 - Layer Bypass & Early Exit
    # -------------------------------------------------------------------------
    print(">>> Phase 4: Mid-Run Reconfiguration to Mode 3 - Bypass / Early Exit")
    router.set_routing_mode(MODE_BYPASS)
    router.set_layer_bypass(layer=1, enable=True)  # Layer 1 set to bypass
    router.commit()
    phase_transitions.append((15, "Mode 3: Bypass / Early Exit", MODE_BYPASS))

    # Events in Mode 3:
    # Early exit directly from Layer 0 -> Routed (EARLY_EXIT)
    router.route(src=0, dst=0, layer=0, cycle=15, early_exit=True)
    # Arriving at Layer 1 (configured to bypass) -> Routed to Layer 2 directly (BYPASS_LAYER_1)
    router.route(src=1, dst=3, layer=1, cycle=16, early_exit=False)
    # Normal feedforward through Layer 0 -> Routed
    router.route(src=2, dst=4, layer=0, cycle=17, early_exit=False)
    # Mask neuron 7 on Layer 0 and route to it -> Dropped (NEURON_MASKED)
    router.set_active_neurons(0, 4)  # only neurons 0..3 enabled
    router.commit()
    router.route(src=3, dst=7, layer=0, cycle=18, early_exit=False)

    print()
    # -------------------------------------------------------------------------
    # Print Readable Tables
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("                         EXECUTION TRACE TABLE")
    print("=" * 80)
    print(router.trace_writer.format_table(limit=30))
    print()

    print("=" * 80)
    print("                       PER-MODE METRICS BREAKDOWN")
    print("=" * 80)
    mode_names = {
        MODE_STATIC_CROSSBAR: "Mode 0: Static Crossbar",
        MODE_AER: "Mode 1: AER Multicast",
        MODE_TDM: "Mode 2: TDM Reuse",
        MODE_BYPASS: "Mode 3: Bypass / Exit",
    }
    header = f"{'Routing Mode':<28} | {'Routed':<8} | {'Dropped':<8} | {'Total':<8} | {'Delivery Rate':<14}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for m in (MODE_STATIC_CROSSBAR, MODE_AER, MODE_TDM, MODE_BYPASS):
        r = router.metrics.mode_routed.get(m, 0)
        d = router.metrics.mode_dropped.get(m, 0)
        tot = r + d
        rate = f"{(r / tot) * 100:.1f}%" if tot > 0 else "N/A"
        print(f"{mode_names[m]:<28} | {r:<8} | {d:<8} | {tot:<8} | {rate:<14}")
    print(sep)
    print(f"{'OVERALL TOTALS':<28} | {router.metrics.routed:<8} | {router.metrics.dropped:<8} | {router.metrics.total_events:<8} | {router.metrics.delivery_rate * 100:.1f}%")
    print("=" * 80)
    print()

    print("=" * 80)
    print("                      CUMULATIVE HARDWARE METRICS")
    print("=" * 80)
    print(router.metrics.format_table())
    print()

    # -------------------------------------------------------------------------
    # Generate Publication-Quality Matplotlib Plot
    # -------------------------------------------------------------------------
    output_plot = "demo_results.png"
    print(f">>> Generating analytical matplotlib plot -> {output_plot}...")
    generate_plot(router, phase_transitions, output_plot)
    print(f">>> Successfully generated and saved plot to: {os.path.abspath(output_plot)}")
    print("=" * 80)


def generate_plot(router: RoutingModule, phase_transitions, output_path: str):
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        "Reconfigurable Neuron-Synapse Routing Module: Performance & Architecture Analysis",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )

    # -------------------------------------------------------------------------
    # Subplot 1: Per-Mode Routed vs Dropped Spikes
    # -------------------------------------------------------------------------
    modes = [0, 1, 2, 3]
    labels = ["Mode 0\nStatic Crossbar", "Mode 1\nAER Multicast", "Mode 2\nTDM Reuse", "Mode 3\nBypass/Exit"]
    routed_counts = [router.metrics.mode_routed.get(m, 0) for m in modes]
    dropped_counts = [router.metrics.mode_dropped.get(m, 0) for m in modes]

    x = np.arange(len(modes))
    width = 0.35

    rects1 = ax1.bar(x - width / 2, routed_counts, width, label="Routed Spikes", color="#2ca02c", edgecolor="black")
    rects2 = ax1.bar(x + width / 2, dropped_counts, width, label="Dropped Spikes", color="#d62728", edgecolor="black")

    ax1.set_ylabel("Spike Count", fontweight="bold")
    ax1.set_title("Spike Outcomes across 4 Routing Modes", fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.legend(loc="upper right")
    ax1.grid(axis="y", linestyle="--", alpha=0.5)

    # Add count labels above bars
    def autolabel(rects, ax):
        for rect in rects:
            height = rect.get_height()
            if height > 0:
                ax.annotate(
                    f"{int(height)}",
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontweight="bold",
                )

    autolabel(rects1, ax1)
    autolabel(rects2, ax1)

    # -------------------------------------------------------------------------
    # Subplot 2: Cycle Timeline with Reconfiguration Spans
    # -------------------------------------------------------------------------
    records = router.trace_writer.records
    cycles = [r.cycle for r in records]
    cum_routed = []
    cum_dropped = []
    r_acc, d_acc = 0, 0
    for r in records:
        if r.status == "ROUTED":
            r_acc += 1
        else:
            d_acc += 1
        cum_routed.append(r_acc)
        cum_dropped.append(d_acc)

    ax2.step(cycles, cum_routed, where="post", label="Cumulative Routed", color="#1f77b4", linewidth=2.5)
    ax2.step(cycles, cum_dropped, where="post", label="Cumulative Dropped", color="#ff7f0e", linewidth=2.5)

    # Mid-run reconfiguration vertical markers
    colors = ["#e377c2", "#17becf", "#bcbd22", "#8c564b"]
    for idx, (cyc, name, m) in enumerate(phase_transitions):
        ax2.axvline(x=cyc, color="grey", linestyle=":", alpha=0.7)
        ax2.text(
            cyc + 0.1,
            max(cum_routed) * 0.85 - idx * 1.5,
            f"Phase {idx+1}\n(Mode {m})",
            fontsize=8,
            color="#333333",
            bbox=dict(boxstyle="round,pad=0.2", facecolor=colors[idx % len(colors)], alpha=0.3),
        )

    ax2.set_xlabel("Simulation Cycle", fontweight="bold")
    ax2.set_ylabel("Cumulative Spikes", fontweight="bold")
    ax2.set_title("Mid-Run Reconfiguration Timeline", fontweight="bold")
    ax2.legend(loc="upper left")
    ax2.grid(True, linestyle="--", alpha=0.5)

    # -------------------------------------------------------------------------
    # Subplot 3: Drop Reason Breakdown
    # -------------------------------------------------------------------------
    reasons = router.metrics.drop_reasons
    if reasons:
        r_names = list(reasons.keys())
        r_counts = list(reasons.values())
        y_pos = np.arange(len(r_names))
        ax3.barh(y_pos, r_counts, color="#9467bd", edgecolor="black")
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(r_names, fontsize=9)
        ax3.set_xlabel("Occurrences", fontweight="bold")
        ax3.set_title("Drop Reason Diagnostic Breakdown", fontweight="bold")
        for i, v in enumerate(r_counts):
            ax3.text(v + 0.05, i, str(v), va="center", fontweight="bold")
    else:
        ax3.text(0.5, 0.5, "No drops recorded", ha="center", va="center")
        ax3.set_title("Drop Reasons", fontweight="bold")
    ax3.grid(axis="x", linestyle="--", alpha=0.5)

    # -------------------------------------------------------------------------
    # Subplot 4: TDM Shared Physical Pool Schedule Matrix
    # -------------------------------------------------------------------------
    # 4 time slots x 8 physical neurons
    # Matrix represents which logical layer is scheduled on each physical neuron
    matrix = np.full((3, 4), -1)  # 3 layers x 4 slots
    # Demo schedule had: slot 0 -> layer 0, slot 1 -> layer 1, slot 2 -> layer 2, slot 3 -> idle (-1)
    matrix[0, 0] = 0  # Layer 0 on slot 0
    matrix[1, 1] = 1  # Layer 1 on slot 1
    matrix[2, 2] = 2  # Layer 2 on slot 2

    im = ax4.imshow(matrix, cmap="Blues", aspect="auto", vmin=-1, vmax=2)
    ax4.set_xticks(range(4))
    ax4.set_xticklabels([f"Slot {s}" for s in range(4)])
    ax4.set_yticks(range(3))
    ax4.set_yticklabels([f"Layer {l}" for l in range(3)])
    ax4.set_xlabel("TDM Slot Schedule (Time Sharing)", fontweight="bold")
    ax4.set_ylabel("Logical Network Layer", fontweight="bold")
    ax4.set_title("TDM Physical Pool Reuse Schedule", fontweight="bold")

    for i in range(3):
        for j in range(4):
            val = matrix[i, j]
            text = f"P[0..7]\nActive" if val >= 0 else "Idle"
            color = "white" if val >= 0 else "grey"
            ax4.text(j, i, text, ha="center", va="center", color=color, fontweight="bold", fontsize=9)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_path, dpi=200)
    plt.close()


if __name__ == "__main__":
    run_demo()
