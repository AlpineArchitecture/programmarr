"""library_facets — genre/decade/blend/entity/marathon counts + thresholds."""

from conftest import movie, show

# ── F12: countries / moods / styles ────────────────────────────────────────────


def test_canonical_genres_always_present_even_at_zero(pr, seed):
    seed([movie("Solo", genres="Comedy")])
    f = pr.library_facets()
    tags = {g["tag"] for g in f["genres"]["canonical"]}
    # All 7 canonical genres returned regardless of library contents.
    assert tags == {"Comedy", "Action", "Horror", "Science Fiction",
                    "Drama", "Animation", "Documentary"}
    comedy = next(g for g in f["genres"]["canonical"] if g["tag"] == "Comedy")
    assert comedy["count"] == 1


def test_more_genres_respect_min_items(pr, seed):
    rows = [movie(f"W{i}", genres="Western") for i in range(5)]      # >= min_items(5)
    rows += [movie(f"N{i}", genres="Noir") for i in range(4)]         # below threshold
    seed(rows)
    f = pr.library_facets(min_items=5)
    more = {g["tag"] for g in f["genres"]["more"]}
    assert "Western" in more
    assert "Noir" not in more


def test_decades_counts(pr, seed):
    seed([movie("A", year=1995), movie("B", year=1997), movie("C", year=2003)])
    f = pr.library_facets()
    by_start = {d["start"]: d["count"] for d in f["decades"]}
    assert by_start[1990] == 2
    assert by_start[2000] == 1
    assert 1970 not in by_start  # empty decades omitted


def test_genre_decade_matrix_threshold(pr, seed):
    # COMBO_MIN = 6 comedies in the 90s qualifies; 5 would not.
    seed([movie(f"C{i}", year=1995, genres="Comedy") for i in range(6)])
    f = pr.library_facets()
    cells = [(c["genre"], c["decade_start"], c["count"]) for c in f["genre_decade"]]
    assert ("Comedy", 1990, 6) in cells


def test_genre_decade_below_threshold_absent(pr, seed):
    seed([movie(f"C{i}", year=1995, genres="Comedy") for i in range(5)])
    f = pr.library_facets()
    assert all(c["genre"] != "Comedy" for c in f["genre_decade"])


def test_blends_threshold(pr, seed):
    # BLEND_MIN = 6 movies sharing two shown genres.
    seed([movie(f"CD{i}", genres="Comedy|Drama") for i in range(6)])
    f = pr.library_facets()
    pairs = [tuple(b["genres"]) for b in f["blends"]]
    assert ("Comedy", "Drama") in pairs


def test_entity_thresholds(pr, seed):
    rows = [movie(f"A24-{i}", studio="A24") for i in range(4)]          # STUDIO_MIN = 4
    rows += [movie(f"Nolan{i}", director="Christopher Nolan") for i in range(3)]  # DIRECTOR_MIN = 3
    rows += [movie(f"Hanks{i}", actors="Tom Hanks") for i in range(4)]  # ACTOR_MIN = 4
    rows += [movie("Tiny", studio="Mom&Pop")]                           # below studio floor
    seed(rows)
    f = pr.library_facets()
    assert "A24" in {s["value"] for s in f["studios"]}
    assert "Mom&Pop" not in {s["value"] for s in f["studios"]}
    assert "Christopher Nolan" in {d["value"] for d in f["directors"]}
    assert "Tom Hanks" in {a["value"] for a in f["actors"]}


def test_tv_genres_and_marathons(pr, seed):
    seed([
        show("Sitcom A", genres="Comedy", episodes=120),
        show("Sitcom B", genres="Comedy", episodes=60),
        show("Sitcom C", genres="Comedy", episodes=3),   # counts for genre, not marathon_count
        show("Mini", genres="Drama", episodes=2),         # eps>=2 so in marathons list
    ])
    f = pr.library_facets()
    tv = {g["genre"]: g["count"] for g in f["tv_genres"]}
    assert tv.get("Comedy") == 3            # TV_GENRE_MIN = 3 met
    assert f["marathon_count"] == 2          # only eps >= 50
    # marathons list holds every show with >= 2 episodes, sorted by episodes desc.
    titles = [m["title"] for m in f["marathons"]]
    assert titles[0] == "Sitcom A"
    assert "Mini" in titles


def test_no_csv_returns_not_exists(pr):
    assert pr.library_facets() == {"exists": False}


# ── tv_movie_genres ────────────────────────────────────────────────────────────

def test_tv_movie_genres_requires_both_sides(pr, seed):
    """A genre present only in movies (or only in TV) does NOT appear in tv_movie_genres."""
    seed([
        movie("Funny Movie 1", genres="Comedy"),
        movie("Funny Movie 2", genres="Comedy"),
        movie("Funny Movie 3", genres="Comedy"),
        # Comedy only on movie side — no TV Comedy shows
        show("Action Show 1", genres="Action", episodes=20),
        show("Action Show 2", genres="Action", episodes=30),
        show("Action Show 3", genres="Action", episodes=15),
        # Action only on TV side — no Action movies
    ])
    f = pr.library_facets()
    genres_in_mix = {x["genre"] for x in f["tv_movie_genres"]}
    assert "Comedy" not in genres_in_mix   # movie only
    assert "Action" not in genres_in_mix   # TV only


def test_tv_movie_genres_appears_when_both_sides_above_floor(pr, seed):
    """A genre with >= TV_MOVIE_MIX_MIN on each side appears in tv_movie_genres with correct counts."""
    seed([
        movie("Drama Movie 1", genres="Drama"),
        movie("Drama Movie 2", genres="Drama"),
        movie("Drama Movie 3", genres="Drama"),
        show("Drama Show 1", genres="Drama", episodes=20),
        show("Drama Show 2", genres="Drama", episodes=30),
        show("Drama Show 3", genres="Drama", episodes=15),
    ])
    f = pr.library_facets()
    drama = next((x for x in f["tv_movie_genres"] if x["genre"] == "Drama"), None)
    assert drama is not None
    assert drama["tv_count"] == 3
    assert drama["movie_count"] == 3


def test_tv_movie_genres_floor_respected(pr, seed):
    """A genre with only 2 entries on one side (below TV_MOVIE_MIX_MIN=3) is excluded."""
    seed([
        movie("Sci Movie 1", genres="Science Fiction"),
        movie("Sci Movie 2", genres="Science Fiction"),
        # Only 2 movies — below floor
        show("Sci Show 1", genres="Science Fiction", episodes=50),
        show("Sci Show 2", genres="Science Fiction", episodes=40),
        show("Sci Show 3", genres="Science Fiction", episodes=30),
    ])
    f = pr.library_facets()
    genres_in_mix = {x["genre"] for x in f["tv_movie_genres"]}
    assert "Science Fiction" not in genres_in_mix


def test_tv_movie_genres_sorted_by_total_desc(pr, seed):
    """Genres are sorted by (tv_count + movie_count) descending."""
    # Comedy: 5 movies + 3 shows = 8 total
    # Drama: 3 movies + 4 shows = 7 total
    seed(
        [movie(f"Com{i}", genres="Comedy") for i in range(5)] +
        [show(f"ComShow{i}", genres="Comedy", episodes=20) for i in range(3)] +
        [movie(f"Dra{i}", genres="Drama") for i in range(3)] +
        [show(f"DraShow{i}", genres="Drama", episodes=20) for i in range(4)]
    )
    f = pr.library_facets()
    mix_genres = [x["genre"] for x in f["tv_movie_genres"]]
    assert mix_genres.index("Comedy") < mix_genres.index("Drama")


# ── networks ───────────────────────────────────────────────────────────────────
# NOTE: Networks now derive from the TVmaze cache (tvmaze_cache.json), NOT the
# Studio column.  Comprehensive tests for all network behaviors live in
# test_networks.py.  The tests here verify only the core facets contract that is
# unaffected by the source change (returned shape, existence key, etc.).

def test_networks_empty_when_no_tvmaze_cache(pr, seed):
    """Networks facet returns [] when TVmaze cache is absent (scan not run yet)."""
    seed([
        show("Show A", studio="HBO"),
        show("Show B", studio="HBO"),
        show("Show C", studio="HBO"),
    ])
    # No tvmaze_cache.json → empty, regardless of Studio column.
    f = pr.library_facets()
    assert f["networks"] == []


def test_networks_from_tvmaze_cache_not_studio(pr, seed):
    """Networks facet values come from TVmaze cache even when Studio says something else."""
    import json
    seed([
        show("Show A", studio="WrongLabel"),
        show("Show B", studio="WrongLabel"),
        show("Show C", studio="WrongLabel"),
    ])
    sig = pr._library_signature()
    cache = {"sig": sig, "networks": {"Show A": "HBO", "Show B": "HBO", "Show C": "HBO"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    by_value = {n["value"]: n["count"] for n in f["networks"]}
    assert by_value.get("HBO") == 3
    assert "WrongLabel" not in by_value


def test_networks_below_floor_omitted(pr, seed):
    """Networks with fewer than NETWORK_MIN (3) shows in the cache are not returned."""
    import json
    seed([show("Show 1"), show("Show 2")])
    sig = pr._library_signature()
    cache = {"sig": sig, "networks": {"Show 1": "HBO", "Show 2": "HBO"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    assert len(f["networks"]) == 0


# ── programming-blocks endpoint ────────────────────────────────────────────────

def test_programming_blocks_filters_to_library(pr, seed, tmp_path, monkeypatch):
    """Only blocks with present_count >= BLOCK_MIN (3) are returned; present_shows
    contains only titles found in the library."""
    import json
    catalog = [
        {
            "name": "TGIF",
            "era": "1989–2000",
            "network": "ABC",
            "shows": ["Full House", "Family Matters", "Step by Step", "Boy Meets World"],
        },
        {
            "name": "Must See TV",
            "era": "1994–2004",
            "network": "NBC",
            "shows": ["Seinfeld", "Friends"],  # only 2 possible matches — below BLOCK_MIN
        },
    ]
    catalog_path = tmp_path / "programming_blocks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(pr, "SCRIPTS_DIR", tmp_path)

    # Seed library with 3 of the 4 TGIF shows (qualifying), 0 of 2 NBC shows.
    seed([
        show("Full House", episodes=192),
        show("Family Matters", episodes=215),
        show("Step by Step", episodes=160),
        # Boy Meets World absent
        # No Seinfeld or Friends in library
    ])

    result = pr.get_programming_blocks()
    names = [b["name"] for b in result]
    assert "TGIF" in names
    assert "Must See TV" not in names

    tgif = next(b for b in result if b["name"] == "TGIF")
    assert tgif["present_count"] == 3
    assert set(tgif["present_shows"]) == {"Full House", "Family Matters", "Step by Step"}


def test_programming_blocks_respects_block_min(pr, seed, tmp_path, monkeypatch):
    """Blocks with exactly BLOCK_MIN (3) matches are included; blocks with 2 are excluded."""
    import json
    catalog = [
        {
            "name": "Block A",
            "era": "1990s",
            "network": "ABC",
            "shows": ["Show1", "Show2", "Show3"],  # exactly 3 — at the floor, should be included
        },
        {
            "name": "Block B",
            "era": "1990s",
            "network": "NBC",
            "shows": ["Show4", "Show5"],  # 2 shows in library — below floor
        },
    ]
    catalog_path = tmp_path / "programming_blocks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(pr, "SCRIPTS_DIR", tmp_path)

    seed([
        show("Show1", episodes=50),
        show("Show2", episodes=50),
        show("Show3", episodes=50),
        show("Show4", episodes=50),
        show("Show5", episodes=50),
    ])

    result = pr.get_programming_blocks()
    names = [b["name"] for b in result]
    assert "Block A" in names
    assert "Block B" not in names


def test_programming_blocks_case_insensitive_match(pr, seed, tmp_path, monkeypatch):
    """Title matching for programming blocks is case-insensitive."""
    import json
    catalog = [
        {
            "name": "Test Block",
            "era": "1990s",
            "network": "Test",
            "shows": ["Full House", "Family Matters", "Step by Step"],
        }
    ]
    catalog_path = tmp_path / "programming_blocks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(pr, "SCRIPTS_DIR", tmp_path)

    # Library has titles with different casing.
    seed([
        show("full house", episodes=192),       # different case
        show("FAMILY MATTERS", episodes=215),   # all caps
        show("Step by Step", episodes=160),
    ])

    result = pr.get_programming_blocks()
    assert len(result) == 1
    assert result[0]["present_count"] == 3


def test_programming_blocks_no_csv_returns_empty(pr, tmp_path, monkeypatch):
    """Returns empty list if no plex_library.csv exists."""
    import json
    catalog = [{"name": "TGIF", "era": "1989–2000", "network": "ABC",
                "shows": ["Full House", "Family Matters", "Step by Step"]}]
    catalog_path = tmp_path / "programming_blocks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(pr, "SCRIPTS_DIR", tmp_path)

    # No seed call — no CSV exists.
    result = pr.get_programming_blocks()
    assert result == []


# ── F12: countries / moods / styles facets ─────────────────────────────────────

def test_countries_facet_above_floor(pr, seed):
    """countries facet returns countries with >= COUNTRY_MIN (3) movies."""
    seed([movie(f"Fr{i}", country="France") for i in range(3)]
         + [movie(f"Jp{i}", country="Japan") for i in range(2)]   # below floor
         + [movie(f"De{i}", country="Germany") for i in range(4)])
    f = pr.library_facets()
    by_value = {c["value"]: c["count"] for c in f["countries"]}
    assert by_value.get("France") == 3
    assert by_value.get("Germany") == 4
    assert "Japan" not in by_value


def test_countries_facet_empty_when_column_absent(pr, seed):
    """countries facet returns [] when the CSV has no Country column (old export)."""
    # seed() writes all CSV_FIELDS, but rows built with movie() default country=""
    # — so the column exists but is empty.  Simulate old CSV by omitting the column.
    import csv
    from conftest import CSV_FIELDS
    path = pr._test_data_dir / "plex_library.csv"
    old_fields = [f for f in CSV_FIELDS if f not in ("Country", "Mood", "Style")]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=old_fields)
        w.writeheader()
        w.writerow({"Title": "Film", "Year": "2000", "Type": "Movie", "Rating": "PG",
                    "Genres": "Drama", "Director": "", "Studio": "", "Actors": "",
                    "Seasons": "", "Episodes": ""})
    f = pr.library_facets()
    # No Country column → _multi(row.get("Country")) == [] → no counts → empty list.
    assert f["countries"] == []


def test_moods_facet_above_floor(pr, seed):
    """moods facet returns moods with >= MOOD_MIN (3) movies."""
    seed([movie(f"F{i}", mood="Feel-Good") for i in range(3)]
         + [movie(f"D{i}", mood="Dark") for i in range(2)])  # below floor
    f = pr.library_facets()
    by_value = {m["value"]: m["count"] for m in f["moods"]}
    assert by_value.get("Feel-Good") == 3
    assert "Dark" not in by_value


def test_styles_facet_above_floor(pr, seed):
    """styles facet returns styles with >= STYLE_MIN (3) movies."""
    seed([movie(f"N{i}", style="Film Noir") for i in range(3)]
         + [movie(f"S{i}", style="Screwball Comedy") for i in range(5)])
    f = pr.library_facets()
    by_value = {s["value"]: s["count"] for s in f["styles"]}
    assert by_value.get("Film Noir") == 3
    assert by_value.get("Screwball Comedy") == 5


def test_country_multi_value(pr, seed):
    """A movie with multiple Country tags is counted for each country."""
    seed([movie(f"Co-prod{i}", country="France|Germany") for i in range(3)])
    f = pr.library_facets()
    by_value = {c["value"]: c["count"] for c in f["countries"]}
    assert by_value.get("France") == 3
    assert by_value.get("Germany") == 3


def test_countries_moods_styles_empty_by_default(pr, seed):
    """When no Country/Mood/Style data is present, all three facets return []."""
    seed([movie(f"M{i}", genres="Drama") for i in range(5)])
    f = pr.library_facets()
    assert f["countries"] == []
    assert f["moods"] == []
    assert f["styles"] == []
