"""generate_no_ai flags — --genres/--decades/--types/--start produce expected blocks.

Run as a subprocess (the script is a monolithic argparse main(), the same way the
web app invokes it) against a synthetic CSV in a temp dir.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "generate_no_ai.py"
CSV_FIELDS = ["Title", "Year", "Type", "Rating", "Genres",
              "Director", "Studio", "Actors", "Seasons", "Episodes"]


def _movie(title, year, genres):
    return {"Title": title, "Year": str(year), "Type": "Movie", "Genres": genres}


def _show(title, episodes):
    return {"Title": title, "Type": "TV", "Episodes": str(episodes), "Seasons": "5"}


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def _run(tmp_path, rows, *flags):
    csv_path = tmp_path / "lib.csv"
    out_path = tmp_path / "out.json"
    _write_csv(csv_path, rows)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--csv", str(csv_path), "--out", str(out_path), *flags],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))["channels"]


def test_genres_and_decades_toggle(tmp_path):
    rows = [
        _movie("Nineties Com", 1995, "Comedy"),
        _movie("Eighties Act", 1985, "Action"),
    ]
    chans = _run(tmp_path, rows, "--types", "movies",
                 "--genres", "Comedy", "--decades", "1990", "--min-items", "1")
    names = {c["name"] for c in chans}
    assert "90s Movies" in names      # decade toggle honored
    assert "Comedy Movies" in names   # genre toggle honored
    assert "80s Movies" not in names  # 1980 decade not selected
    assert "Action Movies" not in names
    # Movie block numbers live in the 30s.
    assert all(30 <= c["number"] <= 49 for c in chans)


def test_marathons_type_only(tmp_path):
    rows = [
        _show("Long Runner", 200),
        _show("Short Run", 10),          # under 50 eps -> not a marathon
        _movie("Some Film", 2001, "Drama"),
    ]
    chans = _run(tmp_path, rows, "--types", "marathons")
    names = [c["name"] for c in chans]
    assert names == ["Long Runner 24/7"]   # only the 50+ ep show, no movie channels
    assert chans[0]["number"] == 10


def test_start_offset_shifts_blocks(tmp_path):
    rows = [_movie(f"C{i}", 1995, "Comedy") for i in range(3)]
    chans = _run(tmp_path, rows, "--types", "movies",
                 "--genres", "Comedy", "--decades", "1990",
                 "--min-items", "1", "--start", "30")
    # Blocks accumulate from --start 30: marathon 30s, tv_block 40s, so movies land at 50+.
    assert all(c["number"] >= 50 for c in chans)
