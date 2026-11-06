"""Tests for Mode 2: TDM Neuron Reuse with shared physical pool and slot schedule."""

import pytest
from routing_module import RoutingModule, ErrorCode, MODE_TDM, SHARED_PHYSICAL_POOL_SIZE


def test_mode2_tdm_slot_matching_and_reuse():
    router = RoutingModule()
    router.set_routing_mode(MODE_TDM)
    router.set_active_layers(3)
    for lyr in range(3):
        router.set_active_neurons(lyr, 8)

    # Schedule:
    # Slot 0 -> Layer 0
    # Slot 1 -> Layer 1
    # Slot 2 -> Layer 2
    assert router.set_tdm_schedule(0, 0) == ErrorCode.SUCCESS
    assert router.set_tdm_schedule(1, 1) == ErrorCode.SUCCESS
    assert router.set_tdm_schedule(2, 2) == ErrorCode.SUCCESS
    router.commit()

    # Slot 0: Layer 0 requested -> ROUTED
    rec0 = router.route(src=0, dst=3, layer=0, slot=0)[0]
    assert rec0.status == "ROUTED"
    assert rec0.dst == 3  # physical neuron 3
    assert "TDM_PHYS_POOL_P3" in rec0.reason

    # Slot 1: Layer 1 requested -> ROUTED
    rec1 = router.route(src=1, dst=5, layer=1, slot=1)[0]
    assert rec1.status == "ROUTED"
    assert rec1.dst == 5  # physical neuron 5
    assert "TDM_PHYS_POOL_P5" in rec1.reason

    # Slot 2: Layer 2 requested -> ROUTED
    rec2 = router.route(src=2, dst=7, layer=2, slot=2)[0]
    assert rec2.status == "ROUTED"
    assert rec2.dst == 7  # physical neuron 7


def test_mode2_tdm_slot_mismatch_dropped():
    router = RoutingModule()
    router.set_routing_mode(MODE_TDM)
    router.set_tdm_schedule(0, 0)  # Slot 0 reserved for Layer 0
    router.set_tdm_schedule(1, 1)  # Slot 1 reserved for Layer 1
    router.commit()

    # Sending an event for Layer 1 during Slot 0 must be dropped (resource conflict / slot mismatch)
    rec = router.route(src=0, dst=2, layer=1, slot=0)[0]
    assert rec.status == "DROPPED"
    assert "SLOT_MISMATCH" in rec.reason

    # Sending an event for Layer 0 during Slot 1 must be dropped
    rec2 = router.route(src=0, dst=2, layer=0, slot=1)[0]
    assert rec2.status == "DROPPED"
    assert "SLOT_MISMATCH" in rec2.reason


def test_mode2_cycle_based_slot_rotation():
    router = RoutingModule()
    router.set_routing_mode(MODE_TDM)
    router.set_tdm_schedule(0, 0)  # Slot 0 -> Layer 0
    router.set_tdm_schedule(1, 1)  # Slot 1 -> Layer 1
    router.commit()

    # When slot is None, slot = cycle % len(schedule)
    # Cycle 0 (slot 0): Layer 0 -> ROUTED
    assert router.route(src=0, dst=0, layer=0, cycle=0)[0].status == "ROUTED"
    # Cycle 1 (slot 1): Layer 1 -> ROUTED
    assert router.route(src=1, dst=1, layer=1, cycle=1)[0].status == "ROUTED"
    # Cycle 2 (slot 0): Layer 0 -> ROUTED
    assert router.route(src=2, dst=2, layer=0, cycle=2)[0].status == "ROUTED"
    # Cycle 3 (slot 1): Layer 0 -> DROPPED (mismatch)
    assert router.route(src=3, dst=3, layer=0, cycle=3)[0].status == "DROPPED"


def test_mode2_logical_to_physical_mapping():
    router = RoutingModule()
    router.set_routing_mode(MODE_TDM)
    router.set_tdm_schedule(0, 0)
    router.commit()

    # Neurons in physical pool: 0..7
    for n in range(8):
        rec = router.route(src=n, dst=n, layer=0, slot=0)[0]
        assert rec.status == "ROUTED"
        assert rec.dst == n % SHARED_PHYSICAL_POOL_SIZE
