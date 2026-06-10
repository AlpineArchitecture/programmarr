"""generate_no_ai flags — --genres/--decades/--types/--order/--start produce expected output.

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
    assert "90s Movies" in names       # decade toggle honored
    assert "Comedy Movies" in names    # genre toggle honored
    assert "80s Movies" not in names   # 1980 decade not selected
    assert "Action Movies" not in names


def test_marathons_type_only(tmp_path):
    rows = [
        _show("Long Runner", 200),
        _show("Short Run", 10),          # under 50 eps -> not a marathon
        _movie("Some Film", 2001, "Drama"),
    ]
    chans = _run(tmp_path, rows, "--types", "marathons")
    names = [c["name"] for c in chans]
    assert names == ["Long Runner 24/7"]   # only the 50+ ep show, no movie channels
    assert chans[0]["number"] == 1         # sequential from default start=1


def test_start_offset_shifts_all_numbers(tmp_path):
    rows = [_movie(f"C{i}", 1995, "Comedy") for i in range(3)]
    chans = _run(tmp_path, rows, "--types", "movies",
                 "--genres", "Comedy", "--decades", "1990",
                 "--min-items", "1", "--start", "20")
    # All numbers start at or above 20.
    assert all(c["number"] >= 20 for c in chans)


def test_sequential_no_gaps(tmp_path):
    """Numbers are contiguous — no block-size gaps."""
    rows = [
        _show("Show A", 200),
        _show("Show B", 100),
        _movie("Film A", 1995, "Comedy"),
        _movie("Film B", 1985, "Horror"),
    ]
    chans = _run(tmp_path, rows, "--types", "marathons,movies",
                 "--genres", "Comedy,Horror", "--min-items", "1", "--start", "1")
    numbers = sorted(c["number"] for c in chans)
    # Should be 1, 2, 3, 4, ... with no holes.
    assert numbers == list(range(1, len(numbers) + 1))


def test_order_flag_changes_numbering(tmp_path):
    """--order movie,marathon puts movies before marathons in the number sequence."""
    rows = [
        _show("Loop Show", 200),
        _movie("Comedy Film", 1995, "Comedy"),
    ]
    # Default order (marathon first)
    chans_default = _run(tmp_path, rows, "--types", "marathons,movies",
                         "--genres", "Comedy", "--min-items", "1", "--start", "1")
    by_name_d = {c["name"]: c["number"] for c in chans_default}

    # Reversed order (movie first)
    chans_rev = _run(tmp_path, rows, "--types", "marathons,movies",
                     "--genres", "Comedy", "--min-items", "1", "--start", "1",
                     "--order", "movie,marathon")
    by_name_r = {c["name"]: c["number"] for c in chans_rev}

    # In default order marathons come first → lower number
    assert by_name_d["Loop Show 24/7"] < by_name_d["Comedy Movies"]
    # In reversed order movies come first → lower number
    assert by_name_r["Comedy Movies"] < by_name_r["Loop Show 24/7"]


def test_empty_category_skipped(tmp_path):
    """Categories with no content produce no channels and no numbers are reserved."""
    rows = [_show("Loop Show", 200)]
    # Only marathons type, but we explicitly request movies too — no movie rows
    chans = _run(tmp_path, rows, "--types", "marathons,movies",
                 "--genres", "Comedy", "--min-items", "1", "--start", "1")
    names = [c["name"] for c in chans]
    assert "Loop Show 24/7" in names
    # All numbers start at 1, contiguous
    numbers = sorted(c["number"] for c in chans)
    assert numbers == list(range(1, len(numbers) + 1))
