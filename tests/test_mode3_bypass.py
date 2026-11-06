"""Tests for Mode 3: Layer Bypass and Early Exit."""

import pytest
from routing_module import RoutingModule, ErrorCode, MODE_BYPASS


def test_mode3_early_exit():
    router = RoutingModule()
    router.set_routing_mode(MODE_BYPASS)
    router.set_active_layers(3)
    router.commit()

    # Event with early_exit=True exits directly from Layer 0 without traversing hidden layers
    rec = router.route(src=5, dst=2, layer=0, early_exit=True, cycle=0)[0]
    assert rec.status == "ROUTED"
    assert rec.mode == 3
    assert rec.src == 5
    assert rec.dst == 2
    assert rec.reason == "EARLY_EXIT"

    assert router.metrics.routed == 1


def test_mode3_layer_bypass_configuration():
    router = RoutingModule()
    router.set_routing_mode(MODE_BYPASS)
    router.set_active_layers(3)
    # Enable bypass on Layer 1
    router.set_layer_bypass(layer=1, enable=True)
    router.commit()

    # Event arriving at Layer 1 should bypass Layer 1 and route to Layer 2
    rec = router.route(src=1, dst=3, layer=1, cycle=1)[0]
    assert rec.status == "ROUTED"
    assert rec.reason == "BYPASS_LAYER_1"
    assert rec.layer == 2  # forwarded to Layer 2 directly

    # Event arriving at Layer 0 (not bypassed) routes normally
    rec0 = router.route(src=0, dst=4, layer=0, cycle=2)[0]
    assert rec0.status == "ROUTED"
    assert rec0.reason == "STANDARD_ROUTED"


def test_mode3_disabled_layer_or_neuron():
    router = RoutingModule()
    router.set_routing_mode(MODE_BYPASS)
    router.set_active_layers(1)  # Only Layer 0 active
    router.set_active_neurons(layer=0, k=2)  # Only neurons 0, 1 active
    router.commit()

    # Event without early exit to disabled layer 2 -> DROPPED
    rec_lyr = router.route(src=0, dst=0, layer=2, early_exit=False)[0]
    assert rec_lyr.status == "DROPPED"
    assert rec_lyr.reason == "LAYER_DISABLED"

    # Event to masked neuron 5 in layer 0 -> DROPPED
    rec_nrn = router.route(src=0, dst=5, layer=0, early_exit=False)[0]
    assert rec_nrn.status == "DROPPED"
    assert rec_nrn.reason == "NEURON_MASKED"
