#!/usr/bin/env python3
"""PWA files for a build (plan 02 A): manifest.webmanifest, sw.js, offline.html, icons.

  python3 scripts/pwa.py _site --config data/pwa.json [--icons data/icons] [--assets URL] [--build-id ID]
  python3 scripts/pwa.py _site --kill        # sw.js that unregisters itself (turning the PWA off)

data/pwa.json: {"name": "…", "short_name": "…", "lang": "cs", "theme_color": "#…", "background_color": "#…"}
Icons (icon-192.png, icon-512.png, icon-maskable-512.png from bin/make_icons.py) are copied to
shared/icons/. All URLs in the manifest are relative, so the site also works under a subpath.
The <head> tags are added by mobilize.py --pwa-config.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ICONS = ("icon-192.png", "icon-512.png", "icon-maskable-512.png")

KILL_SW = """/* sw.js — kill switch: unregisters the service worker and clears its caches (PWA=0). */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (n) { return Promise.all(n.map(function (k) { return caches.delete(k); })); })
    .then(function () { return self.registration.unregister(); })
    .then(function () { return self.clients.matchAll(); })
    .then(function (cs) { cs.forEach(function (c) { c.navigate(c.url); }); }));
});
"""

OFFLINE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}: offline</title>
<style>body{{font:17px/1.5 system-ui,sans-serif;margin:0;padding:24px;background:{bg};color:#222}}
h1{{font-size:1.4em}}a{{color:{theme}}}</style></head>
<body><h1>{name}</h1>
<p>Jste offline a tuto stránku zatím nemáte uloženou.</p>
<p>Stránky, které jste už otevřeli, fungují i bez připojení. Zkuste to znovu, až budete online.</p>
<p><a href="./">Zpět na úvod</a></p></body></html>
"""


def manifest(cfg: dict, icons: list[str]) -> dict:
    m = {
        "name": cfg["name"], "short_name": cfg.get("short_name", cfg["name"][:12]),
        "lang": cfg.get("lang", "cs"), "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": cfg.get("background_color", "#ffffff"), "theme_color": cfg.get("theme_color", "#ffffff"),
        "icons": [],
    }
    for name in icons:
        size = "192x192" if "192" in name else "512x512"
        m["icons"].append({"src": f"shared/icons/{name}", "sizes": size, "type": "image/png",
                           "purpose": "maskable" if "maskable" in name else "any"})
    return m


def origin(url: str) -> str:
    s = urlsplit(url or "")
    return f"{s.scheme}://{s.netloc}" if s.scheme in ("http", "https") and s.netloc else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--icons", type=Path)
    ap.add_argument("--assets", default="")
    ap.add_argument("--build-id", default="")
    ap.add_argument("--kill", action="store_true")
    a = ap.parse_args()

    if a.kill:
        (a.site / "sw.js").write_text(KILL_SW)
        print("pwa: vypnuto (sw.js se odregistruje)")
        return 0
    cfg = json.loads(a.config.read_text())
    icons = []
    if a.icons and a.icons.is_dir():
        (a.site / "shared" / "icons").mkdir(parents=True, exist_ok=True)
        for name in ICONS:
            if (a.icons / name).is_file():
                shutil.copy2(a.icons / name, a.site / "shared" / "icons" / name)
                icons.append(name)
    (a.site / "manifest.webmanifest").write_text(json.dumps(manifest(cfg, icons), ensure_ascii=False, indent=1))
    build = "".join(c for c in (a.build_id or str(int(time.time()))) if c.isalnum())[:16]
    sw = (HERE.parent / "shared" / "sw.js").read_text()
    (a.site / "sw.js").write_text(sw.replace("__BUILD_ID__", build).replace("__ASSETS_ORIGIN__", origin(a.assets)))
    esc = {k: html.escape(str(v)) for k, v in cfg.items()}
    (a.site / "offline.html").write_text(OFFLINE.format(
        lang=esc.get("lang", "cs"), name=esc["name"], bg=esc.get("background_color", "#fff"),
        theme=esc.get("theme_color", "#036")))
    print(f"pwa: manifest, sw.js (build {build}), offline.html, ikon {len(icons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
