# Makefile for Reconfigurable Neuron-Synapse Routing Module

VENV_BIN := .venv/bin
PYTHON   := $(VENV_BIN)/python
PYTEST   := $(VENV_BIN)/pytest
IVERILOG := iverilog
VVP      := vvp

.PHONY: all test demo sim compare compare-random demo-rtl clean help

all: test

test:
	$(PYTEST) -v

demo:
	$(PYTHON) demo.py

sim:
	mkdir -p out
	$(PYTHON) convert_stim.py
	$(IVERILOG) -g2001 -o sim.vvp rtl/router.v tb/tb_router.v
	$(VVP) sim.vvp

compare: sim
	@$(PYTHON) compare_traces.py

compare-random:
	mkdir -p out
	$(PYTHON) generate_random_stim.py
	$(IVERILOG) -g2001 -o sim.vvp rtl/router.v tb/tb_router.v
	$(VVP) sim.vvp
	@$(PYTHON) compare_traces.py

demo-rtl: sim
	$(PYTHON) viewer.py

clean:
	rm -rf __pycache__ src/routing_module/__pycache__ tests/__pycache__ .pytest_cache
	rm -rf out sim.vvp sim.vcd tb/stimulus.hex
	rm -f *.png *.csv *.stim

help:
	@echo "Available make targets:"
	@echo "  make test           - Run all pytest test suites with verbose output"
	@echo "  make demo           - Run the 4-mode reconfigurable routing demonstration"
	@echo "  make sim            - Compile and run Icarus Verilog RTL simulation"
	@echo "  make compare        - Run RTL sim and diff out/rtl_trace.txt vs Python trace"
	@echo "  make compare-random - Run ~300-event random stimulus sim and compare traces"
	@echo "  make demo-rtl       - Run RTL simulation and start the UI trace viewer"
	@echo "  make clean          - Remove temporary build artifacts and test outputs"
