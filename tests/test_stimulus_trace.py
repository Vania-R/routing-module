"""Tests for Stimulus Generator, Trace Writer, and Metrics."""

import io
import os
import pytest
from routing_module import (
    RoutingModule,
    StimulusGenerator,
    TraceWriter,
    TraceRecord,
    RoutingMetrics,
    MODE_STATIC_CROSSBAR,
)


def test_stimulus_generator_write_and_parse(tmp_path):
    gen = StimulusGenerator()
    gen.add_command("set_routing_mode", 0)
    gen.add_command("set_active_layers", 2)
    gen.add_command("set_active_neurons", 0, 8)
    gen.add_command("commit")
    gen.add_event(cycle=0, src=1, dst=2, layer=0, early_exit=False, slot=None)
    gen.add_event(cycle=1, src=3, dst=4, layer=1, early_exit=True, slot=2)

    stim_file = tmp_path / "test.stim"
    gen.write_to_file(str(stim_file))

    # Read back and verify
    loaded = StimulusGenerator.load_from_file(str(stim_file))
    assert len(loaded.items) == 6

    # Execute against a router
    router = RoutingModule()
    loaded.execute(router)
    assert router.active_mode == 0
    assert router.active_layers == 2
    assert router.metrics.routed > 0


def test_trace_writer_csv_and_table(tmp_path):
    writer = TraceWriter()
    writer.log(cycle=0, mode=0, src=1, dst=2, status="ROUTED", layer=0, reason="OK")
    writer.log(cycle=1, mode=0, src=3, dst=4, status="DROPPED", layer=1, reason="NEURON_MASKED")

    assert len(writer.records) == 2
    rec0 = writer.records[0]
    # Check exact tuple format: (cycle, mode, src, dst, status, layer)
    assert rec0.as_tuple() == (0, 0, 1, 2, "ROUTED", 0)

    # Test CSV generation
    csv_file = tmp_path / "trace.csv"
    writer.write_csv(str(csv_file))
    assert os.path.exists(csv_file)
    with open(csv_file, "r") as f:
        content = f.read()
    assert "cycle,mode,src,dst,status,layer,reason" in content
    assert "ROUTED" in content
    assert "DROPPED" in content

    # Test Table generation
    table = writer.format_table()
    assert "Cycle" in table
    assert "ROUTED" in table


def test_metrics_tracking():
    metrics = RoutingMetrics()
    metrics.record_routed(cycle=0, mode=0, layer=0)
    metrics.record_routed(cycle=1, mode=1, layer=0)
    metrics.record_dropped(cycle=2, mode=0, layer=1, reason="NEURON_MASKED")
    metrics.record_dropped(cycle=3, mode=1, layer=2, reason="INVALID_ADDR")

    assert metrics.routed == 2
    assert metrics.dropped == 2
    assert metrics.cycles == 4
    assert metrics.total_events == 4
    assert metrics.delivery_rate == 0.5
    assert metrics.drop_rate == 0.5
    assert metrics.drop_reasons["NEURON_MASKED"] == 1
    assert metrics.drop_reasons["INVALID_ADDR"] == 1

    summary = metrics.get_summary()
    assert summary["routed"] == 2
    assert summary["dropped"] == 2
    assert summary["cycles"] == 4

    tbl = metrics.format_table()
    assert "ROUTING MODULE METRICS" in tbl
    assert "50.0%" in tbl
