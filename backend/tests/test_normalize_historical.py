import pytest

from ingestion.normalize import (
    barkjohn_correct,
    purpleair_channel_qa,
    relative_humidity_from_dewpoint,
)


def test_rh_is_100_when_saturated():
    assert relative_humidity_from_dewpoint(20.0, 20.0) == 100.0


def test_rh_typical_value():
    # 25 °C air with a 10 °C dew point is ~39% RH.
    assert relative_humidity_from_dewpoint(25.0, 10.0) == pytest.approx(38.8, abs=0.5)


def test_rh_missing_input():
    assert relative_humidity_from_dewpoint(None, 10.0) is None
    assert relative_humidity_from_dewpoint(25.0, None) is None


def test_barkjohn_formula():
    # 0.524 * 20 - 0.0862 * 50 + 5.75
    assert barkjohn_correct(20.0, 50.0) == pytest.approx(11.92)


def test_barkjohn_clamps_negative_to_zero():
    assert barkjohn_correct(0.0, 100.0) == 0.0


def test_channels_agree():
    assert purpleair_channel_qa(10.0, 12.0) == (11.0, "ok")


def test_small_absolute_gap_is_ok_even_if_relative_gap_is_large():
    # |A-B| = 4 <= 5 µg/m³, so this passes despite a 133% relative gap.
    assert purpleair_channel_qa(1.0, 5.0) == (3.0, "ok")


def test_channels_disagree():
    mean, flag = purpleair_channel_qa(10.0, 100.0)
    assert mean == 55.0
    assert flag == "invalid"


def test_single_channel_is_suspect():
    assert purpleair_channel_qa(None, 8.0) == (8.0, "suspect")


def test_no_channels_is_invalid():
    assert purpleair_channel_qa(None, None) == (None, "invalid")
