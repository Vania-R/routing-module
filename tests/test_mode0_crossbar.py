"""Tests for Mode 0: Static Crossbar with neuron and layer enable masks."""

import pytest
from routing_module import RoutingModule, ErrorCode, MODE_STATIC_CROSSBAR


def test_mode0_all_enabled_routing():
    router = RoutingModule()
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.set_active_layers(3)
    for lyr in range(3):
        router.set_active_neurons(lyr, 8)
    router.commit()

    # Route through each layer and neuron
    for layer in range(3):
        for neuron in range(8):
            records = router.route(src=neuron, dst=neuron, layer=layer, cycle=layer * 8 + neuron)
            assert len(records) == 1
            rec = records[0]
            assert rec.status == "ROUTED"
            assert rec.mode == 0
            assert rec.src == neuron
            assert rec.dst == neuron
            assert rec.layer == layer

    assert router.metrics.routed == 24
    assert router.metrics.dropped == 0


def test_mode0_layer_mask_dropping():
    router = RoutingModule()
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    # Only layer 0 and 1 are active; layer 2 is disabled
    router.set_active_layers(2)
    router.commit()

    # Traffic to layer 0 and 1 should route
    rec0 = router.route(src=0, dst=0, layer=0, cycle=0)[0]
    rec1 = router.route(src=1, dst=1, layer=1, cycle=1)[0]
    assert rec0.status == "ROUTED"
    assert rec1.status == "ROUTED"

    # Traffic targeting layer 2 must be dropped
    rec2 = router.route(src=2, dst=2, layer=2, cycle=2)[0]
    assert rec2.status == "DROPPED"
    assert rec2.reason == "LAYER_DISABLED"

    assert router.metrics.routed == 2
    assert router.metrics.dropped == 1


def test_mode0_neuron_mask_dropping():
    router = RoutingModule()
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.set_active_layers(3)
    # Layer 0: only neurons 0..3 active (k=4)
    router.set_active_neurons(layer=0, k=4)
    # Layer 1: explicit mask 0b00110011 (neurons 0, 1, 4, 5 enabled)
    router.set_active_neurons(layer=1, k=0, mask=0b00110011)
    router.commit()

    # Layer 0: neurons 0..3 routed
    for n in range(4):
        rec = router.route(src=n, dst=n, layer=0)[0]
        assert rec.status == "ROUTED"

    # Layer 0: neurons 4..7 dropped
    for n in range(4, 8):
        rec = router.route(src=n, dst=n, layer=0)[0]
        assert rec.status == "DROPPED"
        assert rec.reason == "NEURON_MASKED"

    # Layer 1: test against explicit bitmask
    assert router.route(src=0, dst=0, layer=1)[0].status == "ROUTED"
    assert router.route(src=1, dst=1, layer=1)[0].status == "ROUTED"
    assert router.route(src=2, dst=2, layer=1)[0].status == "DROPPED"
    assert router.route(src=4, dst=4, layer=1)[0].status == "ROUTED"
    assert router.route(src=6, dst=6, layer=1)[0].status == "DROPPED"


def test_mode0_default_crossbar_destination():
    router = RoutingModule()
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.commit()

    # When dst is omitted, feedforward defaults to src % 8
    rec = router.route(src=13, dst=None, layer=0)[0]
    assert rec.status == "ROUTED"
    assert rec.dst == 13 % 8  # 5


def test_mode0_invalid_dst_out_of_bounds():
    router = RoutingModule()
    router.set_routing_mode(MODE_STATIC_CROSSBAR)
    router.commit()

    rec = router.route(src=0, dst=8, layer=0)[0]
    assert rec.status == "DROPPED"
    assert rec.reason == "INVALID_DST_NEURON"
