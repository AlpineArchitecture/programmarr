"""parse_guide_xml — XMLTV -> {channels, programmes}. No live Tunarr needed."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _p in (str(BACKEND), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from routers.status_router import parse_guide_xml

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="C10.97.tunarr.com">
    <display-name>Comedy Marathon</display-name>
    <icon src="http://tunarr/icons/10.jpg" />
  </channel>
  <channel id="C20.97.tunarr.com">
    <display-name>Sci-Fi Block</display-name>
  </channel>
  <programme start="20260608100000 -0700" stop="20260608103000 -0700" channel="C10.97.tunarr.com">
    <title>Seinfeld</title>
    <sub-title>The Contest</sub-title>
  </programme>
  <programme start="20260608103000 -0700" stop="20260608110000 -0700" channel="C10.97.tunarr.com">
    <title>Seinfeld</title>
    <sub-title>The Soup</sub-title>
  </programme>
  <programme start="20260608100000 -0700" stop="20260608110000 -0700" channel="C20.97.tunarr.com">
    <title>The Expanse</title>
  </programme>
  <programme start="BADTIME" stop="BADTIME" channel="C10.97.tunarr.com">
    <title>Should Be Skipped</title>
  </programme>
</tv>"""


def test_channel_number_extracted():
    out = parse_guide_xml(FIXTURE)
    nums = [c["number"] for c in out["channels"]]
    assert 10 in nums
    assert 20 in nums


def test_channel_sorted_by_number():
    out = parse_guide_xml(FIXTURE)
    nums = [c["number"] for c in out["channels"]]
    assert nums == sorted(nums)


def test_channel_name_and_icon():
    out = parse_guide_xml(FIXTURE)
    ch10 = next(c for c in out["channels"] if c["number"] == 10)
    assert ch10["name"] == "Comedy Marathon"
    assert ch10["icon"] == "http://tunarr/icons/10.jpg"


def test_channel_without_icon_is_none():
    out = parse_guide_xml(FIXTURE)
    ch20 = next(c for c in out["channels"] if c["number"] == 20)
    assert ch20["icon"] is None


def test_programme_iso_time_conversion():
    out = parse_guide_xml(FIXTURE)
    prog = next(p for p in out["programmes"] if p["title"] == "Seinfeld" and p["episode"] == "The Contest")
    # ISO 8601 round-trip: the offset (-07:00) must be present
    assert "2026-06-08" in prog["start"]
    assert "-07:00" in prog["start"]
    assert "2026-06-08" in prog["stop"]


def test_programme_title_and_episode():
    out = parse_guide_xml(FIXTURE)
    prog = next(p for p in out["programmes"] if p["episode"] == "The Contest")
    assert prog["title"] == "Seinfeld"
    assert prog["number"] == 10


def test_programme_without_subtitle_has_empty_episode():
    out = parse_guide_xml(FIXTURE)
    prog = next(p for p in out["programmes"] if p["title"] == "The Expanse")
    assert prog["episode"] == ""


def test_malformed_timestamp_skipped():
    out = parse_guide_xml(FIXTURE)
    titles = [p["title"] for p in out["programmes"]]
    assert "Should Be Skipped" not in titles


def test_programme_count():
    out = parse_guide_xml(FIXTURE)
    # 3 valid + 1 malformed skipped = 3
    assert len(out["programmes"]) == 3
