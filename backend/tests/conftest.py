"""Shared pytest fixtures for the backend smoke suite.

Points the pipeline router at a temp data dir seeded with a synthetic
plex_library.csv, so the deterministic units (facets / compose / validate /
discover-prompt) can be exercised in isolation without a real Plex export.
"""

import csv
import sys
from pathlib import Path

import pytest

# The router imports `scheduler` (backend/) which imports `channel_engine` (repo
# root) — both must be importable the same way main.py wires them.
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _p in (str(BACKEND), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Exact header export.py writes (see export.py fieldnames). Multi-valued columns
# (Genres / Director / Actors / Country / Mood / Style) are pipe-separated.
CSV_FIELDS = ["Title", "Year", "Type", "Rating", "Genres",
              "Director", "Studio", "Actors", "Seasons", "Episodes",
              "Country", "Mood", "Style"]


def movie(title, year=2000, genres="", studio="", director="", actors="", rating="PG",
          country="", mood="", style=""):
    return {"Title": title, "Year": str(year), "Type": "Movie", "Rating": rating,
            "Genres": genres, "Director": director, "Studio": studio, "Actors": actors,
            "Country": country, "Mood": mood, "Style": style}


def show(title, genres="", seasons=1, episodes=10, studio=""):
    return {"Title": title, "Type": "TV", "Genres": genres,
            "Studio": studio, "Seasons": str(seasons), "Episodes": str(episodes)}


@pytest.fixture
def pr(tmp_path, monkeypatch):
    """The pipeline_router module with DATA_DIR redirected to a temp dir."""
    from routers import pipeline_router as module
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "SCRIPTS_DIR", ROOT)
    monkeypatch.setattr(module, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setenv("PROGRAMMARR_DATA", str(tmp_path))
    module._test_data_dir = tmp_path  # convenience handle for assertions
    return module


@pytest.fixture
def seed(pr):
    """Write a synthetic plex_library.csv into the router's temp DATA_DIR."""
    def _seed(rows):
        path = pr._test_data_dir / "plex_library.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
        return path
    return _seed
