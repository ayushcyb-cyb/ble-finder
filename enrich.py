"""
enrich.py - optional, on-demand GATT "Identify".

Passive scanning often yields no device name. When the user clicks Identify on
the selected target, we actively CONNECT to it once and read the standard
Device Information characteristics (name, manufacturer, model, firmware). This
is the main way to turn an anonymous blip into a named device.

It is best-effort: connecting can fail, time out, or briefly interrupt the
scan. All errors are swallowed into a status string shown in the UI.

NOTE: this path needs real Bluetooth hardware; it cannot be exercised in a
sandbox without an adapter.
"""
import asyncio

import scanner

# Standard GATT characteristic UUIDs (Device Information Service)
CHARS = {
    "name": "00002a00-0000-1000-8000-00805f9b34fb",         # Device Name
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "model": "00002a24-0000-1000-8000-00805f9b34fb",
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",
}
APPEARANCE_CHAR = "00002a01-0000-1000-8000-00805f9b34fb"    # Appearance (uint16)


async def _read(address):
    from bleak import BleakClient
    out = {}
    async with BleakClient(address, timeout=12) as client:
        for label, uuid in CHARS.items():
            try:
                val = await client.read_gatt_char(uuid)
                txt = val.decode("utf-8", "replace").strip("\x00").strip()
                if txt:
                    out[label] = txt
            except Exception:
                pass
        try:
            v = await client.read_gatt_char(APPEARANCE_CHAR)
            if len(v) >= 2:
                out["appearance"] = scanner.appearance_name(int.from_bytes(v[:2], "little"))
        except Exception:
            pass
    return out


def identify_blocking(address, store, index):
    """Run the connect+read in its own event loop; update the device in place."""
    dev = store.by_index(index)
    if not dev:
        return
    dev.model_info = "identifying..."
    try:
        info = asyncio.run(_read(address))
    except Exception as e:
        dev.model_info = f"identify failed: {type(e).__name__}"
        return
    if not info:
        dev.model_info = "connected, no info exposed"
        return
    parts = []
    if info.get("name"):
        if not dev.name:
            dev.name = info["name"]
        parts.append(info["name"])
    for k in ("manufacturer", "model", "firmware"):
        if info.get(k):
            parts.append(f"{k}: {info[k]}")
    if info.get("appearance"):
        dev.appearance = info["appearance"]
        parts.append(f"appearance: {info['appearance']}")
    dev.model_info = " | ".join(parts) or "connected"


async def _pair(address):
    """Connect and send a real BLE pairing/bonding request; also read identity."""
    from bleak import BleakClient
    out = {"paired": False, "note": "", "info": {}}
    async with BleakClient(address, timeout=15) as client:
        try:
            out["paired"] = bool(await client.pair())
        except NotImplementedError:
            # macOS/CoreBluetooth pairs implicitly when an encrypted value is read
            out["note"] = "OS pairs automatically on access (macOS)"
        except Exception as e:
            out["note"] = f"{type(e).__name__}: {e}"
        for label, uuid in CHARS.items():
            try:
                val = await client.read_gatt_char(uuid)
                txt = val.decode("utf-8", "replace").strip("\x00").strip()
                if txt:
                    out["info"][label] = txt
            except Exception:
                pass
    return out


def pair_blocking(address, store, index):
    """Connect + pair with the selected device; report the outcome in place."""
    dev = store.by_index(index)
    if not dev:
        return
    dev.pair_status = "pairing..."
    try:
        r = asyncio.run(_pair(address))
    except Exception as e:
        # Most common honest failures: device not connectable (beacon), not in
        # pairing mode, already bonded elsewhere, or out of range.
        dev.pair_status = f"could not pair: {type(e).__name__}"
        return
    name = r["info"].get("name")
    if name and not dev.name:
        dev.name = name
    if r["paired"]:
        dev.pair_status = "paired ✓" + (f" ({r['note']})" if r["note"] else "")
    elif r["note"]:
        dev.pair_status = r["note"]
    else:
        dev.pair_status = "connected but device did not accept pairing"
