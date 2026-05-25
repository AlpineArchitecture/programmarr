#!/usr/bin/env python3
"""programmarr.py - Interactive CLI for the Programmarr pipeline."""

import json
import os
import subprocess
import sys

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RED    = "\033[31m"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    return subprocess.run([sys.executable] + cmd, cwd=SCRIPT_DIR)


LOGO = BOLD + CYAN + r"""
______
| ___ \
| |_/ / __ ___   __ _ _ __ __ _ _ __ ___  _ __ ___   __ _ _ __ _ __
|  __/ '__/ _ \ / _` | '__/ _` | '_ ` _ \| '_ ` _ \ / _` | '__| '__|
| |  | | | (_) | (_| | | | (_| | | | | | | | | | | | (_| | |  | |
\_|  |_|  \___/ \__, |_|  \__,_|_| |_| |_|_| |_| |_|\__,_|_|  |_|
                 __/ |
                |___/
""" + RESET


def header(title):
    print(LOGO)
    bar = "-" * 52
    print(f"{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}\n")


def step(msg):
    print(f"\n{BOLD}>> {msg}{RESET}")


def success(msg):
    print(f"{GREEN}[ok] {msg}{RESET}")


def warn(msg):
    print(f"{YELLOW}[!] {msg}{RESET}")


def error(msg):
    print(f"{RED}[x] {msg}{RESET}")


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else (default or "")


def ask_yn(prompt, default="n"):
    suffix = "[y/N]" if default.lower() == "n" else "[Y/n]"
    val = input(f"{prompt} {suffix}: ").strip().lower()
    if not val:
        return default.lower() == "y"
    return val in ("y", "yes")


# ── Config setup ──────────────────────────────────────────────────────────────

def setup_config():
    header("First-time setup")
    print("No config.json found. Let's set one up.\n")

    tunarr_url = ask("Tunarr URL", "http://192.168.1.10:8000")
    plex_url   = ask("Plex URL",   "http://192.168.1.10:32400")
    plex_token = ask("Plex token")
    tmdb_key   = ask("TMDB API key (optional - for channel logos, press Enter to skip)", "")

    config = {
        "tunarr_url": tunarr_url,
        "plex_url":   plex_url,
        "plex_token": plex_token,
    }
    if tmdb_key:
        config["tmdb_api_key"] = tmdb_key

    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    print()
    success("Config saved to config.json.")


# ── Shared steps ──────────────────────────────────────────────────────────────

def load_channels_json():
    path = os.path.join(SCRIPT_DIR, "channels.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def probe_and_deploy(extra_args=None):
    """Run probe, print output, ask confirmation, deploy if yes. Returns True on success."""
    extra = extra_args or []
    step("Running probe (dry run)...")
    result = run(["create.py", "--probe"] + extra)
    if result.returncode != 0:
        error("Probe failed - fix the errors above before deploying.")
        return False

    print()
    if not ask_yn("Deploy to Tunarr?", default="n"):
        warn("Deploy cancelled.")
        return False

    step("Deploying channels...")
    result = run(["create.py"] + extra)
    if result.returncode != 0:
        error("Deploy failed.")
        return False

    success("Channels deployed.")
    return True


def offer_collections_pipeline():
    """Offer to append Plex collections to channels.json inside the AI/No-AI pipeline."""
    if not ask_yn("\nInclude Plex collections as channels?", default="n"):
        return

    data = load_channels_json()
    max_ch = 0
    channel_count = 0
    if data and "channels" in data:
        nums = [ch.get("number", 0) for ch in data["channels"]]
        max_ch = max(nums) if nums else 0
        channel_count = len(nums)

    if max_ch:
        suggested_base = ((max_ch // 10) + 1) * 10
        suggested_base = max(suggested_base, 80)
        print(f"{DIM}Current channels.json: {channel_count} channels, highest #{max_ch}{RESET}\n")
    else:
        suggested_base = 80

    base      = ask("Start collection channels at number", str(suggested_base))
    min_items = ask("Skip collections with fewer than N items", "3")
    condense  = ask_yn(
        "Skip collections whose name already matches an existing channel? (--condense)",
        default="n",
    )

    cmd = ["generate_from_collections.py", "--apply", "--base", base, "--min-items", min_items]
    if condense:
        cmd.append("--condense")

    step("Fetching collections from Plex...")
    result = run(cmd)
    if result.returncode != 0:
        error("Collection generation failed — continuing without collections.")


def offer_images_pipeline():
    """Offer to fetch images post-deploy — applies directly, no dry-run preview."""
    if ask_yn("\nFetch channel images from TMDB?", default="n"):
        step("Fetching images...")
        run(["fetch_images.py", "--apply"])


def offer_plex_sync():
    if ask_yn("\nSync channels to Plex DVR?", default="y"):
        step("Syncing Plex...")
        run(["sync_plex.py"])


# ── Prompt generator ──────────────────────────────────────────────────────────
# TODO: re-implement preference questions here and inject them into the prompt
# before the ## The Library section. Stub retained for future use.

def generate_prompt():
    """Copy PROMPT.md to prompt_for_llm.md without modification."""
    prompt_path = os.path.join(SCRIPT_DIR, "PROMPT.md")
    out_path = os.path.join(SCRIPT_DIR, "prompt_for_llm.md")
    with open(prompt_path, encoding="utf-8") as f:
        base = f.read()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(base)
    success("Prompt written to prompt_for_llm.md")
    return out_path


# ── Workflows ─────────────────────────────────────────────────────────────────

def workflow_ai():
    header("AI Path")

    step("Exporting Plex library...")
    result = run(["export.py"])
    if result.returncode != 0:
        error("Export failed.")
        return

    print()
    generated_path = generate_prompt()

    csv_path      = os.path.join(SCRIPT_DIR, "plex_library.csv")
    channels_path = os.path.join(SCRIPT_DIR, "channels.json")

    print(f"""
{BOLD}Manual step - paste into your LLM{RESET}

  1. Open {CYAN}{generated_path}{RESET} and copy the whole file.

  2. Use the largest model available - Claude Opus, Gemini Pro/Ultra, GPT-4o.
     Speed-optimized models (Flash, Mini, Lite) tend to produce incomplete results
     on a task this size.

  3. Send using one of:

     {BOLD}Option A (recommended):{RESET} attach {CYAN}{csv_path}{RESET} as a file.
     The LLM reads it as structured data - more accurate, uses less context.

     {BOLD}Option B (works everywhere):{RESET} paste the full contents of the CSV
     directly after the prompt.

  4. Save the JSON output as:
     {CYAN}{channels_path}{RESET}
""")

    input(f"{BOLD}Press Enter when channels.json is ready...{RESET}")

    if not os.path.exists(channels_path):
        error("channels.json not found - aborting.")
        return

    offer_collections_pipeline()

    if probe_and_deploy():
        offer_images_pipeline()
        offer_plex_sync()


def workflow_no_ai():
    header("No-AI Path")

    step("Exporting Plex library...")
    result = run(["export.py"])
    if result.returncode != 0:
        error("Export failed.")
        return

    step("Generating channels from metadata...")
    result = run(["generate_no_ai.py"])
    if result.returncode != 0:
        error("Generation failed.")
        return

    offer_collections_pipeline()

    if probe_and_deploy():
        offer_images_pipeline()
        offer_plex_sync()


def workflow_collections():
    header("Collections Path")

    data = load_channels_json()
    max_ch = 0
    channel_count = 0
    if data and "channels" in data:
        nums = [ch.get("number", 0) for ch in data["channels"]]
        max_ch = max(nums) if nums else 0
        channel_count = len(nums)

    if max_ch:
        suggested_base = ((max_ch // 10) + 1) * 10
        suggested_base = max(suggested_base, 80)
        print(f"{DIM}Current channels.json: {channel_count} channels, highest #{max_ch}{RESET}\n")
    else:
        suggested_base = 80

    base      = ask("Start collection channels at number", str(suggested_base))
    min_items = ask("Skip collections with fewer than N items", "3")
    condense  = ask_yn(
        "Skip collections whose name already matches an existing channel? (--condense)",
        default="n",
    )

    cmd = ["generate_from_collections.py", "--apply", "--base", base, "--min-items", min_items]
    if condense:
        cmd.append("--condense")

    step("Fetching collections from Plex...")
    result = run(cmd)
    if result.returncode != 0:
        error("Collection generation failed.")
        return

    if probe_and_deploy(extra_args=["--from", base]):
        offer_images_pipeline()
        offer_plex_sync()


def fetch_images_standalone():
    """Standalone image fetch — dry run preview then confirm."""
    step("Previewing image changes (dry run)...")
    result = run(["fetch_images.py"])
    if result.returncode != 0:
        error("Fetch failed.")
        return
    print()
    if ask_yn("Apply image updates to Tunarr?", default="n"):
        run(["fetch_images.py", "--apply"])


# ── Main menu ─────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        header("Main Menu")
        print("  1) AI path         — export → LLM → deploy")
        print("  2) No-AI path      — auto-generate → deploy")
        print("  3) Collections     — sync Plex collections → deploy")
        print()
        print("  i) Fetch channel images from TMDB")
        print("  s) Sync channels to Plex DVR")
        print(f"\n  {DIM}q) Quit{RESET}\n")

        choice = input("Choice: ").strip().lower()

        if choice == "1":
            workflow_ai()
        elif choice == "2":
            workflow_no_ai()
        elif choice == "3":
            workflow_collections()
        elif choice == "i":
            fetch_images_standalone()
        elif choice == "s":
            step("Syncing Plex...")
            run(["sync_plex.py"])
        elif choice in ("q", ""):
            print(f"\n{DIM}Bye.{RESET}\n")
            sys.exit(0)
        else:
            warn("Unknown option.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    if not os.path.exists(config_path):
        setup_config()
    main_menu()


if __name__ == "__main__":
    main()
