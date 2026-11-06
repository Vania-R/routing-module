# Makefile for Reconfigurable Neuron-Synapse Routing Module

VENV_BIN := .venv/bin
PYTHON   := $(VENV_BIN)/python
PYTEST   := $(VENV_BIN)/pytest

.PHONY: all test demo clean help

all: test

test:
	$(PYTEST) -v

demo:
	$(PYTHON) demo.py

clean:
	rm -rf __pycache__ src/routing_module/__pycache__ tests/__pycache__ .pytest_cache
	rm -f *.png *.csv *.stim

help:
	@echo "Available make targets:"
	@echo "  make test   - Run all pytest test suites with verbose output"
	@echo "  make demo   - Run the 4-mode reconfigurable routing demonstration"
	@echo "  make clean  - Remove temporary build artifacts and test outputs"
