"""
scanner.py - core BLE decoding + device store for the Find-BLE project.

Pure logic, no I/O or Bluetooth here (see server.py for the scan loop and
enrich.py for optional GATT identify). Everything is READ-ONLY analysis of
advertising packets, plus a per-device RSSI history used for the "find"
proximity meter.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# --- Reference databases (bundled from Nordic's bluetooth-numbers-database) ---


def _load_company_ids():
    try:
        with open(os.path.join(DATA_DIR, "company_ids.json"), encoding="utf-8") as f:
            return {e["code"]: e["name"] for e in json.load(f)}
    except Exception:
        return {}


def _load_service_uuids():
    out = {}
    try:
        with open(os.path.join(DATA_DIR, "service_uuids.json"), encoding="utf-8") as f:
            for e in json.load(f):
                out[e["uuid"].lower()] = e["name"]
    except Exception:
        pass
    # A few well-known member UUIDs the generic DB labels blandly or omits.
    out.update({
        "fe2c": "Google Fast Pair", "feaa": "Eddystone", "feed": "Tile",
        "fd6f": "Exposure Notification", "fe95": "Xiaomi MiBeacon",
        "fe59": "Nordic DFU (update mode)", "fe0f": "Philips Hue",
        "180f": "Battery Service", "180a": "Device Information",
    })
    return out


COMPANY_IDS = _load_company_ids()
SERVICE_UUIDS = _load_service_uuids()

APPLE_CONTINUITY_TYPES = {
    0x02: "iBeacon", 0x05: "AirDrop", 0x06: "HomeKit", 0x07: "Proximity Pairing",
    0x08: "Hey Siri", 0x09: "AirPlay target", 0x0A: "AirPlay source",
    0x0C: "Handoff", 0x0D: "Tethering target", 0x0E: "Tethering source",
    0x0F: "Nearby Action", 0x10: "Nearby Info", 0x12: "Find My",
}
APPLE_ACTIVE_TYPES = {0x05, 0x07, 0x0C, 0x0F, 0x09, 0x0A, 0x0D, 0x0E}

# Short, friendly labels for the most common makers (the full DB resolves the
# rest to their official names; these just read nicer in a narrow column).
VENDOR_SHORT = {
    0x004C: "Apple", 0x0006: "Microsoft", 0x00E0: "Google", 0x018E: "Google",
    0x0075: "Samsung", 0x012D: "Sony", 0x009E: "Bose", 0x00CC: "Beats",
    0x01DA: "Logitech", 0x0067: "Jabra", 0x07C9: "Skullcandy", 0x0CAC: "Shokz",
    0x0CC2: "Anker", 0x05A7: "Sonos", 0x0087: "Garmin", 0x0157: "Huami/Zepp",
    0x038F: "Xiaomi", 0x0171: "Amazon", 0x067C: "Tile", 0x0499: "Ruuvi",
    0x05D6: "Jieli audio", 0x0059: "Nordic",
}

NO_ADDRESS = "unauthorised"
HISTORY_LEN = 150  # ~a couple minutes of samples for the find meter


def company_name(cid: int) -> str:
    return VENDOR_SHORT.get(cid) or COMPANY_IDS.get(cid) or f"0x{cid:04X}"


def short_uuid(uuid: str) -> str:
    p = uuid.lower().split("-")
    return p[0][4:] if len(p) == 5 and p[0].startswith("0000") else uuid.lower()


def service_name(uuid: str) -> str:
    su = short_uuid(uuid)
    return SERVICE_UUIDS.get(su, su)


def decode_apple(payload: bytes):
    seen, labels, i = [], [], 0
    while i + 1 < len(payload):
        t, ln = payload[i], payload[i + 1]
        seen.append(t)
        labels.append(APPLE_CONTINUITY_TYPES.get(t, f"0x{t:02X}"))
        i += 2 + ln
    if not labels:
        return "Apple", False
    passive = not any(t in APPLE_ACTIVE_TYPES for t in seen)
    return ", ".join(labels), passive


def angle_for(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % 360


def _norm_name(name: str) -> str:
    """Normalize a device name for grouping duplicate earbud advertisers."""
    s = name.lower()
    for junk in (" le", "-le", " ble", "-ble", "(le)", " le audio", "_le"):
        s = s.replace(junk, "")
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


@dataclass
class Device:
    index: int
    address: str
    angle: int = 0
    name: str = ""
    vendor: str = ""
    company_id: Optional[int] = None
    kind: str = ""
    services: list = field(default_factory=list)   # decoded service names
    mfg_hex: str = ""
    tx_power: Optional[int] = None
    rssi: float = -100.0          # smoothed
    rssi_raw: int = -100
    passive_hint: bool = False
    cal_tx: Optional[float] = None  # per-device 1 m reference, set by Calibrate
    model_info: str = ""           # filled by GATT Identify
    pair_status: str = ""          # filled by Pair
    first: datetime = field(default_factory=datetime.now)
    last: datetime = field(default_factory=datetime.now)
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))


class Store:
    def __init__(self, smooth=0.2, tx=-59.0, n=2.5):
        self.devices: dict[str, Device] = {}
        self.order: list[str] = []
        self.lock = threading.Lock()
        self.smooth, self.tx, self.n = smooth, tx, n

    # -- ingest -------------------------------------------------------------
    def update(self, address, rssi, name="", mfg=None, service_uuids=None,
               service_data=None, tx_power=None):
        mfg = mfg or {}
        service_uuids = service_uuids or []
        with self.lock:
            d = self.devices.get(address)
            created = d is None
            if created:
                idx = len(self.order) + 1
                d = Device(index=idx, address=address,
                           angle=angle_for(f"{address}:{idx}"))
                self.devices[address] = d
                self.order.append(address)

            d.rssi_raw = rssi
            d.rssi = rssi if created else self.smooth * rssi + (1 - self.smooth) * d.rssi
            d.last = datetime.now()
            d.history.append((time.time(), rssi))
            if tx_power is not None:
                d.tx_power = tx_power
            if name:
                d.name = name

            vendor, kind, passive, cid, mhex = "", "", False, None, ""
            for c, data in mfg.items():
                cid, mhex = c, bytes(data).hex()
                vendor = company_name(c)
                if c == 0x004C:
                    kind, passive = decode_apple(bytes(data))
                elif c == 0x0075:
                    kind = "Samsung proximity"
                elif c == 0x0006:
                    kind = "Microsoft Swift Pair"
                break
            svc = [service_name(u) for u in service_uuids]
            for u in service_uuids:
                su = short_uuid(u)
                if su in ("fe2c", "feaa", "feed") and not vendor:
                    vendor = {"feed": "Tile"}.get(su, "Google")
            if vendor:
                d.vendor, d.company_id, d.mfg_hex = vendor, cid, mhex
            if kind:
                d.kind = kind
            if svc:
                d.services = svc
            d.passive_hint = passive

    # -- distance / state ---------------------------------------------------
    def distance(self, d: Device) -> float:
        tx = d.cal_tx if d.cal_tx is not None else self.tx
        return 10 ** ((tx - d.rssi) / (10 * self.n))

    def _state(self, d: Device, stale_after: float) -> str:
        age = (datetime.now() - d.last).total_seconds()
        if age > stale_after:
            return "STALE"
        return "PASSIVE" if d.passive_hint else "ACTIVE"

    def _row(self, d: Device, stale_after: float) -> dict:
        return {
            "index": d.index, "address": d.address, "angle": d.angle,
            "name": d.name, "vendor": d.vendor, "decoded": d.kind,
            "rssi": round(d.rssi), "dist": round(self.distance(d), 2),
            "state": self._state(d, stale_after),
            "seen": int((datetime.now() - d.last).total_seconds()),
            "calibrated": d.cal_tx is not None,
            "services": d.services[:4],
        }

    # -- queries ------------------------------------------------------------
    def snapshot(self, stale_after=10.0, group=True) -> dict:
        with self.lock:
            rows = [self._row(d, stale_after) for d in self.devices.values()]
        total = len(rows)
        if group:
            rows = self._group(rows)
        return {"devices": rows, "total": total, "groups": len(rows)}

    def _group(self, rows):
        """Collapse same-named advertisers (e.g. L/R/case of one earbud set)."""
        buckets: dict[str, dict] = {}
        singles = []
        for r in rows:
            key = _norm_name(r["name"]) if r["name"] else None
            if not key:
                singles.append(r)
                continue
            b = buckets.get(key)
            if b is None or r["rssi"] > b["rssi"]:  # keep nearest as the face
                merged_count = (b["group_count"] if b else 0) + 1
                r = dict(r, group_count=merged_count)
                buckets[key] = r
            else:
                b["group_count"] += 1
        return sorted([*buckets.values(), *singles], key=lambda x: x["index"])

    def detail(self, index: int, stale_after=10.0) -> Optional[dict]:
        with self.lock:
            d = next((x for x in self.devices.values() if x.index == index), None)
            if not d:
                return None
            row = self._row(d, stale_after)
            hist = list(d.history)
        now = time.time()
        series = [{"t": round(now - t, 1), "rssi": r} for t, r in hist][-60:]
        row.update({
            "company_id": d.company_id, "mfg_hex": d.mfg_hex,
            "tx_power": d.tx_power, "model_info": d.model_info,
            "pair_status": d.pair_status,
            "services_all": d.services, "trend": self._trend(hist),
            "history": series, "cal_tx": d.cal_tx,
        })
        return row

    def _trend(self, hist):
        """Warmer/colder: compare recent vs older RSSI average."""
        if len(hist) < 6:
            return 0
        recent = [r for _, r in hist[-5:]]
        older = [r for _, r in hist[-12:-5]] or recent
        return round(sum(recent) / len(recent) - sum(older) / len(older), 1)

    def set_cal(self, index: int) -> bool:
        with self.lock:
            d = next((x for x in self.devices.values() if x.index == index), None)
            if not d:
                return False
            d.cal_tx = d.rssi  # current smoothed RSSI becomes the 1 m reference
            return True

    def by_index(self, index: int) -> Optional[Device]:
        with self.lock:
            return next((x for x in self.devices.values() if x.index == index), None)
