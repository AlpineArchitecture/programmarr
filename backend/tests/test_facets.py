"""library_facets — genre/decade/blend/entity/marathon counts + thresholds."""

from conftest import movie, show


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
