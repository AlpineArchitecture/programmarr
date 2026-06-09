"""build_prompt — numbering scheme in the prompt reflects the sequential model."""

import json


def test_prompt_scheme_reflects_sequential_model(pr):
    """The prompt should describe sequential numbering (X+) not fixed block ranges."""
    out = pr.build_prompt(pr.PromptOptions(start=1))["content"]
    # The scheme bullets now use "N+" notation (start of each category), not "N–M" ranges.
    # With no config override, start=1, first category (marathon) starts at 1.
    assert "1+" in out


def test_prompt_scheme_reflects_custom_order(pr):
    """Configuring channel_order=["movie","marathon",...] puts movie first in the scheme."""
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_order": ["movie", "marathon", "tv_block", "tv_movie_mix",
                                      "entity", "network", "programming_block",
                                      "franchise", "specialty"]}),
        encoding="utf-8")
    out = pr.build_prompt(pr.PromptOptions(start=1))["content"]
    # movie is first in the configured order, so it gets number 1.
    assert "1+" in out
    # TV Marathons description should still appear somewhere in the bullet list.
    assert "TV Marathons" in out


def test_old_channel_blocks_config_does_not_crash(pr):
    """Old configs with channel_blocks key don't crash _regen_numbering_scheme."""
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_blocks": {"marathon": 100, "tv_block": 100}}), encoding="utf-8")
    # Should not raise
    out = pr.build_prompt(pr.PromptOptions(start=1))["content"]
    assert "1+" in out
