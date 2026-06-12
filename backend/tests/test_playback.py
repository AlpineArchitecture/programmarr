"""Playback structure — interleaved random-slot weighting + timeline manual lineups."""

import channel_engine


def _movie_item(title, pid, release_ms=None, duration=5400000):
    return {"type": "Movie", "title": title, "programs": [
        {"id": pid, "program": {"title": title, "releaseDate": release_ms,
                                "duration": duration, "year": 1990}}]}


def _show_item(title, show_id, episodes):
    """episodes: list of (pid, season, ep, release_ms)"""
    return {"type": "TV", "title": title, "showId": show_id, "programs": [
        {"id": pid, "program": {"title": f"{title} s{s}e{e}", "duration": 1800000,
                                "seasonNumber": s, "episode": e, "releaseDate": rms}}
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
