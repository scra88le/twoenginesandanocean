import io

import numpy as np
import pytest
from PIL import Image

from pipeline.encode import (
    FIRST_VALID,
    MASKED,
    MAX_INT,
    NODATA,
    decode,
    png_to_ints,
    quantise,
    scalar_png,
    scale_offset,
    vector_png,
)

RNG = np.random.default_rng(0)


def test_reserved_codes():
    assert (NODATA, MASKED, FIRST_VALID, MAX_INT) == (0, 1, 2, 65535)


def test_linear_round_trip_within_half_a_step():
    lo, hi = -300.0, 1500.0
    x = RNG.uniform(lo, hi, size=10_000)
    q, clipped = quantise(x, np.zeros_like(x, bool), lo, hi)
    assert clipped == 0
    step = (hi - lo) / (MAX_INT - FIRST_VALID)
    assert np.abs(decode(q, lo, hi) - x).max() <= step / 2 + 1e-12


def test_log_round_trip_within_half_a_step_in_log_space():
    lo, hi = 1e-4, 1e3
    x = 10 ** RNG.uniform(-4, 3, size=10_000)
    q, _ = quantise(x, np.zeros_like(x, bool), lo, hi, log=True)
    step = (np.log10(hi) - np.log10(lo)) / (MAX_INT - FIRST_VALID)
    err = np.abs(np.log10(decode(q, lo, hi, log=True)) - np.log10(x))
    assert err.max() <= step / 2 + 1e-12


def test_range_ends_map_to_first_and_last_valid_codes():
    q, _ = quantise(np.array([0.0, 45.0]), np.zeros(2, bool), 0.0, 45.0)
    assert list(q) == [FIRST_VALID, MAX_INT]


def test_zero_is_exact_for_clamped_carnot_cells():
    q, _ = quantise(np.array([0.0]), np.zeros(1, bool), 0.0, 45.0)
    assert decode(q, 0.0, 45.0)[0] == 0.0


def test_nan_is_nodata_and_mask_wins_over_values():
    x = np.array([np.nan, 5.0, np.nan, 5.0])
    masked = np.array([False, True, True, False])
    q, _ = quantise(x, masked, 0.0, 10.0)
    assert list(q[:3]) == [NODATA, MASKED, MASKED]
    assert q[3] >= FIRST_VALID
    d = decode(q, 0.0, 10.0)
    assert np.isnan(d[:3]).all() and d[3] == pytest.approx(5.0, abs=1e-3)


def test_log_layers_mark_non_positive_values_as_masked():
    q, _ = quantise(np.array([0.0, -1.0, 1.0]), np.zeros(3, bool), 1e-3, 1e3, log=True)
    assert list(q[:2]) == [MASKED, MASKED] and q[2] >= FIRST_VALID


def test_out_of_range_values_are_clipped_and_counted():
    q, clipped = quantise(np.array([-5.0, 5.0, 50.0]), np.zeros(3, bool), 0.0, 10.0)
    assert clipped == 2
    assert list(q[[0, 2]]) == [FIRST_VALID, MAX_INT]


def test_fixed_step_round_trip_and_clipping_at_hi():
    x = np.array([0.0, 0.12, 0.13, 299.9, 400.0])
    q, clipped = quantise(x, np.zeros(5, bool), 0.0, 300.0, step=0.25)
    assert list(q[:3]) == [2, 2, 3]  # 0.12 rounds down, 0.13 rounds up
    assert clipped == 1
    assert decode(q, 0.0, 300.0, step=0.25)[-1] == pytest.approx(300.0)
    assert scale_offset(0.0, 300.0, step=0.25) == (0.25, 0.0)


def test_fixed_step_in_log_space():
    lo, hi = 1e-3, 1e3
    x = 10 ** RNG.uniform(-3, 3, size=1000)
    q, _ = quantise(x, np.zeros(1000, bool), lo, hi, log=True, step=0.002)
    err = np.abs(np.log10(decode(q, lo, hi, log=True, step=0.002)) - np.log10(x))
    assert err.max() <= 0.001 + 1e-12


def test_step_too_small_for_the_range_is_rejected():
    with pytest.raises(ValueError, match="65533"):
        quantise(np.array([1.0]), np.zeros(1, bool), 0.0, 1e6, step=1e-3)


def test_scale_and_offset_reproduce_decode():
    lo, hi = -400.0, 400.0
    scale, offset = scale_offset(lo, hi)
    q = np.array([2, 1000, 65535], dtype=np.uint16)
    np.testing.assert_allclose(offset + scale * (q.astype(float) - FIRST_VALID), decode(q, lo, hi))
    lscale, loffset = scale_offset(1e-4, 1e3, log=True)
    assert loffset == pytest.approx(-4.0)
    np.testing.assert_allclose(
        10 ** (loffset + lscale * (q.astype(float) - FIRST_VALID)), decode(q, 1e-4, 1e3, log=True)
    )


def test_scalar_png_is_rgb_high_low_zero_and_round_trips():
    q = RNG.integers(0, 65536, size=(360, 720), dtype=np.uint16)
    data = scalar_png(q)
    img = Image.open(io.BytesIO(data))
    assert img.mode == "RGB" and img.size == (720, 360)
    px = np.asarray(img)
    np.testing.assert_array_equal(px[..., 0], q >> 8)
    np.testing.assert_array_equal(px[..., 1], q & 0xFF)
    assert (px[..., 2] == 0).all()
    np.testing.assert_array_equal(png_to_ints(data), q)


def test_vector_png_keeps_rgb_where_alpha_is_zero():
    # v values whose low byte is 0 put 0 in the alpha channel; u must survive in R+G.
    u = RNG.integers(2, 65536, size=(360, 720), dtype=np.uint16)
    v = (RNG.integers(1, 256, size=(360, 720)) << 8).astype(np.uint16)  # low byte 0 -> A = 0
    data = vector_png(u, v)
    img = Image.open(io.BytesIO(data))
    assert img.mode == "RGBA"
    got_u, got_v = png_to_ints(data)
    np.testing.assert_array_equal(got_u, u)
    np.testing.assert_array_equal(got_v, v)
    assert (np.asarray(img)[..., 3] == 0).all()


def test_png_wrong_shape_rejected():
    with pytest.raises(ValueError):
        scalar_png(np.zeros((10, 10), dtype=np.uint16))
