"""channel_blocks.py — shared, pure channel-numbering layout.

Single source of truth for how channels are bucketed into numbered blocks.
**Pure and importable** (no config.json / argv / sys.exit), like channel_engine.py,
so both the subprocess scripts (generate_no_ai.py) and the long-lived FastAPI
backend (pipeline_router) can use it without side effects.

A *block* is a named, ordered category of channels with a configurable **size**
(how many channel numbers it reserves). Block start numbers are derived by
**accumulating sizes from a base**, so resizing one block shifts everything after
it — there are no fixed absolute lanes. This is what lets a large library scale a
category up (e.g. 100 movie channels) without colliding into the next block.

Defaults reproduce the historical cable-style layout when ``start=10``:
Marathons 10-19, TV Blocks 20-29, Movies 30-49, Franchise 50-69, Specialty 70-79.
Fresh deploys default to ``start=1`` (channel numbering truly begins at 1).
"""

# Canonical block order. Keys match the LLM/no-AI categories. The Planner's
# "entity" channels (studio/director/actor) share the "franchise" block start
# (historically channel 50) — see pipeline_router's compose mapping.
CANONICAL_ORDER = ["marathon", "tv_block", "movie", "franchise", "specialty"]

# Human-facing labels for the Settings UI and the generated prompt scheme.
BLOCK_LABELS = {
    "marathon": "TV Marathons",
    "tv_block": "TV Blocks",
    "movie": "Movie Channels",
    "franchise": "Franchise & Series",
    "specialty": "Specialty",
}

# Default block sizes — reproduce the historical 10/10/20/20/10 layout.
DEFAULT_SIZES = {
    "marathon": 10,
    "tv_block": 10,
    "movie": 20,
    "franchise": 20,
    "specialty": 10,
}

# Fresh deploys begin at channel 1 (the protection flow rounds up above kept ones).
DEFAULT_START = 1


def normalize_sizes(sizes) -> dict:
    """Return a complete size map, filling missing/invalid entries from defaults.

    Each size is coerced to an int >= 1, so a malformed config can never produce a
    zero-width or negative block.
    """
    sizes = sizes or {}
    out = {}
    for key in CANONICAL_ORDER:
        try:
            v = int(sizes.get(key, DEFAULT_SIZES[key]))
        except (TypeError, ValueError):
            v = DEFAULT_SIZES[key]
        out[key] = max(1, v)
    return out


def resolve_layout(sizes=None, start: int = DEFAULT_START) -> dict:
    """Map each block to its placement, accumulating sizes from ``start``.

    Returns an ordered dict ``{key: {"start", "size", "end"}}`` where ``end`` is
    inclusive (``start + size - 1``). Block N+1 begins immediately after block N.
    """
    sizes = normalize_sizes(sizes)
    layout: dict = {}
    cursor = int(start)
    for key in CANONICAL_ORDER:
        size = sizes[key]
        layout[key] = {"start": cursor, "size": size, "end": cursor + size - 1}
        cursor += size
    return layout
