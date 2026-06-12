"""Playback structure — interleaved random-slot weighting + timeline manual lineups."""

import channel_engine


def _movie_item(title, pid, release_ms=None, duration=5400000):
    return {"type": "Movie", "title": title, "programs": [
        {"id": pid, "program": {"title": title, "releaseDate": release_ms,
                                "duration": duration, "year": 1990}}]}


def _show_item(title, show_id, episodes):
    """episodes: list of (pid, season, ep, release_ms)
    Uses real Tunarr field names: season={index: N} and episodeNumber.
    """
    return {"type": "TV", "title": title, "showId": show_id, "programs": [
        {"id": pid, "program": {"title": f"{title} s{s}e{e}", "duration": 1800000,
                                "season": {"index": s}, "episodeNumber": e,
                                "releaseDate": rms}}
        for pid, s, e, rms in episodes]}


def _slots(schedule):
    return schedule["schedule"]["slots"]


# ── interleaved ───────────────────────────────────────────────────────────────

def test_interleaved_weights_movies_vs_episode_blocks():
    items = [
        _movie_item("Movie A", "m1", 100),
        _movie_item("Movie B", "m2", 200),
        _show_item("Show X", "sx", [("e1", 1, 1, 50), ("e2", 1, 2, 60)]),
        _show_item("Show Y", "sy", [("e3", 1, 1, 70)]),
    ]
    sched = channel_engine.build_schedule(
        "ordered", items, playback={"structure": "interleaved", "episodes_per_block": 4})
    assert sched["type"] == "random"
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    show_slots = [s for s in _slots(sched) if s["type"] == "show"]
    assert len(movie_slots) == 1 and len(show_slots) == 2
    assert movie_slots[0]["order"] == "chronological"
    assert movie_slots[0]["weight"] == 2          # = number of shows
    assert all(s["order"] == "next" for s in show_slots)
    assert all(s["weight"] == 4 for s in show_slots)  # = episodes_per_block


def test_interleaved_default_block_size_is_4():
    items = [_movie_item("Movie A", "m1", 100),
             _show_item("Show X", "sx", [("e1", 1, 1, 50)])]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "interleaved"})
    show_slots = [s for s in _slots(sched) if s["type"] == "show"]
    assert show_slots[0]["weight"] == 4
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    assert movie_slots[0]["weight"] == 1          # one show


def test_interleaved_movies_only_degrades_gracefully():
    items = [_movie_item("Movie A", "m1", 100)]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "interleaved"})
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    assert movie_slots[0]["order"] == "chronological"
    assert movie_slots[0]["weight"] == 1


def test_no_playback_is_byte_identical_to_today():
    items = [_movie_item("Movie A", "m1", 100),
             _show_item("Show X", "sx", [("e1", 1, 1, 50)])]
    a = channel_engine.build_schedule("ordered", items)
    b = channel_engine.build_schedule("ordered", items, playback=None)
    # uuids differ per call; compare everything except slot ids
    def strip(s):
        return {**s, "schedule": {**s["schedule"],
                "slots": [{k: v for k, v in sl.items() if k != "id"}
                          for sl in s["schedule"]["slots"]]}}
    assert strip(a) == strip(b)
    sl = strip(a)["schedule"]["slots"]
    assert all(x["weight"] == 1 for x in sl)      # today's weights untouched


# ── timeline ──────────────────────────────────────────────────────────────────

def test_timeline_builds_manual_lineup_in_premiere_order():
    items = [
        _movie_item("Late Movie", "m2", 900),
        _show_item("Mid Show", "sx", [("e2", 1, 2, 510), ("e1", 1, 1, 500)]),
        _movie_item("Early Movie", "m1", 100),
    ]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "timeline"})
    assert sched["type"] == "manual"
    assert sched["append"] is False
    ids = [li["id"] for li in sched["lineup"]]
    # Early Movie (100) → Mid Show premiere (500; episodes in s/e order) → Late Movie (900)
    assert ids == ["m1", "e1", "e2", "m2"]
    assert all(li["type"] == "content" for li in sched["lineup"])
    assert all(isinstance(li["duration"], int) and li["duration"] > 0
               for li in sched["lineup"])


def test_timeline_show_without_releasedate_sorts_by_year_then_end():
    items = [
        _movie_item("Movie 1990", "m1", 700000000000),  # ~1992 in ms — fine, just ordered
        {"type": "TV", "title": "Undated Show", "showId": "sz", "programs": [
            {"id": "z1", "program": {"title": "Undated s1e1", "duration": 1800000,
                                     "season": {"index": 1}, "episodeNumber": 1,
                                     "releaseDate": None, "year": None}}]},
    ]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "timeline"})
    ids = [li["id"] for li in sched["lineup"]]
    assert ids == ["m1", "z1"]  # undated content sorts to the end, never crashes


def test_timeline_empty_items_returns_none():
    assert channel_engine.build_schedule(
        "ordered", [], playback={"structure": "timeline"}) is None
