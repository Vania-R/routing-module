"""Tests for configuration staging, validation, and commit() behavior."""

import pytest
from routing_module import RoutingModule, ErrorCode, MODE_STATIC_CROSSBAR, MODE_AER, MODE_TDM, MODE_BYPASS


def test_initial_default_state():
    router = RoutingModule()
    assert router.active_mode == MODE_STATIC_CROSSBAR
    assert router.active_layers == 3
    assert router.active_layer_mask == 0b111
    for layer in range(3):
        assert router.get_active_neuron_mask(layer) == 0xFF
    assert not router.has_uncommitted_changes


def test_staged_mode_not_applied_until_commit():
    router = RoutingModule()
    err = router.set_routing_mode(MODE_AER)
    assert err == ErrorCode.SUCCESS
    assert router.has_uncommitted_changes is True
    # Active mode must remain unchanged prior to commit
    assert router.active_mode == MODE_STATIC_CROSSBAR
    assert router.staged_mode == MODE_AER

    # Commit applies the staged mode
    err = router.commit()
    assert err == ErrorCode.SUCCESS
    assert router.active_mode == MODE_AER
    assert router.has_uncommitted_changes is False


def test_staged_layers_not_applied_until_commit():
    router = RoutingModule()
    err = router.set_active_layers(1)
    assert err == ErrorCode.SUCCESS
    assert router.active_layers == 3
    assert router.active_layer_mask == 0b111

    router.commit()
    assert router.active_layers == 1
    assert router.active_layer_mask == 0b001


def test_staged_neurons_not_applied_until_commit():
    router = RoutingModule()
    err = router.set_active_neurons(layer=0, k=4)
    assert err == ErrorCode.SUCCESS
    assert router.get_active_neuron_mask(0) == 0xFF

    router.commit()
    assert router.get_active_neuron_mask(0) == 0x0F


def test_staged_route_table_not_applied_until_commit():
    router = RoutingModule()
    err = router.load_route_table(src=42, dst_mask=0x15)
    assert err == ErrorCode.SUCCESS
    assert 42 not in router.active_route_table

    router.commit()
    assert router.active_route_table[42] == 0x15


def test_staged_tdm_schedule_not_applied_until_commit():
    router = RoutingModule()
    err = router.set_tdm_schedule(slot=0, layer=2)
    assert err == ErrorCode.SUCCESS
    assert 0 not in router.active_tdm_schedule

    router.commit()
    assert router.active_tdm_schedule[0] == 2


def test_validation_invalid_mode():
    router = RoutingModule()
    assert router.set_routing_mode(4) == ErrorCode.ERR_INVALID_MODE
    assert router.set_routing_mode(-1) == ErrorCode.ERR_INVALID_MODE
    assert router.set_routing_mode("0") == ErrorCode.ERR_INVALID_MODE
    assert router.set_routing_mode(True) == ErrorCode.ERR_INVALID_MODE
    assert router.set_routing_mode(None) == ErrorCode.ERR_INVALID_MODE


def test_validation_invalid_active_layers():
    router = RoutingModule()
    assert router.set_active_layers(0) == ErrorCode.ERR_INVALID_LAYERS
    assert router.set_active_layers(4) == ErrorCode.ERR_INVALID_LAYERS
    assert router.set_active_layers(-1) == ErrorCode.ERR_INVALID_LAYERS
    assert router.set_active_layers("2") == ErrorCode.ERR_INVALID_LAYERS
    assert router.set_active_layers(True) == ErrorCode.ERR_INVALID_LAYERS


def test_validation_invalid_active_neurons():
    router = RoutingModule()
    # Invalid layer index
    assert router.set_active_neurons(layer=3, k=8) == ErrorCode.ERR_INVALID_LAYER
    assert router.set_active_neurons(layer=-1, k=8) == ErrorCode.ERR_INVALID_LAYER
    assert router.set_active_neurons(layer="0", k=8) == ErrorCode.ERR_INVALID_LAYER

    # Invalid neuron count / mask
    assert router.set_active_neurons(layer=0, k=-1) == ErrorCode.ERR_INVALID_NEURONS
    assert router.set_active_neurons(layer=0, k=256) == ErrorCode.ERR_INVALID_NEURONS
    assert router.set_active_neurons(layer=0, k="4") == ErrorCode.ERR_INVALID_NEURONS


def test_validation_invalid_route_table():
    router = RoutingModule()
    assert router.load_route_table(src=-1, dst_mask=0x01) == ErrorCode.ERR_INVALID_SRC
    assert router.load_route_table(src=0x10000, dst_mask=0x01) == ErrorCode.ERR_INVALID_SRC
    assert router.load_route_table(src="10", dst_mask=0x01) == ErrorCode.ERR_INVALID_SRC
    assert router.load_route_table(src=10, dst_mask=-1) == ErrorCode.ERR_INVALID_DST_MASK
    assert router.load_route_table(src=10, dst_mask=0x1000000) == ErrorCode.ERR_INVALID_DST_MASK


def test_validation_invalid_tdm_schedule():
    router = RoutingModule()
    assert router.set_tdm_schedule(slot=-1, layer=0) == ErrorCode.ERR_INVALID_SLOT
    assert router.set_tdm_schedule(slot=16, layer=0) == ErrorCode.ERR_INVALID_SLOT
    assert router.set_tdm_schedule(slot="0", layer=0) == ErrorCode.ERR_INVALID_SLOT
    assert router.set_tdm_schedule(slot=0, layer=3) == ErrorCode.ERR_INVALID_LAYER
    assert router.set_tdm_schedule(slot=0, layer=-2) == ErrorCode.ERR_INVALID_LAYER
