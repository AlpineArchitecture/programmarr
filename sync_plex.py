#!/usr/bin/env python3
"""
sync_plex.py — Sync Tunarr channels into Plex's Live TV guide.

After running create.py, Plex may not know about new channels.
This script attempts to update Plex's DVR channel mappings automatically.
If it can't do it via API, it prints the XMLTV URL and manual steps.

Usage:
    python sync_plex.py            # check and attempt auto-sync
    python sync_plex.py --probe    # show current state, no changes
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG_FILE = "config.json"


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        sys.exit(1)


# ── HTTP helpers ────────────────────────────────────────────────────────────────

def plex_get(plex_url, token, path):
    url = f"{plex_url}{path}?X-Plex-Token={token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception as e:
        print(f"  ! Plex GET {path}: {e}")
        return None


def plex_put(plex_url, token, path, data):
    url = f"{plex_url}{path}?X-Plex-Token={token}"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT",
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        return e.code, {}


def tunarr_get(tunarr_url, path):
    try:
        with urllib.request.urlopen(tunarr_url + path, timeout=10) as r:
            return r.read().decode()
    except Exception as e:
        print(f"  ! Tunarr GET {path}: {e}")
        return None


# ── Core logic ──────────────────────────────────────────────────────────────────

def get_tunarr_channels(tunarr_url):
    """Returns {channel_number: xmltv_channel_id} from Tunarr's XMLTV guide."""
    xml = tunarr_get(tunarr_url, "/api/xmltv.xml")
    if not xml:
        return {}
    channel_ids = re.findall(r'<channel id="([^"]+)">', xml)
    result = {}
    for cid in channel_ids:
        num = cid.split(".")[0][1:]  # C10.97.tunarr.com -> "10"
        result[num] = cid
    return result


def get_plex_dvr(plex_url, token):
    """Returns (dvr, device) tuple or (None, None) if no DVR configured."""
    data = plex_get(plex_url, token, "/livetv/dvrs")
    if not data:
        return None, None
    dvrs = data.get("MediaContainer", {}).get("Dvr", [])
    if not dvrs:
        return None, None
    dvr = dvrs[0]
    devices = dvr.get("Device", [])
    device = devices[0] if devices else None
    return dvr, device


def get_mapped_channel_numbers(device):
    """Returns the set of channel numbers currently mapped in Plex."""
    if not device:
        return set()
    return {cm["deviceIdentifier"] for cm in device.get("ChannelMapping", [])}


def attempt_soft_update(plex_url, token, dvr_key, device_key, xmltv_map):
    """
    Try to add all channels via PUT to the device endpoint.
    Returns True if Plex accepted the update and channels changed.
    """
    data = {}
    for num, chkey in xmltv_map.items():
        data[f"channelMappings[{chkey}].deviceIdentifier"] = num
        data[f"channelMappings[{chkey}].lineupIdentifier"] = num
        data[f"channelMappings[{chkey}].enabled"] = "1"

    status, resp = plex_put(plex_url, token, f"/livetv/dvrs/{dvr_key}/devices/{device_key}", data)

    if status != 200:
        return False

    # Plex returns status:-1 with "device in use" when it can't apply — check for that
    mc = resp.get("MediaContainer", {})
    if mc.get("status") == -1:
        return False

    return True


def print_manual_instructions(tunarr_url):
    xmltv_url = f"{tunarr_url}/api/xmltv.xml"
    print()
    print("  Manual setup steps:")
    print("  1. Open Plex → Settings → Live TV & DVR")
    print("  2. Click 'Set Up Plex DVR'")
    print("  3. Select Tunarr as the DVR device")
    print("  4. When asked for a guide source, enter this URL:")
    print()
    print(f"       {xmltv_url}")
    print()
    print("  5. Select all channels (use Select All if available)")
    print("  6. Complete the wizard")


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync Tunarr channels into Plex DVR guide")
    parser.add_argument("--probe", action="store_true", help="Show state only, no changes")
    args = parser.parse_args()

    cfg = load_config()
    plex_url = cfg["plex_url"].rstrip("/")
    tunarr_url = cfg["tunarr_url"].rstrip("/")
    token = cfg["plex_token"]

    # ── Fetch Tunarr channels ─────────────────────────────────────────────────
    print("Fetching Tunarr channel list...")
    xmltv_map = get_tunarr_channels(tunarr_url)
    if not xmltv_map:
        print("ERROR: Could not fetch XMLTV from Tunarr")
        sys.exit(1)
    print(f"  {len(xmltv_map)} channels in Tunarr")

    # ── Fetch Plex DVR state ──────────────────────────────────────────────────
    print("Fetching Plex DVR state...")
    dvr, device = get_plex_dvr(plex_url, token)

    if not dvr or not device:
        print("  No DVR configured in Plex.")
        print_manual_instructions(tunarr_url)
        sys.exit(0)

    mapped = get_mapped_channel_numbers(device)
    tunarr_nums = set(xmltv_map.keys())
    missing = tunarr_nums - mapped

    print(f"  {len(mapped)} channels currently mapped in Plex")
    print(f"  {len(missing)} channels not yet mapped")

    if not missing:
        print("\nPlex is already in sync — nothing to do.")
        return

    if args.probe:
        print(f"\n[PROBE] Would attempt to map {len(missing)} missing channels:")
        for num in sorted(missing, key=int):
            print(f"  #{num}")
        return

    # ── Attempt soft update ───────────────────────────────────────────────────
    print(f"\nAttempting to add {len(missing)} channels to Plex...")
    dvr_key = dvr["key"]
    device_key = device["key"]

    accepted = attempt_soft_update(plex_url, token, dvr_key, device_key, xmltv_map)

    if accepted:
        # Verify channels actually changed
        _, device2 = get_plex_dvr(plex_url, token)
        mapped2 = get_mapped_channel_numbers(device2)
        newly_mapped = mapped2 - mapped
        if newly_mapped:
            print(f"  Auto-sync successful — {len(newly_mapped)} channels added.")
            return
        # API accepted but nothing changed — fall through to manual
        print("  API accepted but channel count unchanged.")
    else:
        print("  Auto-sync not supported by this Plex version.")

    # ── Fall back to manual instructions ─────────────────────────────────────
    print("\nManual setup required to add the missing channels.")
    print_manual_instructions(tunarr_url)


if __name__ == "__main__":
    main()
