#!/usr/bin/env python3
"""programmarr.py - Interactive CLI for the Programmarr pipeline."""

import json
import os
import subprocess
import sys
import urllib.request

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

def load_config():
    path = os.path.join(SCRIPT_DIR, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_tunarr_channels():
    """Return the list of channels currently in Tunarr, or None on failure."""
    config = load_config()
    url = config.get("tunarr_url", "").rstrip("/") + "/api/channels"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def load_channels_json():
    path = os.path.join(SCRIPT_DIR, "channels.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_and_fix_channels_json(path):
    """Ensure channels.json is usable. Handles JSON dict, bare array, and JSONL."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        error(f"Could not read channels.json: {e}")
        return False

    # Try standard JSON first (dict or bare array)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "channels" in data:
            return True
        if isinstance(data, list):
            warn("channels.json is a bare JSON array — wrapping automatically.")
            data = {"channels": data, "orphaned": [], "suggested_channels": []}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            success(f"channels.json ready: {len(data['channels'])} channels.")
            return True
        error('channels.json must have a "channels" key. Fix it and try again.')
        return False
    except json.JSONDecodeError:
        pass

    # Try JSONL — one channel object per line
    channels = []
    bad_lines = []
    for i, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "number" in obj:
                channels.append(obj)
            else:
                bad_lines.append(i)
        except json.JSONDecodeError:
            bad_lines.append(i)

    if bad_lines:
        warn(f"Skipped {len(bad_lines)} malformed line(s): {bad_lines}")

    if not channels:
        error("channels.json contains no valid channel objects. Fix it and try again.")
        return False

    warn(f"Detected JSONL format — converting ({len(channels)} channels).")
    data = {"channels": channels, "orphaned": [], "suggested_channels": []}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    success(f"channels.json ready: {len(channels)} channels.")
    return True


def confirm_deploy_scope():
    """Check Tunarr for existing channels and let the user choose deploy scope.
    Returns extra_args to pass to probe_and_deploy ([] for full wipe, ['--from', N] for partial)."""
    existing = fetch_tunarr_channels()

    if not existing:
        return []

    nums = sorted(ch.get("number", 0) for ch in existing)
    count = len(nums)
    print(f"\n{YELLOW}[!] Tunarr currently has {count} channel(s) (#{nums[0]}–#{nums[-1]}).{RESET}")
    print(f"\n  1) Wipe all and deploy fresh  {DIM}(full rebuild — recommended when channels.json changed significantly){RESET}")
    print(f"  2) Preserve channels below a number  {DIM}(keep lower channels and their custom images){RESET}")

    choice = input("\nChoice [1]: ").strip() or "1"

    if choice == "2":
        from_num = ask("Preserve channels below number", str(nums[-1] + 1))
        return ["--from", from_num]

    return []


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


def is_collection_channel(ch):
    return any(isinstance(item, dict) and "collection" in item for item in ch.get("content", []))


def offer_collections_pipeline():
    """Offer to append Plex collections to channels.json inside the AI/No-AI pipeline."""
    data = load_channels_json()
    max_ch = 0
    channel_count = 0
    if data and "channels" in data:
        ai_channels = [ch for ch in data["channels"] if not is_collection_channel(ch)]
        nums = [ch.get("number", 0) for ch in ai_channels]
        max_ch = max(nums) if nums else 0
        channel_count = len(ai_channels)

    if max_ch:
        suggested_base = ((max_ch // 10) + 1) * 10
        print(f"\n{DIM}channels.json: {channel_count} channels, highest #{max_ch} — collections would start at #{suggested_base}{RESET}")
    else:
        suggested_base = 80

    if not ask_yn("Include Plex collections as channels?", default="n"):
        return

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
        print(f"""
{BOLD}Plex tip:{RESET} If channels aren't showing up in the Plex guide, the easiest fix is to
delete the Tunarr DVR in Plex and re-add it — Plex will re-import all channels fresh.

  Plex Settings → Live TV & DVR → (your Tunarr device) → Delete → Add device again.
""")
    input(f"{DIM}Press Enter to return to the main menu...{RESET}")


# ── Prompt generator ──────────────────────────────────────────────────────────

def generate_prompt():
    """Build prompt_for_llm.md from PROMPT.md, injecting user preferences if provided."""
    prompt_path = os.path.join(SCRIPT_DIR, "PROMPT.md")
    out_path = os.path.join(SCRIPT_DIR, "prompt_for_llm.md")

    with open(prompt_path, encoding="utf-8") as f:
        base = f.read()

    print()
    target = input(
        f"How many channels do you want? {DIM}(rule of thumb: ~1 per 15–20 titles — press Enter to skip){RESET}\n"
        f"> "
    ).strip()
    if target:
        base = base.replace("{TARGET}", target)

    prefs = input(
        f"\nAny specific channels or themes you want?\n"
        f"{DIM}e.g. Batman, Documentaries, 90s, TGIF, Cartoons — press Enter to skip{RESET}\n"
        f"> "
    ).strip()

    if prefs:
        injection = (
            "\n## User Preferences\n\n"
            "The user has specifically requested the following channels or themes. "
            "Treat these as high-priority — if the library has enough content to support them, "
            "they must appear in the output:\n\n"
            f"{prefs}\n"
        )
        base = base.replace("## Channel Numbering Scheme", injection + "\n## Channel Numbering Scheme")

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

  4. Save the output (one channel per line) as:
     {CYAN}{channels_path}{RESET}
""")

    input(f"{BOLD}Press Enter when channels.json is ready...{RESET}")

    if not os.path.exists(channels_path):
        error("channels.json not found - aborting.")
        return

    if not validate_and_fix_channels_json(channels_path):
        return

    offer_collections_pipeline()

    scope = confirm_deploy_scope()
    if probe_and_deploy(extra_args=scope):
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

    scope = confirm_deploy_scope()
    if probe_and_deploy(extra_args=scope):
        offer_images_pipeline()
        offer_plex_sync()


def workflow_collections():
    header("Collections Path")

    data = load_channels_json()
    max_ch = 0
    channel_count = 0
    if data and "channels" in data:
        ai_channels = [ch for ch in data["channels"] if not is_collection_channel(ch)]
        nums = [ch.get("number", 0) for ch in ai_channels]
        max_ch = max(nums) if nums else 0
        channel_count = len(ai_channels)

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
