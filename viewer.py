#!/usr/bin/env python3
"""Pure viewer UI for the Reconfigurable Neuron-Synapse Router.

Reads ONLY out/rtl_trace.txt (primary) and optionally out/py_trace.txt.
Contains NO routing logic.
Generates an interactive standalone HTML visualization page and serves it locally.
"""

import argparse
import csv
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
from typing import Dict, List, Any

# Ensure line-buffered output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def parse_trace(filepath: str) -> List[Dict[str, Any]]:
    """Parse trace file (cycle,mode,src,dst,status,layer,reason)."""
    if not os.path.exists(filepath):
        return []
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "cycle": int(row["cycle"]),
                "mode": int(row["mode"]),
                "src": int(row["src"]),
                "dst": row["dst"],
                "status": row["status"].strip(),
                "layer": int(row["layer"]),
                "reason": row["reason"].strip(),
            })
    return records


def find_free_port(start_port: int = 8080) -> int:
    """Find a free TCP port to bind the server."""
    port = start_port
    while port < start_port + 100:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            port += 1
    return start_port


def generate_html(rtl_records: List[Dict[str, Any]], py_records: List[Dict[str, Any]], output_path: str):
    """Generate self-contained interactive HTML viewer."""

    # Compute high-level statistics strictly from the trace records
    total_events = len(rtl_records)
    routed_count = sum(1 for r in rtl_records if r["status"] == "ROUTED")
    dropped_count = sum(1 for r in rtl_records if r["status"] == "DROPPED")
    delivery_rate = (routed_count / total_events * 100.0) if total_events > 0 else 0.0

    # Identify mode change markers
    mode_changes = []
    prev_mode = None
    for r in rtl_records:
        if prev_mode is None or r["mode"] != prev_mode:
            mode_changes.append({
                "cycle": r["cycle"],
                "old_mode": prev_mode,
                "new_mode": r["mode"],
                "src": r["src"],
                "dst": r["dst"],
            })
            prev_mode = r["mode"]

    # Compute neuron activity per layer (0..2 layers x 0..7 neurons) strictly from logged trace
    # activity[layer][neuron] = count of events involving this neuron
    neuron_activity = {lyr: [0] * 8 for lyr in range(3)}
    for r in rtl_records:
        lyr = r["layer"]
        if 0 <= lyr < 3:
            dst_val = r["dst"]
            if dst_val != "-1":
                # Handle hex multicast mask or integer dst
                if dst_val.startswith("0x") or dst_val.startswith("0X"):
                    mask = int(dst_val, 16)
                    for n in range(8):
                        if mask & (1 << n):
                            neuron_activity[lyr][n] += 1
                else:
                    try:
                        n = int(dst_val)
                        if 0 <= n < 8:
                            neuron_activity[lyr][n] += 1
                    except ValueError:
                        pass

    # Check match with Python trace
    match_status = "N/A"
    if py_records:
        if len(py_records) == len(rtl_records):
            all_match = all(
                py_records[i]["cycle"] == rtl_records[i]["cycle"] and
                py_records[i]["mode"] == rtl_records[i]["mode"] and
                py_records[i]["src"] == rtl_records[i]["src"] and
                py_records[i]["dst"] == rtl_records[i]["dst"] and
                py_records[i]["status"] == rtl_records[i]["status"] and
                py_records[i]["layer"] == rtl_records[i]["layer"] and
                py_records[i]["reason"] == rtl_records[i]["reason"]
                for i in range(len(rtl_records))
            )
            match_status = "100% Match (PASS)" if all_match else "Mismatch Detected (FAIL)"
        else:
            match_status = f"Length Mismatch (RTL: {len(rtl_records)}, Py: {len(py_records)})"

    # Embedded data payload (pure viewer: NO routing calculations)
    data_payload = {
        "rtl_records": rtl_records,
        "mode_changes": mode_changes,
        "neuron_activity": neuron_activity,
        "total_events": total_events,
        "routed_count": routed_count,
        "dropped_count": dropped_count,
        "delivery_rate": round(delivery_rate, 1),
        "match_status": match_status,
    }

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Neuron-Synapse Router - Icarus Verilog Simulation Trace Viewer</title>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --success: #22c55e;
    --danger: #ef4444;
    --warning: #f59e0b;
    --purple: #a855f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ background: var(--bg); color: var(--text); padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}

  /* Header */
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
  .title-group {{ display: flex; align-items: center; gap: 12px; }}
  h1 {{ font-size: 22px; font-weight: 700; color: var(--text); }}
  .verilog-badge {{ background: linear-gradient(135deg, #0284c7, #6366f1); color: white; padding: 6px 14px; border-radius: 9999px; font-size: 13px; font-weight: 700; letter-spacing: 0.5px; box-shadow: 0 2px 8px rgba(2, 132, 199, 0.4); }}
  .match-badge {{ padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; }}
  .match-pass {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; }}

  /* Stat Cards */
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px; }}
  .card-label {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }}
  .card-val {{ font-size: 28px; font-weight: 800; }}
  .card-val.green {{ color: #4ade80; }}
  .card-val.red {{ color: #f87171; }}
  .card-val.blue {{ color: var(--accent); }}

  /* Section Title */
  .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }}

  /* Mode Change Markers */
  .mode-markers {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
  .marker-chip {{ background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; }}
  .marker-cycle {{ color: var(--accent); font-weight: 700; }}

  /* Active / Inactive Neurons Grid */
  .layers-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
  .layer-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
  .layer-header {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; color: var(--accent); }}
  .neuron-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  .neuron-cell {{ background: #0f172a; border: 1px solid var(--border); border-radius: 8px; padding: 10px 6px; text-align: center; }}
  .neuron-cell.active {{ background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.5); }}
  .neuron-cell.inactive {{ opacity: 0.5; }}
  .neuron-id {{ font-size: 12px; font-weight: 700; margin-bottom: 4px; }}
  .neuron-cell.active .neuron-id {{ color: #4ade80; }}
  .neuron-cell.inactive .neuron-id {{ color: var(--muted); }}
  .neuron-count {{ font-size: 11px; color: var(--muted); }}

  /* Filters */
  .toolbar {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; justify-content: space-between; }}
  .filter-group {{ display: flex; gap: 8px; }}
  .btn {{ background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 600; }}
  .btn.active {{ background: var(--accent); color: #0f172a; border-color: var(--accent); }}
  .search-input {{ background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; font-size: 13px; width: 220px; }}

  /* Event Timeline Table */
  .table-wrap {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
  th {{ background: #162032; padding: 12px 16px; font-weight: 700; color: var(--muted); text-transform: uppercase; font-size: 11px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 16px; border-bottom: 1px solid rgba(51, 65, 85, 0.6); }}
  tr:hover {{ background: rgba(56, 189, 248, 0.05); }}
  .status-badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
  .status-ROUTED {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); }}
  .status-DROPPED {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
  .mode-tag {{ font-weight: 600; color: var(--accent); }}
  .reason-text {{ font-family: monospace; font-size: 12px; color: #cbd5e1; }}
  .mode-change-row {{ background: rgba(168, 85, 247, 0.15) !important; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="title-group">
      <h1>Neuron-Synapse Router Trace Viewer</h1>
      <span class="verilog-badge">Icarus Verilog simulation</span>
    </div>
    <div>
      <span class="match-badge match-pass">Ref Diff: {data_payload["match_status"]}</span>
    </div>
  </div>

  <!-- Summary Cards -->
  <div class="stats-grid">
    <div class="card">
      <div class="card-label">Total Simulation Events</div>
      <div class="card-val blue" id="stat-total">{total_events}</div>
    </div>
    <div class="card">
      <div class="card-label">Routed Spikes</div>
      <div class="card-val green" id="stat-routed">{routed_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Dropped Spikes</div>
      <div class="card-val red" id="stat-dropped">{dropped_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Delivery Success Rate</div>
      <div class="card-val blue" id="stat-rate">{delivery_rate:.1f}%</div>
    </div>
  </div>

  <!-- Mode Change Markers -->
  <div class="section-title">🔄 Dynamic Mode Reconfiguration Markers</div>
  <div class="mode-markers" id="mode-markers-list"></div>

  <!-- Active and Inactive Neurons per Layer -->
  <div class="section-title">🧠 Layer & Neuron Activity (Active vs Inactive)</div>
  <div class="layers-grid" id="layers-container"></div>

  <!-- Event Timeline Table -->
  <div class="section-title">⏱️ Event Timeline (src → dst, mode, status, reason)</div>
  <div class="toolbar">
    <div class="filter-group">
      <button class="btn active" onclick="setFilter('ALL', this)">All Events</button>
      <button class="btn" onclick="setFilter('ROUTED', this)">Routed</button>
      <button class="btn" onclick="setFilter('DROPPED', this)">Dropped</button>
    </div>
    <input type="text" class="search-input" id="search-box" placeholder="Search src, dst, reason..." oninput="renderTable()">
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Cycle</th>
          <th>Mode</th>
          <th>Src → Dst</th>
          <th>Status</th>
          <th>Layer</th>
          <th>Diagnostic Reason</th>
        </tr>
      </thead>
      <tbody id="trace-tbody"></tbody>
    </table>
  </div>

</div>

<script>
  const DATA = {json.dumps(data_payload)};
  const MODE_NAMES = {{
    0: "Mode 0 (Static Crossbar)",
    1: "Mode 1 (AER Multicast)",
    2: "Mode 2 (TDM Reuse)",
    3: "Mode 3 (Layer Bypass/Exit)"
  }};

  let currentStatusFilter = 'ALL';

  function init() {{
    renderModeMarkers();
    renderLayers();
    renderTable();
  }}

  function renderModeMarkers() {{
    const container = document.getElementById("mode-markers-list");
    container.innerHTML = "";
    DATA.mode_changes.forEach(mc => {{
      const chip = document.createElement("div");
      chip.className = "marker-chip";
      chip.innerHTML = `<span class="marker-cycle">Cycle ${{mc.cycle}}</span>: Switched to <strong>${{MODE_NAMES[mc.new_mode] || "Mode " + mc.new_mode}}</strong>`;
      container.appendChild(chip);
    }});
  }}

  function renderLayers() {{
    const container = document.getElementById("layers-container");
    container.innerHTML = "";
    for (let lyr = 0; lyr < 3; lyr++) {{
      const card = document.createElement("div");
      card.className = "layer-card";
      
      const counts = DATA.neuron_activity[lyr] || [0,0,0,0,0,0,0,0];
      const activeCount = counts.filter(c => c > 0).length;
      
      let cellsHtml = "";
      for (let n = 0; n < 8; n++) {{
        const cnt = counts[n];
        const isActive = cnt > 0;
        cellsHtml += `
          <div class="neuron-cell ${{isActive ? 'active' : 'inactive'}}">
            <div class="neuron-id">N${{n}}</div>
            <div class="neuron-count">${{isActive ? cnt + ' spikes' : 'Inactive'}}</div>
          </div>
        `;
      }}

      card.innerHTML = `
        <div class="layer-header">Hidden Layer ${{lyr}} (${{activeCount}}/8 Active)</div>
        <div class="neuron-grid">${{cellsHtml}}</div>
      `;
      container.appendChild(card);
    }}
  }}

  function setFilter(status, btn) {{
    currentStatusFilter = status;
    document.querySelectorAll(".filter-group .btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    renderTable();
  }}

  function renderTable() {{
    const tbody = document.getElementById("trace-tbody");
    const search = document.getElementById("search-box").value.toLowerCase();
    tbody.innerHTML = "";

    const modeChangeCycles = new Set(DATA.mode_changes.map(mc => mc.cycle));

    DATA.rtl_records.forEach(r => {{
      if (currentStatusFilter !== 'ALL' && r.status !== currentStatusFilter) return;

      const textMatch = `${{r.cycle}} ${{r.src}} ${{r.dst}} ${{r.reason}}`.toLowerCase();
      if (search && !textMatch.includes(search)) return;

      const isModeChange = modeChangeCycles.has(r.cycle);
      const tr = document.createElement("tr");
      if (isModeChange) tr.className = "mode-change-row";

      tr.innerHTML = `
        <td><strong>${{r.cycle}}</strong></td>
        <td><span class="mode-tag">${{MODE_NAMES[r.mode] || "Mode " + r.mode}}</span></td>
        <td>${{r.src}} → <strong>${{r.dst}}</strong></td>
        <td><span class="status-badge status-${{r.status}}">${{r.status}}</span></td>
        <td>Layer ${{r.layer}}</td>
        <td class="reason-text">${{r.reason}}</td>
      `;
      tbody.appendChild(tr);
    }});
  }}

  window.onload = init;
</script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Generated standalone HTML UI: {output_path}")


class QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """Serve files quietly from the directory containing viewer.html."""
    def log_message(self, format, *args):
        pass  # Suppress request spam in console


def serve_ui(html_path: str, port: int = 8080, run_forever: bool = True):
    """Serve the generated HTML UI on local HTTP server."""
    directory = os.path.dirname(os.path.abspath(html_path))
    actual_port = find_free_port(port)

    # Change working directory of handler
    handler = lambda *args, **kwargs: QuietHTTPHandler(*args, directory=directory, **kwargs)
    
    print("=" * 80)
    print("        RECONFIGURABLE ROUTER - ICARUS VERILOG SIMULATION VIEWER")
    print("=" * 80)
    print(f"Label:           [Icarus Verilog simulation]")
    print(f"Primary Source:  out/rtl_trace.txt")
    print(f"HTML File:       {os.path.abspath(html_path)}")
    print(f"Local Server:    http://127.0.0.1:{actual_port}/viewer.html")
    print("=" * 80)

    # Only attempt browser launch if display environment is present and requested
    if "DISPLAY" in os.environ and os.environ.get("DISPLAY"):
        try:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(html_path)}")
        except Exception:
            pass

    try:
        with socketserver.TCPServer(("127.0.0.1", actual_port), handler) as httpd:
            if run_forever:
                print(f"HTTP server running. Open http://127.0.0.1:{actual_port}/viewer.html in your browser.")
                print(f"Or open directly: file://{os.path.abspath(html_path)}")
                print("Press Ctrl+C to terminate.")
                httpd.serve_forever()
            else:
                # One-shot or background check
                pass
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    parser = argparse.ArgumentParser(description="Neuron-Synapse Router Trace Viewer")
    parser.add_argument("--rtl-trace", default="out/rtl_trace.txt", help="Path to RTL trace file")
    parser.add_argument("--py-trace", default="out/py_trace.txt", help="Path to Python trace file")
    parser.add_argument("--output-html", default="out/viewer.html", help="Path to output HTML file")
    parser.add_argument("--port", type=int, default=8080, help="Local HTTP server port")
    parser.add_argument("--no-serve", action="store_true", help="Generate HTML only without serving")
    parser.add_argument("--daemon", action="store_true", help="Start server in background daemon thread")
    args = parser.parse_args()

    rtl_records = parse_trace(args.rtl_trace)
    py_records = parse_trace(args.py_trace)

    if not rtl_records:
        print(f"Warning: No records found in {args.rtl_trace}. Run `make sim` first.")

    generate_html(rtl_records, py_records, args.output_html)

    if not args.no_serve:
        serve_ui(args.output_html, port=args.port, run_forever=not args.daemon)


if __name__ == "__main__":
    main()
