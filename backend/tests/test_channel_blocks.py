"""channel_blocks.resolve_layout — accumulation, defaults, normalization."""

import channel_blocks as cb


def test_defaults_reproduce_historical_layout():
    # start=10 with default sizes == the original cable layout.
    lay = cb.resolve_layout(None, start=10)
    assert (lay["marathon"]["start"], lay["marathon"]["end"]) == (10, 19)
    assert (lay["tv_block"]["start"], lay["tv_block"]["end"]) == (20, 29)
    assert (lay["movie"]["start"], lay["movie"]["end"]) == (30, 49)
    assert (lay["franchise"]["start"], lay["franchise"]["end"]) == (50, 69)
    assert (lay["specialty"]["start"], lay["specialty"]["end"]) == (70, 79)


def test_start_at_one():
    lay = cb.resolve_layout(None, start=1)
    assert lay["marathon"]["start"] == 1
    assert lay["tv_block"]["start"] == 11
    assert lay["specialty"]["end"] == 70


def test_sizes_accumulate():
    lay = cb.resolve_layout({"marathon": 100, "tv_block": 100, "movie": 100,
                             "franchise": 100, "specialty": 100}, start=1)
    assert lay["marathon"]["end"] == 100
    assert lay["tv_block"]["start"] == 101
    assert lay["movie"]["start"] == 201


def test_partial_sizes_fill_from_defaults():
    lay = cb.resolve_layout({"movie": 50}, start=10)
    assert lay["marathon"]["size"] == 10        # untouched default
    assert lay["movie"]["size"] == 50           # override applied
    assert lay["franchise"]["start"] == 80      # shifted by the bigger movie block


def test_invalid_sizes_clamped_to_one():
    lay = cb.resolve_layout({"marathon": 0, "tv_block": -5, "movie": "x"}, start=1)
    assert lay["marathon"]["size"] == 1
    assert lay["tv_block"]["size"] == 1
    assert lay["movie"]["size"] == cb.DEFAULT_SIZES["movie"]  # unparseable -> default
