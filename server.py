#!/usr/bin/env python3
"""
server.py - Find-BLE: live BLE scanner + radar + proximity "find" tool.

Passively scans BLE advertising packets and serves a local web app:
  - a radar map of nearby devices (distance from RSSI; angle illustrative),
  - a stable device list with duplicate-earbud grouping,
  - a "Find" panel to home in on one device (live meter, warmer/colder, and a
    Calibrate-at-1m button for an accurate per-device distance),
  - an Identify button that connects once to read the device's real name.

READ-ONLY scanning; nothing is transmitted except the optional Identify
connect you trigger yourself.

Usage:
    python3 server.py                 # real scan, open browser
    python3 server.py --demo          # synthetic devices, no Bluetooth
    python3 server.py --port 8500 --range 15 --smooth 0.2

Requires: pip install bleak   (not needed for --demo)
"""
import argparse
import json
import os
import random
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import scanner
import enrich

STATIC = os.path.join(os.path.dirname(__file__), "static")
STORE: scanner.Store = None
STALE = 10.0
CTYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
          ".css": "text/css", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        ext = os.path.splitext(path)[1]
        self.send_response(200)
        self.send_header("Content-Type", CTYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/":
            return self._file("index.html")
        if p == "/api/devices":
            q = parse_qs(u.query)
            group = q.get("group", ["1"])[0] != "0"
            return self._json(STORE.snapshot(STALE, group))
        if p.startswith("/api/device/"):
            try:
                idx = int(p.rsplit("/", 1)[1])
            except ValueError:
                return self._json({"error": "bad index"}, 400)
            d = STORE.detail(idx, STALE)
            return self._json(d or {"error": "not found"}, 200 if d else 404)
        return self._file(p.lstrip("/"))

    def do_POST(self):
        p = urlparse(self.path).path
        if p.startswith("/api/calibrate/"):
            idx = int(p.rsplit("/", 1)[1])
            return self._json({"ok": STORE.set_cal(idx)})
        if p.startswith("/api/identify/"):
            idx = int(p.rsplit("/", 1)[1])
            d = STORE.by_index(idx)
            if not d:
                return self._json({"ok": False, "error": "not found"}, 404)
            threading.Thread(target=enrich.identify_blocking,
                             args=(d.address, STORE, idx), daemon=True).start()
            return self._json({"ok": True, "status": "identifying"})
        if p.startswith("/api/pair/"):
            idx = int(p.rsplit("/", 1)[1])
            d = STORE.by_index(idx)
            if not d:
                return self._json({"ok": False, "error": "not found"}, 404)
            threading.Thread(target=enrich.pair_blocking,
                             args=(d.address, STORE, idx), daemon=True).start()
            return self._json({"ok": True, "status": "pairing"})
        if p.startswith("/api/label/"):
            idx = int(p.rsplit("/", 1)[1])
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            name = str(body.get("name", "")).strip()[:64]
            return self._json({"ok": STORE.set_label(idx, name)})
        self.send_error(404)


def start_server(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --- scan sources -------------------------------------------------------------

def scan_real():
    import asyncio
    from bleak import BleakScanner

    def cb(device, adv):
        STORE.update(device.address or scanner.NO_ADDRESS, adv.rssi,
                     adv.local_name or "", adv.manufacturer_data,
                     adv.service_uuids, adv.service_data, adv.tx_power)

    async def run():
        s = BleakScanner(detection_callback=cb)
        try:
            await s.start()
        except Exception as e:
            print(f"\nCould not start Bluetooth scanner: {type(e).__name__}: {e}")
            print("  - Bluetooth ON? Linux: BlueZ running + scan permission.")
            print("  - No adapter? Try:  python3 server.py --demo")
            return
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await s.stop()

    asyncio.run(run())


def scan_demo():
    FP = "0000fe2c-0000-1000-8000-00805f9b34fb"
    # (address, name, mfg, service_uuids, service_data) - addresses chosen so
    # address-type classification is meaningful (public vs random subtypes).
    seed = [
        ("3c:5a:b4:10:00:01", "Galaxy Buds4", {0x0075: b"\x01\x00\x02"}, [], {}),
        ("3c:5a:b4:10:00:02", "Galaxy Buds4 LE", {0x0075: b"\x01\x00\x02"}, [], {}),
        ("3c:5a:b4:10:00:03", "Galaxy Buds4", {0x0075: b"\x01\x00\x02"}, [], {}),
        ("6e:11:22:33:44:01", "", {0x004C: b"\x12\x02\xaa\xbb"}, [], {}),            # Apple Find My, resolvable-private
        ("6e:11:22:33:44:02", "", {0x004C: b"\x10\x05\x00\x00\x00\x00\x00"}, [], {}),
        ("d8:0d:17:00:00:01", "Pixel Buds Pro", {}, [FP], {FP: b"\x2a\xbb\xcc"}),    # Fast Pair model
        ("d8:0d:17:00:00:02", "", {0x0006: b"\x01\x00"}, [], {}),                    # MS Swift Pair
        ("fc:fb:fb:00:00:01", "RuuviTag", {0x0499: b"\x05\x00"}, [], {}),
        ("c3:aa:bb:cc:dd:01", "MI Band 8", {0x0157: b"\x00"},
         ["0000fe95-0000-1000-8000-00805f9b34fb"], {}),                             # random-static
        ("fc:fb:fb:00:00:02", "JBL Flip 6", {0x0057: b"\x00"}, [], {}),
        ("fc:fb:fb:00:00:03", "Tile Mate", {}, ["0000feed-0000-1000-8000-00805f9b34fb"], {}),
    ]
    # genuinely-unknown devices: random addresses, unlisted company IDs, no name
    # -> exercises the fallback (address-type, fingerprint, "label this").
    extra = []
    for _ in range(9):
        first = random.choice([0x6e, 0x7a, 0xc3, 0xd6])
        mac = "%02x:%02x:%02x:%02x:%02x:%02x" % (first, *[random.randint(0, 255) for _ in range(5)])
        cid = random.choice([0xFFF0, 0xFFFE, 0xFEED0 & 0xFFFF])
        extra.append((mac, "", {cid: bytes(random.randint(0, 255) for _ in range(4))}, [], {}))
    pool = seed + extra
    base = {a: random.randint(-90, -35) for a, *_ in pool}
    print(f"DEMO mode: {len(pool)} synthetic devices. (No real Bluetooth used.)")
    try:
        while True:
            for a, name, mfg, svc, sd in pool:
                base[a] = max(-98, min(-20, base[a] + random.randint(-3, 3)))
                STORE.update(a, base[a], name, mfg, svc, sd, None)
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main():
    global STORE, STALE
    ap = argparse.ArgumentParser(description="Find-BLE scanner + radar + finder")
    ap.add_argument("--port", type=int, default=8500)
    ap.add_argument("--stale", type=float, default=10.0)
    ap.add_argument("--range", type=float, default=12.0)
    ap.add_argument("--tx", type=float, default=-59.0, help="expected RSSI at 1 m")
    ap.add_argument("--n", type=float, default=2.5, help="path-loss exponent")
    ap.add_argument("--smooth", type=float, default=0.2, help="RSSI smoothing 0.05..1")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    STALE = args.stale
    STORE = scanner.Store(smooth=args.smooth, tx=args.tx, n=args.n)
    # expose config to the page
    with open(os.path.join(STATIC, "config.json"), "w") as f:
        json.dump({"range": args.range, "tx": args.tx, "n": args.n}, f)

    start_server(args.port)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Find-BLE at {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    scan_demo() if args.demo else scan_real()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
