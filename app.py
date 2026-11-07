"""Streamlit trace viewer for the Reconfigurable Neuron-Synapse Router.

Pure viewer with NO routing logic. Reads ONLY:
- out/rtl_trace.txt
- out/config_log.txt
- out/compare_result.txt
"""

import csv
import os
from typing import Any, Dict, List, Tuple
import pandas as pd
import streamlit as st

# Configure page: plain and minimal
st.set_page_config(
    page_title="Router Trace Viewer",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def load_compare_result(path: str = "out/compare_result.txt") -> str:
    """Read compare result from file."""
    if not os.path.exists(path):
        return "UNKNOWN (out/compare_result.txt not found)"
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_config_log(path: str = "out/config_log.txt") -> List[Dict[str, Any]]:
    """Parse out/config_log.txt into staged commits."""
    if not os.path.exists(path):
        return []

    commits: List[Dict[str, Any]] = []
    staged_commands: List[str] = []
    mode = 0
    layers = 3
    neurons = [8, 8, 8]

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cmd = row.get("command", "").strip()
            args = row.get("args", "").strip()
            cycle_str = row.get("cycle", "0").strip()
            try:
                cyc = int(cycle_str)
            except ValueError:
                cyc = 0

            if cmd == "set_routing_mode":
                try:
                    mode = int(args)
                except ValueError:
                    pass
                staged_commands.append(f"set_routing_mode({args})")
            elif cmd == "set_active_layers":
                try:
                    layers = int(args)
                except ValueError:
                    pass
                staged_commands.append(f"set_active_layers({args})")
            elif cmd == "set_active_neurons":
                parts = args.split()
                if len(parts) >= 2:
                    try:
                        lyr = int(parts[0])
                        val = int(parts[1])
                        if 0 <= lyr < 3:
                            neurons[lyr] = val
                    except ValueError:
                        pass
                staged_commands.append(f"set_active_neurons({args.replace(' ', ', ')})")
            elif cmd == "load_route_table":
                staged_commands.append(f"load_route_table({args.replace(' ', ', ')})")
            elif cmd == "set_tdm_schedule":
                staged_commands.append(f"set_tdm_schedule({args.replace(' ', ', ')})")
            elif cmd == "set_layer_bypass":
                staged_commands.append(f"set_layer_bypass({args.replace(' ', ', ')})")
            elif cmd == "commit":
                commits.append({
                    "cycle": cyc,
                    "commands applied": ", ".join(staged_commands) if staged_commands else "commit()",
                    "resulting mode": mode,
                    "active layers": layers,
                    "active neurons": f"L0:{neurons[0]}, L1:{neurons[1]}, L2:{neurons[2]}",
                    "routed": 0,
                    "dropped": 0,
                })
                staged_commands = []

    return commits


def load_rtl_trace(path: str = "out/rtl_trace.txt") -> List[Dict[str, Any]]:
    """Parse out/rtl_trace.txt."""
    if not os.path.exists(path):
        return []
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cyc = int(row.get("cycle", 0))
            except ValueError:
                cyc = 0
            try:
                mode_val = int(row.get("mode", 0))
            except ValueError:
                mode_val = 0
            try:
                src_val = int(row.get("src", 0))
            except ValueError:
                src_val = 0
            try:
                layer_val = int(row.get("layer", 0))
            except ValueError:
                layer_val = 0

            records.append({
                "cycle (event index)": cyc,
                "mode": mode_val,
                "src": src_val,
                "dst": row.get("dst", "").strip(),
                "status": row.get("status", "").strip(),
                "layer": layer_val,
                "reason": row.get("reason", "").strip(),
            })
    return records


def correlate_events_with_commits(
    commits: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
) -> None:
    """Attribute routed and dropped counts to commits without routing logic."""
    if not commits or not events:
        return

    c_idx = 0
    for ev in events:
        while c_idx < len(commits) - 1:
            next_c = commits[c_idx + 1]
            # Advance if next commit switches mode and event matches next mode
            if next_c["resulting mode"] != commits[c_idx]["resulting mode"] and ev["mode"] == next_c["resulting mode"]:
                c_idx += 1
                continue
            # Advance if mode is identical but a reconfigured feature matches (e.g. neuron masked)
            if next_c["resulting mode"] == commits[c_idx]["resulting mode"]:
                if "NEURON_MASKED" in ev["reason"] and "set_active_neurons" in next_c["commands applied"]:
                    c_idx += 1
                    continue
            break

        if ev["status"] == "ROUTED":
            commits[c_idx]["routed"] += 1
        elif ev["status"] == "DROPPED":
            commits[c_idx]["dropped"] += 1


def main() -> None:
    # 1. Top Strip
    col1, col_arr1, col2, col_arr2, col3 = st.columns([4, 1, 4, 1, 4])
    with col1:
        st.markdown("**Policy engine**  \ncommands from stimulus file (policy engine not connected)")
    with col_arr1:
        st.markdown("### ->")
    with col2:
        st.markdown("**Router (Icarus Verilog simulation)**  \nactive simulation core")
    with col_arr2:
        st.markdown("### ->")
    with col3:
        st.markdown("**Dashboard**  \nnot connected")

    st.divider()

    # Load data
    compare_res = load_compare_result("out/compare_result.txt")
    commits = load_config_log("out/config_log.txt")
    events = load_rtl_trace("out/rtl_trace.txt")
    correlate_events_with_commits(commits, events)

    # 2. Compare Result
    st.subheader("Compare result")
    if compare_res.startswith("PASS"):
        st.success(compare_res)
    else:
        st.error(compare_res)

    # 3. Reconfigurations
    st.subheader("Reconfigurations")
    if commits:
        df_reconfigs = pd.DataFrame(commits)
        st.dataframe(df_reconfigs, use_container_width=True, hide_index=True)
    else:
        st.info("No reconfiguration records found in out/config_log.txt")

    # 4. Per-mode counts and drop reasons
    st.subheader("Per-mode counts and drop reasons")
    col_mode, col_drop = st.columns(2)

    with col_mode:
        st.markdown("**Per-mode counts**")
        mode_names = {
            0: "0 (Static Crossbar)",
            1: "1 (AER Multicast)",
            2: "2 (TDM Reuse)",
            3: "3 (Bypass / Early Exit)",
        }
        mode_stats: Dict[int, Dict[str, int]] = {}
        for ev in events:
            m = ev["mode"]
            if m not in mode_stats:
                mode_stats[m] = {"routed": 0, "dropped": 0, "total": 0}
            mode_stats[m]["total"] += 1
            if ev["status"] == "ROUTED":
                mode_stats[m]["routed"] += 1
            elif ev["status"] == "DROPPED":
                mode_stats[m]["dropped"] += 1

        mode_rows = []
        for m in sorted(mode_stats.keys()):
            mode_rows.append({
                "mode": mode_names.get(m, str(m)),
                "routed": mode_stats[m]["routed"],
                "dropped": mode_stats[m]["dropped"],
                "total": mode_stats[m]["total"],
            })
        if mode_rows:
            st.dataframe(pd.DataFrame(mode_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No events logged.")

    with col_drop:
        st.markdown("**Drop reasons**")
        drop_reasons: Dict[str, int] = {}
        for ev in events:
            if ev["status"] == "DROPPED":
                r = ev["reason"]
                drop_reasons[r] = drop_reasons.get(r, 0) + 1

        drop_rows = [{"reason": r, "count": cnt} for r, cnt in sorted(drop_reasons.items(), key=lambda x: -x[1])]
        if drop_rows:
            st.dataframe(pd.DataFrame(drop_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No drops recorded.")

    # 5. Event table (collapsed by default)
    with st.expander("Event table", expanded=False):
        if events:
            df_events = pd.DataFrame(events)
            st.dataframe(df_events, use_container_width=True, hide_index=True)
        else:
            st.info("No events found in out/rtl_trace.txt")


if __name__ == "__main__":
    main()
