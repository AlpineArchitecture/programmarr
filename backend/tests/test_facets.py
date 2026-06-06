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
