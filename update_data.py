#!/usr/bin/env python3
"""
update_data.py - refresh the bundled reference databases from upstream.

Pulls the latest Bluetooth-SIG-derived company IDs and service UUIDs from
Nordic Semiconductor's bluetooth-numbers-database (BSD-3-Clause) into data/.
Run it occasionally to keep vendor/protocol names current:

    python3 update_data.py

Only data whose license permits redistribution is fetched here. See
data/SOURCES.md for provenance and licenses.
"""
import json
import os
import urllib.request

DATA = os.path.join(os.path.dirname(__file__), "data")
BASE = "https://raw.githubusercontent.com/NordicSemiconductor/bluetooth-numbers-database/master/v1"
SOURCES = {
    "company_ids.json": f"{BASE}/company_ids.json",
    "service_uuids.json": f"{BASE}/service_uuids.json",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ble-finder/update_data"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    os.makedirs(DATA, exist_ok=True)
    for name, url in SOURCES.items():
        try:
            raw = fetch(url)
            obj = json.loads(raw)                 # validate before writing
            with open(os.path.join(DATA, name), "wb") as f:
                f.write(raw)
            print(f"updated {name}: {len(obj)} entries")
        except Exception as e:
            print(f"FAILED {name}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
