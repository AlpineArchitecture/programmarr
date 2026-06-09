"""channel_blocks.py — shared, pure channel-numbering layout.

Single source of truth for how channels are bucketed into numbered categories.
**Pure and importable** (no config.json / argv / sys.exit), like channel_engine.py,
so both the subprocess scripts (generate_no_ai.py) and the long-lived FastAPI
backend (pipeline_router) can use it without side effects.

Channels are numbered sequentially from a start value, packed tight in category
order.  A "category" is simply a named bucket; categories with zero channels
consume no numbers.  The only configurable knob is the *order* of the categories,
stored as ``channel_order`` in config.json (a list of category key strings).

Example: order [marathon, movie, franchise], counts {marathon:15, movie:8,
franchise:3}, start 1 → marathon 1–15, movie 16–23, franchise 24–26.
"""

# Canonical category order — the full future set in the order used when no
# config override is present.  Later steps map Planner candidates onto these keys.
CANONICAL_ORDER = [
    "marathon",
    "tv_block",
    "tv_movie_mix",
    "movie",
    "entity",
    "network",
    "programming_block",
    "franchise",
    "specialty",
]

# Human-facing labels for the Settings UI and generated prompt guidance.
BLOCK_LABELS = {
    "marathon":          "TV Marathons",
    "tv_block":          "TV Blocks",
    "tv_movie_mix":      "TV & Movie Mix",
    "movie":             "Movie Channels",
    "entity":            "Studios / Directors / Actors",
    "network":           "Networks",
    "programming_block": "Classic TV Blocks",
    "franchise":         "Franchise & Series",
    "specialty":         "Specialty",
}

# Fresh deploys begin at channel 1 (the protection flow rounds up above kept ones).
DEFAULT_START = 1


def resolve_order(configured: list | None) -> list:
    """Return the effective category order from a config value.

    Rules:
    - Start with ``configured`` filtered to known CANONICAL_ORDER keys (unknown
      keys are silently dropped so stale configs don't crash).
    - Append any CANONICAL_ORDER keys that are missing from ``configured``
      (preserving canonical relative order for the tail).
    - If ``configured`` is falsy (None, empty list) fall back to CANONICAL_ORDER.
    """
    known = set(CANONICAL_ORDER)
    if not configured:
        return list(CANONICAL_ORDER)
    filtered = [k for k in configured if k in known]
    present = set(filtered)
    tail = [k for k in CANONICAL_ORDER if k not in present]
    return filtered + tail


def assign_numbers(order: list, counts: dict, start: int = DEFAULT_START) -> dict:
    """Return {category: [channel numbers]} packed sequentially from ``start``.

    Categories in ``order`` that have no entry in ``counts`` (or a zero count)
    consume no channel numbers.  The first non-empty category begins at ``start``;
    every subsequent non-empty category follows immediately after.

    Args:
        order:  Ordered list of category keys (from resolve_order).
        counts: {category_key: number_of_channels}.  Missing keys treated as 0.
        start:  The first channel number to assign (default 1).

    Returns:
        Dict mapping each category key (with count > 0) to its list of channel
        numbers.  Categories with count == 0 are omitted.

    Example:
        assign_numbers(["marathon", "movie", "franchise"],
                       {"marathon": 15, "movie": 8, "franchise": 3}, start=1)
        → {"marathon": [1..15], "movie": [16..23], "franchise": [24..26]}
    """
    result: dict = {}
    cursor = int(start)
    for key in order:
        n = counts.get(key, 0)
        if n > 0:
            result[key] = list(range(cursor, cursor + n))
            cursor += n
    return result
