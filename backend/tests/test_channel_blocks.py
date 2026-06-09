"""channel_blocks — assign_numbers sequential packing and resolve_order."""

import channel_blocks as cb


# ── assign_numbers ─────────────────────────────────────────────────────────────

def test_assign_numbers_sequential_tight_packing():
    """15 marathons + 8 movies → 1–15 then 16–23 (spec acceptance criterion)."""
    order = ["marathon", "movie", "franchise"]
    counts = {"marathon": 15, "movie": 8, "franchise": 3}
    result = cb.assign_numbers(order, counts, start=1)
    assert result["marathon"] == list(range(1, 16))
    assert result["movie"] == list(range(16, 24))
    assert result["franchise"] == list(range(24, 27))


def test_empty_categories_consume_no_numbers():
    order = ["marathon", "tv_block", "movie"]
    counts = {"marathon": 3, "movie": 2}  # tv_block absent / 0
    result = cb.assign_numbers(order, counts, start=1)
    assert result["marathon"] == [1, 2, 3]
    # tv_block has 0 channels → skipped, movie follows immediately
    assert result["movie"] == [4, 5]
    assert "tv_block" not in result


def test_assign_numbers_start_offset():
    order = ["marathon", "movie"]
    counts = {"marathon": 2, "movie": 3}
    result = cb.assign_numbers(order, counts, start=10)
    assert result["marathon"] == [10, 11]
    assert result["movie"] == [12, 13, 14]


def test_assign_numbers_single_category():
    result = cb.assign_numbers(["specialty"], {"specialty": 5}, start=1)
    assert result["specialty"] == [1, 2, 3, 4, 5]


def test_assign_numbers_all_empty_returns_empty():
    result = cb.assign_numbers(["marathon", "movie"], {}, start=1)
    assert result == {}


def test_assign_numbers_returns_list_of_ints():
    result = cb.assign_numbers(["marathon"], {"marathon": 3}, start=7)
    assert result["marathon"] == [7, 8, 9]
    assert all(isinstance(n, int) for n in result["marathon"])


# ── resolve_order ──────────────────────────────────────────────────────────────

def test_resolve_order_none_returns_canonical():
    assert cb.resolve_order(None) == cb.CANONICAL_ORDER


def test_resolve_order_empty_returns_canonical():
    assert cb.resolve_order([]) == cb.CANONICAL_ORDER


def test_resolve_order_filters_unknown_keys():
    result = cb.resolve_order(["marathon", "nonexistent_key", "movie"])
    assert "nonexistent_key" not in result
    assert "marathon" in result
    assert "movie" in result


def test_resolve_order_appends_missing_canonical_keys():
    # Only marathon and movie supplied; rest of CANONICAL_ORDER appended at end.
    result = cb.resolve_order(["marathon", "movie"])
    assert result[0] == "marathon"
    assert result[1] == "movie"
    # Every canonical key must appear exactly once.
    assert set(result) == set(cb.CANONICAL_ORDER)
    assert len(result) == len(cb.CANONICAL_ORDER)


def test_resolve_order_preserves_configured_prefix():
    # Put movie first, marathon second — configured order respected at the front.
    result = cb.resolve_order(["movie", "marathon"])
    assert result[0] == "movie"
    assert result[1] == "marathon"


def test_resolve_order_full_canonical_unchanged():
    # Supplying the full canonical order returns it verbatim.
    assert cb.resolve_order(cb.CANONICAL_ORDER) == cb.CANONICAL_ORDER


# ── category order affects produced numbers ────────────────────────────────────

def test_category_order_changes_numbers():
    """Reordering categories changes which numbers each category gets."""
    counts = {"marathon": 5, "movie": 3}

    result_a = cb.assign_numbers(cb.resolve_order(["marathon", "movie"]), counts, start=1)
    result_b = cb.assign_numbers(cb.resolve_order(["movie", "marathon"]), counts, start=1)

    # In order A: marathon 1–5, movie 6–8
    assert result_a["marathon"] == [1, 2, 3, 4, 5]
    assert result_a["movie"] == [6, 7, 8]

    # In order B: movie 1–3, marathon 4–8
    assert result_b["movie"] == [1, 2, 3]
    assert result_b["marathon"] == [4, 5, 6, 7, 8]


# ── canonical catalogue ────────────────────────────────────────────────────────

def test_canonical_order_has_expected_keys():
    expected = {
        "marathon", "tv_block", "tv_movie_mix", "movie",
        "entity", "network", "programming_block", "franchise", "specialty",
    }
    assert set(cb.CANONICAL_ORDER) == expected


def test_block_labels_covers_canonical_order():
    for key in cb.CANONICAL_ORDER:
        assert key in cb.BLOCK_LABELS, f"BLOCK_LABELS missing key: {key}"
