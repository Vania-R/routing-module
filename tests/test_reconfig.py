"""Tests for mid-run reconfiguration across all 4 modes."""

import pytest
from routing_module import (
    RoutingModule,
    StimulusGenerator,
    MODE_STATIC_CROSSBAR,
    MODE_AER,
    MODE_TDM,
    MODE_BYPASS,
)


def test_midrun_reconfiguration_staging_between_inputs():
    """Verify that configuration staged between input spikes does not take effect until commit()."""
    router = RoutingModule()

    # Step 1: Start in Mode 0 (Static Crossbar)
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.commit()

    # Input 1: Routes using Mode 0
    rec1 = router.route(src=1, dst=1, layer=0, cycle=0)[0]
    assert rec1.mode == 0
    assert rec1.status == "ROUTED"

    # Step 2: Stage Mode 1 (AER) and configure routing table, but DO NOT commit yet
    router.set_routing_mode(MODE_AER)
    router.load_route_table(src=50, dst_mask=0x07)

    # Input 2: Arrives BEFORE commit() -> MUST still use Mode 0 (Static Crossbar)!
    rec2 = router.route(src=50, dst=0, layer=0, cycle=1)[0]
    assert rec2.mode == 0
    assert rec2.status == "ROUTED"

    # Step 3: Now commit() between inputs
    router.commit()

    # Input 3: Arrives AFTER commit() -> MUST use Mode 1 (AER)!
    rec3 = router.route(src=50, layer=0, cycle=2)[0]
    assert rec3.mode == 1
    assert rec3.status == "ROUTED"
    assert rec3.dst == 0x07


def test_midrun_reconfiguration_all_4_modes_sequence():
    """Verify executing a multi-phase workload spanning all 4 modes mid-run."""
    gen = StimulusGenerator.generate_midrun_reconfiguration()
    router = RoutingModule()
    gen.execute(router)

    # Check metrics
    metrics = router.metrics
    assert metrics.routed > 0
    assert metrics.dropped > 0
    assert metrics.cycles > 0

    # Verify that all 4 modes were engaged during execution
    modes_seen = set(r.mode for r in router.trace_writer.records)
    assert modes_seen == {0, 1, 2, 3}

    # Verify each mode had both routed and dropped events as expected
    assert metrics.mode_routed[0] >= 1
    assert metrics.mode_dropped[0] >= 1
    assert metrics.mode_routed[1] >= 1
    assert metrics.mode_dropped[1] >= 1
    assert metrics.mode_routed[2] >= 1
    assert metrics.mode_dropped[2] >= 1
    assert metrics.mode_routed[3] >= 1
