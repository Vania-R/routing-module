#!/usr/bin/env python3
"""Compares RTL execution trace out/rtl_trace.txt against Python trace out/py_trace.txt."""

import os
import sys

def main():
    py_trace_path = "out/py_trace.txt"
    rtl_trace_path = "out/rtl_trace.txt"
    res_path = "out/compare_result.txt"
    os.makedirs("out", exist_ok=True)

    if not os.path.exists(py_trace_path):
        msg = f"FAIL: Reference Python trace {py_trace_path} does not exist."
        print(msg)
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(msg + "\n")
        sys.exit(1)

    if not os.path.exists(rtl_trace_path):
        msg = f"FAIL: RTL trace {rtl_trace_path} does not exist."
        print(msg)
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(msg + "\n")
        sys.exit(1)

    with open(py_trace_path, "r", encoding="utf-8") as f_py:
        py_lines = [line.rstrip("\r\n") for line in f_py]

    with open(rtl_trace_path, "r", encoding="utf-8") as f_rtl:
        rtl_lines = [line.rstrip("\r\n") for line in f_rtl]

    max_len = max(len(py_lines), len(rtl_lines))
    for i in range(max_len):
        p = py_lines[i] if i < len(py_lines) else "<EOF>"
        r = rtl_lines[i] if i < len(rtl_lines) else "<EOF>"
        if p != r:
            msg = f"FAIL: Mismatch at line {i + 1}:\n  Python: {p}\n  RTL:    {r}"
            print(msg)
            with open(res_path, "w", encoding="utf-8") as f:
                f.write(msg + "\n")
            sys.exit(1)

    with open(res_path, "w", encoding="utf-8") as f:
        f.write("PASS\n")
    print("PASS")
    sys.exit(0)

if __name__ == "__main__":
    main()
