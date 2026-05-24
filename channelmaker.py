#!/usr/bin/env python3
"""channelmaker.py - Interactive CLI for the ChannelMaker pipeline."""

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


def header(title):
    bar = "-" * 52
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
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


def offer_plex_sync():
    if ask_yn("\nSync new channels to Plex DVR?", default="y"):
        step("Syncing Plex...")
        run(["sync_plex.py"])


# ── Prompt generator ──────────────────────────────────────────────────────────

def ask_choice(prompt, options, default=None):
    """Present a numbered list and return the selected value."""
    for i, (label, _) in enumerate(options, 1):
        marker = f"{BOLD}*{RESET}" if default and options[i-1][0] == default else " "
        print(f"  {marker} {i}) {label}")
    while True:
        val = input(f"{prompt} [{default or 1}]: ").strip()
        if not val:
            return options[0][1] if not default else next(v for l, v in options if l == default)
        try:
            idx = int(val) - 1
            if 0 <= idx < len(options):
                return options[idx][1]
        except ValueError:
            pass
        warn("Enter a number from the list.")


def generate_prompt():
    """Ask preference questions and write a tailored prompt to prompt_for_llm.md."""
    header("Customize Your Prompt")
    print(f"Answer a few questions to shape the LLM's output.")
    print(f"{DIM}Press Enter to accept the default for any question.{RESET}\n")

    # 1. Channel count
    target = ask("How many channels do you want", "40")
    print(f"  {DIM}Tip: ~1 channel per 15-20 titles in your library{RESET}\n")

    # 2. Era focus
    print("What era dominates your library?")
    era = ask_choice("Era", [
        ("All eras equally",         "all eras equally"),
        ("Heavy 80s/90s nostalgia",  "heavy 80s and 90s nostalgia"),
        ("2000s-2010s",              "2000s and 2010s content"),
        ("Modern (2020s+)",          "modern 2020s content"),
    ])
    print()

    # 3. TV style
    print("What TV channel style do you prefer?")
    tv_style = ask_choice("TV style", [
        ("Both marathons and themed blocks",  "both 24/7 single-show marathons and themed multi-show blocks"),
        ("Single-show marathons only",        "single-show 24/7 marathons; avoid multi-show blocks"),
        ("Themed multi-show blocks only",     "themed multi-show blocks; avoid single-show marathons"),
    ])
    print()

    # 4. Franchises
    franchises = ask("Any franchises you definitely want channels for? (e.g. MCU, Batman, John Wick)", "").strip()
    print()

    # 5. Skip anything?
    exclude = ask("Anything to deprioritize or skip entirely? (e.g. documentaries, kids content)", "").strip()
    print()

    # Build preferences section
    prefs = ["## My Preferences", ""]
    prefs.append(f"- **Era focus**: {era}")
    prefs.append(f"- **TV channel style**: {tv_style}")
    if franchises:
        prefs.append(f"- **Priority franchises**: {franchises} — make sure these get dedicated channels")
    if exclude:
        prefs.append(f"- **Deprioritize**: {exclude}")
    prefs_text = "\n".join(prefs)

    # Read base prompt, fill TARGET, inject preferences before ## The Library
    prompt_path = os.path.join(SCRIPT_DIR, "PROMPT.md")
    with open(prompt_path, encoding="utf-8") as f:
        base = f.read()

    base = base.replace("{TARGET}", target)
    base = base.replace("## The Library", prefs_text + "\n\n## The Library")

    out_path = os.path.join(SCRIPT_DIR, "prompt_for_llm.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(base)

    success(f"Prompt written to prompt_for_llm.md")
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

  1. Open {CYAN}{generated_path}{RESET}
     Your preferences are already filled in - just copy the whole file.

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

    if probe_and_deploy():
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

    if probe_and_deploy():
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
        offer_plex_sync()


# ── Utilities submenu ─────────────────────────────────────────────────────────

def utilities_menu():
    while True:
        header("Utilities")
        print("  f) Fetch channel images from TMDB")
        print("  s) Sync channels to Plex DVR")
        print(f"\n  {DIM}b) Back{RESET}\n")

        choice = input("Choice: ").strip().lower()

        if choice == "f":
            step("Previewing image changes (dry run)...")
            result = run(["fetch_images.py"])
            if result.returncode != 0:
                error("Fetch failed.")
                continue
            print()
            if ask_yn("Apply image updates to Tunarr?", default="n"):
                run(["fetch_images.py", "--apply"])

        elif choice == "s":
            step("Syncing Plex...")
            run(["sync_plex.py"])

        elif choice in ("b", ""):
            break

        else:
            warn("Unknown option.")


# ── Main menu ─────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        header("ChannelMaker")
        print("  1) AI path         - export -> paste into LLM -> deploy")
        print("  2) No-AI path      - auto-generate from metadata -> deploy")
        print("  3) Collections     - sync Plex collections -> deploy")
        print(f"\n  u) Utilities")
        print(f"  {DIM}q) Quit{RESET}\n")

        choice = input("Choice: ").strip().lower()

        if choice == "1":
            workflow_ai()
        elif choice == "2":
            workflow_no_ai()
        elif choice == "3":
            workflow_collections()
        elif choice == "u":
            utilities_menu()
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
