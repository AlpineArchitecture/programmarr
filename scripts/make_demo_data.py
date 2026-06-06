#!/usr/bin/env python3
"""Generate a synthetic demo dataset for screenshots and onboarding.

Writes a self-contained data dir (default: ./demo) holding the three files the web
app reads — plex_library.csv, channels.json, config.json (plus export_summary.json)
— so the app can be launched in "demo mode" without touching your real library:

    PROGRAMMARR_DATA=./demo PROGRAMMARR_SCRIPTS=. python -m uvicorn main:app --app-dir backend

Everything here is DETERMINISTIC (no RNG) so the rendered UI — and therefore the
docs screenshots — is byte-for-byte identical every run. The movie/TV titles are
real, recognizable, public films; the genres/years are roughly accurate, but the
studio/director/actor assignments are rotated deterministically only to cross the
Planner's entity thresholds (which film a given director "made" here isn't shown in
the UI — only the candidate counts are). No real tokens, IPs, or library data.

Run:  python scripts/make_demo_data.py [--out demo]
"""

import argparse
import csv
import json
from pathlib import Path

# ── Movie pool: (title, year, [genres]) ─────────────────────────────────────────
# Tuned so the Planner's genre×decade (>=6) and blend (>=6) cells populate: lots of
# Comedy in the 90s, Action in the 80s, Horror in the 80s, Sci-Fi in the 2010s, etc.
MOVIES = [
    # ── Comedy (heavy in the 90s for a genre×decade cell) ──
    ("Airplane!", 1980, ["Comedy"]),
    ("Caddyshack", 1980, ["Comedy"]),
    ("Ghostbusters", 1984, ["Comedy", "Fantasy"]),
    ("Coming to America", 1988, ["Comedy", "Romance"]),
    ("Groundhog Day", 1993, ["Comedy", "Romance"]),
    ("Dumb and Dumber", 1994, ["Comedy"]),
    ("Happy Gilmore", 1996, ["Comedy"]),
    ("The Big Lebowski", 1998, ["Comedy", "Crime"]),
    ("There's Something About Mary", 1998, ["Comedy", "Romance"]),
    ("Office Space", 1999, ["Comedy"]),
    ("Galaxy Quest", 1999, ["Comedy", "Science Fiction"]),
    ("Anchorman", 2004, ["Comedy"]),
    ("Superbad", 2007, ["Comedy"]),
    ("Hot Fuzz", 2007, ["Comedy", "Action"]),
    ("Tropic Thunder", 2008, ["Comedy", "Action"]),
    ("Bridesmaids", 2011, ["Comedy", "Romance"]),
    ("21 Jump Street", 2012, ["Comedy", "Action"]),
    ("The Grand Budapest Hotel", 2014, ["Comedy", "Drama"]),
    ("Game Night", 2018, ["Comedy", "Crime"]),
    ("Palm Springs", 2020, ["Comedy", "Romance"]),

    # ── Action (heavy in the 80s) ──
    ("Mad Max", 1979, ["Action"]),
    ("The Road Warrior", 1981, ["Action", "Science Fiction"]),
    ("First Blood", 1982, ["Action"]),
    ("The Terminator", 1984, ["Action", "Science Fiction"]),
    ("Commando", 1985, ["Action"]),
    ("Aliens", 1986, ["Action", "Science Fiction"]),
    ("Predator", 1987, ["Action", "Science Fiction"]),
    ("RoboCop", 1987, ["Action", "Science Fiction"]),
    ("Die Hard", 1988, ["Action", "Thriller"]),
    ("Lethal Weapon", 1987, ["Action", "Crime"]),
    ("Total Recall", 1990, ["Action", "Science Fiction"]),
    ("Point Break", 1991, ["Action", "Crime"]),
    ("Speed", 1994, ["Action", "Thriller"]),
    ("The Rock", 1996, ["Action", "Thriller"]),
    ("Face/Off", 1997, ["Action", "Thriller"]),
    ("The Matrix", 1999, ["Action", "Science Fiction"]),
    ("Gladiator", 2000, ["Action", "Drama"]),
    ("The Bourne Identity", 2002, ["Action", "Thriller"]),
    ("Casino Royale", 2006, ["Action", "Thriller"]),
    ("Mad Max: Fury Road", 2015, ["Action", "Science Fiction"]),
    ("John Wick", 2014, ["Action", "Crime"]),

    # ── Horror (heavy in the 80s) ──
    ("The Shining", 1980, ["Horror"]),
    ("The Evil Dead", 1981, ["Horror"]),
    ("Poltergeist", 1982, ["Horror"]),
    ("The Thing", 1982, ["Horror", "Science Fiction"]),
    ("A Nightmare on Elm Street", 1984, ["Horror"]),
    ("Re-Animator", 1985, ["Horror"]),
    ("The Fly", 1986, ["Horror", "Science Fiction"]),
    ("Hellraiser", 1987, ["Horror"]),
    ("Child's Play", 1988, ["Horror", "Thriller"]),
    ("Scream", 1996, ["Horror", "Thriller"]),
    ("The Ring", 2002, ["Horror", "Thriller"]),
    ("28 Days Later", 2002, ["Horror", "Science Fiction"]),
    ("The Conjuring", 2013, ["Horror", "Thriller"]),
    ("It Follows", 2014, ["Horror"]),
    ("Get Out", 2017, ["Horror", "Thriller"]),
    ("Hereditary", 2018, ["Horror", "Drama"]),
    ("Midsommar", 2019, ["Horror", "Drama"]),

    # ── Science Fiction (heavy in the 2010s) ──
    ("Alien", 1979, ["Science Fiction", "Horror"]),
    ("Blade Runner", 1982, ["Science Fiction"]),
    ("Back to the Future", 1985, ["Science Fiction", "Comedy"]),
    ("Jurassic Park", 1993, ["Science Fiction", "Action"]),
    ("Contact", 1997, ["Science Fiction", "Drama"]),
    ("Children of Men", 2006, ["Science Fiction", "Thriller"]),
    ("Inception", 2010, ["Science Fiction", "Action"]),
    ("Looper", 2012, ["Science Fiction", "Thriller"]),
    ("Edge of Tomorrow", 2014, ["Science Fiction", "Action"]),
    ("Interstellar", 2014, ["Science Fiction", "Drama"]),
    ("Ex Machina", 2014, ["Science Fiction", "Drama"]),
    ("The Martian", 2015, ["Science Fiction", "Drama"]),
    ("Arrival", 2016, ["Science Fiction", "Drama"]),
    ("Blade Runner 2049", 2017, ["Science Fiction", "Drama"]),
    ("Annihilation", 2018, ["Science Fiction", "Horror"]),
    ("Dune", 2021, ["Science Fiction", "Adventure"]),

    # ── Drama (heavy in the 2000s) ──
    ("Raging Bull", 1980, ["Drama"]),
    ("Goodfellas", 1990, ["Drama", "Crime"]),
    ("The Shawshank Redemption", 1994, ["Drama"]),
    ("American Beauty", 1999, ["Drama"]),
    ("Memento", 2000, ["Drama", "Thriller"]),
    ("No Country for Old Men", 2007, ["Drama", "Crime"]),
    ("There Will Be Blood", 2007, ["Drama"]),
    ("The Departed", 2006, ["Drama", "Crime"]),
    ("Zodiac", 2007, ["Drama", "Crime"]),
    ("The Social Network", 2010, ["Drama"]),
    ("Whiplash", 2014, ["Drama"]),
    ("Moonlight", 2016, ["Drama"]),
    ("Parasite", 2019, ["Drama", "Thriller"]),
    ("Nomadland", 2020, ["Drama"]),

    # ── Animation ──
    ("The Lion King", 1994, ["Animation"]),
    ("Toy Story", 1995, ["Animation", "Comedy"]),
    ("Spirited Away", 2001, ["Animation", "Fantasy"]),
    ("Finding Nemo", 2003, ["Animation", "Comedy"]),
    ("The Incredibles", 2004, ["Animation", "Action"]),
    ("Ratatouille", 2007, ["Animation", "Comedy"]),
    ("WALL-E", 2008, ["Animation", "Science Fiction"]),
    ("Up", 2009, ["Animation", "Drama"]),
    ("Spider-Man: Into the Spider-Verse", 2018, ["Animation", "Action"]),
    ("Soul", 2020, ["Animation", "Drama"]),

    # ── Documentary ──
    ("Hoop Dreams", 1994, ["Documentary"]),
    ("Bowling for Columbine", 2002, ["Documentary"]),
    ("March of the Penguins", 2005, ["Documentary"]),
    ("Man on Wire", 2008, ["Documentary"]),
    ("Searching for Sugar Man", 2012, ["Documentary"]),
    ("Won't You Be My Neighbor?", 2018, ["Documentary"]),
    ("Free Solo", 2018, ["Documentary"]),
    ("My Octopus Teacher", 2020, ["Documentary"]),

    # ── Western (a "more" genre, >=5) ──
    ("The Outlaw Josey Wales", 1976, ["Western"]),
    ("Unforgiven", 1992, ["Western", "Drama"]),
    ("Tombstone", 1993, ["Western", "Action"]),
    ("3:10 to Yuma", 2007, ["Western", "Action"]),
    ("True Grit", 2010, ["Western", "Drama"]),
    ("Django Unchained", 2012, ["Western", "Drama"]),
    ("The Hateful Eight", 2015, ["Western", "Crime"]),

    # ── Romance (a "more" genre, >=5) ──
    ("When Harry Met Sally", 1989, ["Romance", "Comedy"]),
    ("Pretty Woman", 1990, ["Romance", "Comedy"]),
    ("Titanic", 1997, ["Romance", "Drama"]),
    ("Notting Hill", 1999, ["Romance", "Comedy"]),
    ("Eternal Sunshine of the Spotless Mind", 2004, ["Romance", "Science Fiction"]),
    ("La La Land", 2016, ["Romance", "Drama"]),

    # ── Fantasy (a "more" genre, >=5) ──
    ("The Princess Bride", 1987, ["Fantasy", "Comedy"]),
    ("The Lord of the Rings: The Fellowship of the Ring", 2001, ["Fantasy", "Adventure"]),
    ("Pan's Labyrinth", 2006, ["Fantasy", "Drama"]),
    ("The Shape of Water", 2017, ["Fantasy", "Drama"]),
    ("The Green Knight", 2021, ["Fantasy", "Adventure"]),
]

# Studios / directors / actors are rotated across the movie list so each crosses its
# Planner threshold (studio>=4, director>=3, actor>=4) for a populated candidate list.
STUDIOS = [
    "A24", "Universal Pictures", "Warner Bros.", "Paramount Pictures",
    "Walt Disney Pictures", "20th Century Studios", "New Line Cinema", "Blumhouse",
]
DIRECTORS = [
    "Steven Spielberg", "Christopher Nolan", "Quentin Tarantino", "Martin Scorsese",
    "Greta Gerwig", "Denis Villeneuve", "Kathryn Bigelow", "Jordan Peele",
    "Ridley Scott", "The Coen Brothers",
]
ACTORS = [
    "Tom Hanks", "Samuel L. Jackson", "Scarlett Johansson", "Leonardo DiCaprio",
    "Frances McDormand", "Denzel Washington", "Tilda Swinton", "Oscar Isaac",
    "Viola Davis", "Brad Pitt", "Cate Blanchett", "Michael B. Jordan",
    "Saoirse Ronan", "Idris Elba", "Florence Pugh",
]

# ── TV pool: (title, [genres], seasons, episodes) ───────────────────────────────
# Several shows clear 50 episodes (marathon-eligible); a few short runs exercise the
# >=2-episode marathon list. TV genres with >=3 shows show up as TV-block candidates.
SHOWS = [
    ("The Simpsons", ["Animation", "Comedy"], 35, 768),
    ("Friends", ["Comedy", "Romance"], 10, 236),
    ("Seinfeld", ["Comedy"], 9, 180),
    ("The Office", ["Comedy"], 9, 201),
    ("Parks and Recreation", ["Comedy"], 7, 126),
    ("It's Always Sunny in Philadelphia", ["Comedy"], 16, 170),
    ("Cheers", ["Comedy"], 11, 275),
    ("Frasier", ["Comedy"], 11, 264),
    ("Breaking Bad", ["Drama", "Crime"], 5, 62),
    ("Better Call Saul", ["Drama", "Crime"], 6, 63),
    ("The Sopranos", ["Drama", "Crime"], 6, 86),
    ("Mad Men", ["Drama"], 7, 92),
    ("The Wire", ["Drama", "Crime"], 5, 60),
    ("Lost", ["Drama", "Science Fiction"], 6, 121),
    ("The X-Files", ["Drama", "Science Fiction"], 11, 218),
    ("Stranger Things", ["Drama", "Science Fiction"], 4, 34),
    ("Game of Thrones", ["Drama", "Fantasy"], 8, 73),
    ("Fargo", ["Drama", "Crime"], 5, 51),
    ("True Detective", ["Drama", "Crime"], 4, 30),
    ("Twin Peaks", ["Drama", "Mystery"], 3, 48),
    ("Rick and Morty", ["Animation", "Comedy"], 7, 71),
    ("Futurama", ["Animation", "Comedy"], 8, 140),
    ("BoJack Horseman", ["Animation", "Comedy"], 6, 77),
    ("Archer", ["Animation", "Comedy"], 14, 146),
    ("Avatar: The Last Airbender", ["Animation", "Adventure"], 3, 61),
    ("Planet Earth", ["Documentary"], 2, 17),
    ("Cosmos", ["Documentary"], 2, 26),
    ("Chernobyl", ["Drama"], 1, 5),
    ("Band of Brothers", ["Drama"], 1, 10),
    ("Sherlock", ["Drama", "Mystery"], 4, 15),
]

CSV_FIELDS = ["Title", "Year", "Type", "Rating", "Genres",
              "Director", "Studio", "Actors", "Seasons", "Episodes"]
RATINGS = ["G", "PG", "PG-13", "R"]


def build_movie_rows():
    rows = []
    for i, (title, year, genres) in enumerate(MOVIES):
        # Deterministic rotation so every studio/director/actor crosses its threshold.
        studio = STUDIOS[i % len(STUDIOS)]
        director = DIRECTORS[i % len(DIRECTORS)]
        actors = "|".join(ACTORS[(i + k) % len(ACTORS)] for k in range(3))
        rows.append({
            "Title": title, "Year": str(year), "Type": "Movie",
            "Rating": RATINGS[i % len(RATINGS)], "Genres": "|".join(genres),
            "Director": director, "Studio": studio, "Actors": actors,
            "Seasons": "", "Episodes": "",
        })
    return rows


def build_show_rows():
    rows = []
    for title, genres, seasons, episodes in SHOWS:
        rows.append({
            "Title": title, "Year": "", "Type": "TV", "Rating": "TV-14",
            "Genres": "|".join(genres), "Director": "", "Studio": "", "Actors": "",
            "Seasons": str(seasons), "Episodes": str(episodes),
        })
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def build_channels(movie_rows, show_rows):
    """A curated demo lineup so the Channels / Deploy screens look populated."""
    def titles_with_genre(rows, genre):
        gl = genre.lower()
        return sorted(r["Title"] for r in rows
                      if any(g.strip().lower() == gl for g in r["Genres"].split("|")))

    channels = []
    # Marathons (10s): the longest-running shows.
    top_shows = sorted(show_rows, key=lambda s: -int(s["Episodes"]))[:4]
    for n, s in enumerate(top_shows, start=10):
        channels.append({"number": n, "name": f"{s['Title']} 24/7",
                         "shuffle": "ordered", "content": [s["Title"]]})
    # Movie genre channels (30s).
    for n, genre in enumerate(["Comedy", "Action", "Horror", "Science Fiction", "Drama"], start=30):
        name = "Sci-Fi Movies" if genre == "Science Fiction" else f"{genre} Movies"
        channels.append({"number": n, "name": name, "shuffle": "shuffle",
                         "content": titles_with_genre(movie_rows, genre)})
    # An entity channel (50s).
    nolan = sorted(r["Title"] for r in movie_rows if r["Director"] == "Christopher Nolan")
    channels.append({"number": 50, "name": "Directed by Christopher Nolan",
                     "shuffle": "shuffle", "content": nolan})
    return {"channels": channels, "orphaned": [], "suggested_channels": []}


DEMO_CONFIG = {
    "tunarr_url": "http://tunarr.demo.local:8000",
    "plex_url": "http://plex.demo.local:32400",
    "plex_token": "DEMO-TOKEN-NOT-A-REAL-SECRET",
    "tmdb_api_key": "",
    "auth_username": "",
    "auth_password": "",
}


def main():
    ap = argparse.ArgumentParser(description="Generate the synthetic demo dataset")
    ap.add_argument("--out", default="demo", help="Output data dir (default: demo)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(exist_ok=True)

    movie_rows = build_movie_rows()
    show_rows = build_show_rows()
    write_csv(out / "plex_library.csv", movie_rows + show_rows)

    with open(out / "export_summary.json", "w", encoding="utf-8") as f:
        json.dump({"movies": len(movie_rows), "tv_shows": len(show_rows),
                   "skipped_movies": 0, "skipped_shows": 0}, f, indent=2)

    with open(out / "channels.json", "w", encoding="utf-8") as f:
        json.dump(build_channels(movie_rows, show_rows), f, indent=2, ensure_ascii=False)

    with open(out / "config.json", "w", encoding="utf-8") as f:
        json.dump(DEMO_CONFIG, f, indent=2)

    print(f"Wrote demo dataset to {out}/ — {len(movie_rows)} movies, {len(show_rows)} shows")
    print("Launch demo mode:")
    print(f"  $env:PROGRAMMARR_DATA='{out.resolve()}'; $env:PROGRAMMARR_SCRIPTS='{Path.cwd()}'; "
          "python -m uvicorn main:app --app-dir backend --port 7979")


if __name__ == "__main__":
    main()
