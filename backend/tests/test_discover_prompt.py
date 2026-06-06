"""discover_prompt — seeds from channels.json, numbers from max+1, curate + discover sections."""

import json


def _write_channels(pr, channels):
    data = {"channels": channels, "orphaned": [], "suggested_channels": []}
    (pr._test_data_dir / "channels.json").write_text(json.dumps(data), encoding="utf-8")


def test_seeds_from_existing_lineup_and_numbers_from_max_plus_one(pr):
    _write_channels(pr, [
        {"number": 10, "name": "Comedy", "content": []},
        {"number": 12, "name": "Horror", "content": []},
    ])
    res = pr.discover_prompt(pr.DiscoverOptions(discover=True))
    assert res["start"] == 13          # max(12) + 1
    assert res["existing_count"] == 2
    assert "#10 Comedy" in res["content"]
    assert "#12 Horror" in res["content"]
    assert "13" in res["content"]      # new channels numbered from here


def test_no_existing_defaults_start_to_10(pr):
    # No channels.json at all -> max defaults to 9, start = 10.
    res = pr.discover_prompt(pr.DiscoverOptions(discover=True))
    assert res["start"] == 10
    assert res["existing_count"] == 0
    assert "(none yet)" in res["content"]


def test_curate_section_present_only_with_pools(pr):
    _write_channels(pr, [{"number": 10, "name": "Comedy", "content": []}])
    with_pools = pr.discover_prompt(pr.DiscoverOptions(
        discover=False, curate_pools=["Comedy: all comedy movies"]))
    assert "Curate these pools by tone" in with_pools["content"]
    assert "Comedy: all comedy movies" in with_pools["content"]

    without = pr.discover_prompt(pr.DiscoverOptions(discover=False, curate_pools=[]))
    assert "Curate these pools by tone" not in without["content"]


def test_discover_section_toggle(pr):
    _write_channels(pr, [{"number": 10, "name": "Comedy", "content": []}])
    on = pr.discover_prompt(pr.DiscoverOptions(discover=True))
    off = pr.discover_prompt(pr.DiscoverOptions(discover=False, curate_pools=["x"]))
    assert "Discover additional channels" in on["content"]
    assert "Discover additional channels" not in off["content"]
