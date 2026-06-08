"""build_prompt — numbering scheme + example numbers regenerate from the live block layout."""

import json


def test_prompt_scheme_reflects_default_layout_at_start_one(pr):
    out = pr.build_prompt(pr.PromptOptions(start=1))["content"]
    # Default sizes from channel 1: marathon 1–10, tv_block 11–20, movie 21–40.
    assert "**1–10**" in out
    assert "**11–20**" in out
    assert "**21–40**" in out
    assert '"number": 1,' in out      # marathon example
    assert '"number": 11,' in out     # tv_block example
    assert '"number": 21,' in out     # movie example


def test_prompt_scheme_reflects_custom_block_sizes(pr):
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_blocks": {"marathon": 100, "tv_block": 100}}), encoding="utf-8")
    out = pr.build_prompt(pr.PromptOptions(start=1))["content"]
    assert "**1–100**" in out        # marathon scaled to 100 wide
    assert "**101–200**" in out      # tv_block shifted up after it
    assert '"number": 101,' in out   # tv_block example follows the layout
