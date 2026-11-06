"""Tests for Mode 1: AER (Address Event Representation) routing."""

import pytest
from routing_module import RoutingModule, ErrorCode, MODE_AER


def test_mode1_aer_multicast():
    router = RoutingModule()
    router.set_routing_mode(MODE_AER)
    router.set_active_layers(3)
    for lyr in range(3):
        router.set_active_neurons(lyr, 8)

    # Load AER routing table entries
    # Address 100 -> multicast to neurons 0, 1, 4 (mask 0b00010011 = 0x13)
    assert router.load_route_table(src=100, dst_mask=0x13) == ErrorCode.SUCCESS
    # Address 200 -> broadcast to all 8 neurons (mask 0xFF)
    assert router.load_route_table(src=200, dst_mask=0xFF) == ErrorCode.SUCCESS
    router.commit()

    # Route event for mapped address 100
    records = router.route(src=100, layer=0, cycle=1)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == "ROUTED"
    assert rec.mode == 1
    assert rec.src == 100
    assert rec.dst == 0x13
    assert "AER_MULTICAST" in rec.reason

    # Route broadcast address 200
    rec_bcast = router.route(src=200, layer=1, cycle=2)[0]
    assert rec_bcast.status == "ROUTED"
    assert rec_bcast.dst == 0xFF


def test_mode1_invalid_address_dropped():
    router = RoutingModule()
    router.set_routing_mode(MODE_AER)
    router.load_route_table(src=10, dst_mask=0x01)
    # Entry with 0 destination mask is treated as invalid
    router.load_route_table(src=20, dst_mask=0x00)
    router.commit()

    # Mapped address 10 routes
    assert router.route(src=10, layer=0)[0].status == "ROUTED"

    # Unmapped address 999 must be dropped
    rec_unmapped = router.route(src=999, layer=0)[0]
    assert rec_unmapped.status == "DROPPED"
    assert rec_unmapped.reason == "INVALID_ADDR"

    # Address mapped to 0 must be dropped
    rec_zero = router.route(src=20, layer=0)[0]
    assert rec_zero.status == "DROPPED"
    assert rec_zero.reason == "INVALID_ADDR"

    assert router.metrics.routed == 1
    assert router.metrics.dropped == 2


def test_mode1_aer_with_neuron_masking():
    router = RoutingModule()
    router.set_routing_mode(MODE_AER)
    # Layer 0: only neurons 0..3 active (mask 0x0F)
    router.set_active_neurons(layer=0, k=4)
    # Address 50 targets neurons 0, 1, 4 (mask 0b00010011 = 0x13)
    router.load_route_table(src=50, dst_mask=0x13)
    # Address 60 targets only neuron 7 (mask 0x80)
    router.load_route_table(src=60, dst_mask=0x80)
    router.commit()

    # Address 50: neuron 4 is masked, but neurons 0 and 1 remain active -> dst = 0x03
    rec50 = router.route(src=50, layer=0)[0]
    assert rec50.status == "ROUTED"
    assert rec50.dst == 0x03  # 0x13 & 0x0F

    # Address 60: neuron 7 is masked out, leaving 0 active destinations -> DROPPED
    rec60 = router.route(src=60, layer=0)[0]
    assert rec60.status == "DROPPED"
    assert rec60.reason == "ALL_DST_MASKED"


def test_mode1_aer_disabled_layer():
    router = RoutingModule()
    router.set_routing_mode(MODE_AER)
    router.set_active_layers(1)  # Only Layer 0 active
    router.load_route_table(src=15, dst_mask=0x01)
    router.commit()

    # Targeting disabled Layer 1 must be dropped
    rec = router.route(src=15, layer=1)[0]
    assert rec.status == "DROPPED"
    assert rec.reason == "LAYER_DISABLED"
