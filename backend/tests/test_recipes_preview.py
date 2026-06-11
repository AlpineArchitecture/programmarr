"""/recipes/preview — franchise mode + unchanged title_contains."""

import json

import channel_engine
from routers import recipes_router


def test_preview_franchise_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes_router, "DATA_DIR", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"tunarr_url": "http://t"}))
    (tmp_path / "tmdb_enrichment.json").write_text(json.dumps({
        "sig": "x", "enrichment": {
            "Die Hard": {"title": "Die Hard", "year": 1988,
                         "collection": {"id": 1, "name": "Die Hard Collection"},
                         "keywords": []}}}))
    (tmp_path / "wikidata_cache.json").write_text(json.dumps({"sig": "x", "franchises": []}))

    movie_map = {"die hard": {"id": "p1", "program": {
        "title": "Die Hard", "releaseDate": 1, "year": 1988}}}
    monkeypatch.setattr(channel_engine, "build_library_index",
                        lambda url: (movie_map, {}))

    res = recipes_router.preview_recipe(recipes_router.PreviewRequest(
        value="Die Hard Collection", match="franchise"))
    assert res["count"] == 1
    assert res["matches"][0]["title"] == "Die Hard"
    assert res["match"] == "franchise"


def test_preview_title_contains_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes_router, "DATA_DIR", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"tunarr_url": "http://t"}))
    movie_map = {"die hard": {"id": "p1", "program": {
        "title": "Die Hard", "releaseDate": 1, "year": 1988}}}
    monkeypatch.setattr(channel_engine, "build_library_index",
                        lambda url: (movie_map, {}))
    res = recipes_router.preview_recipe(recipes_router.PreviewRequest(value="Die Hard"))
    assert res["count"] == 1
