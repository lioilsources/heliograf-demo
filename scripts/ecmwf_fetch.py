#!/usr/bin/env python3
"""ECMWF maps for the static /Ecmwf (plan §4.1 item 9, workflow ecmwf.yml).

FOUND IN AUDIT: /Ecmwf is not a plain proxy. The server itself renders combined maps
(Mix_YYYYMMDD_HHMM_EU.jpg = perspective projection, 850 hPa temperature + wind + isobars) and individual fields
(…_0h_em_msl_global_0p5deg.jpg) from ECMWF open data. They cannot be reproduced without the client's source script.

Hence two modes:
  --source oldserver  TRANSITIONAL: downloads finished images from the running pi-alpha.org/Ecmwf (while the server lives)
  --source render     TARGET: calls the client's render script (--render-cmd), once we get it

Output: OUT/<YYYY>/<file>.jpg (→ R2) + LATEST (JSON for Ecmwf.html, committed to the repo):
  {"run":"2026-10-27T00:00","types":{"EU":[{"label":"Combined EU","file":"2026/Mix_20261027_0000_EU.jpg"}, …]}}

  python3 ecmwf_fetch.py --source oldserver --out build/ecmwf --latest site/data/ecmwf-latest.json --types EU
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OLD = "https://pi-alpha.org/Ecmwf"
UA = "Mozilla/5.0 (pi-alpha.org GitHub Pages migration)"
VIEW = re.compile(r'<a href="Ecmwf\?View=([^"&]+\.jpg)"[^>]*>([^<]+)</a>')
RUN = re.compile(r"(\d{8})_?(\d{4})")


PAUSE = 3.0   # s between requests; the old server blocked a crawler once (AUDIT_pi-alpha.md)
_last = 0.0


def get(url: str) -> bytes:
    global _last
    time.sleep(max(0.0, _last + PAUSE - time.monotonic()))
    _last = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def from_oldserver(types: list[str], out: Path) -> tuple[str | None, dict]:
    run, result = None, {}
    for t in types:
        page = get(f"{OLD}?Latest&Type={t}").decode("cp1250", "replace")
        items = []
        for fname, label in VIEW.findall(page):
            m = RUN.search(fname)
            if not m:
                continue
            run = run or f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]}T{m[2][:2]}:{m[2][2:]}"
            rel = f"{m[1][:4]}/{fname}"
            dst = out / rel
            if not dst.exists():
                data = get(f"{OLD}?File={fname}")
                if not data.startswith(b"\xff\xd8"):
                    print(f"  ! {fname}: není JPEG ({data[:60]!r})", file=sys.stderr)
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                print(f"  + {rel}")
            items.append({"label": html.unescape(label.strip()), "file": rel})
        result[t] = items
    return run, result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["oldserver", "render"], default="oldserver")
    ap.add_argument("--render-cmd", help="client's script; must print JSON in LATEST format to stdout")
    ap.add_argument("--types", default="EU,Am")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--latest", type=Path, required=True)
    a = ap.parse_args()

    if a.source == "render":
        if not a.render_cmd:
            ap.error("--source render vyžaduje --render-cmd (zdroj od klienta, viz AUDIT)")
        latest = json.loads(subprocess.run(a.render_cmd, shell=True, check=True, capture_output=True, text=True).stdout)
    else:
        run, types = from_oldserver(a.types.split(","), a.out)
        if not run or not any(types.values()):
            print("žádné obrázky — starý server nedostupný?", file=sys.stderr)
            return 1
        latest = {"run": run, "types": types}

    data = json.dumps(latest, ensure_ascii=False, indent=1) + "\n"
    if a.latest.exists() and a.latest.read_text() == data:
        print("beze změny")
        return 0
    a.latest.parent.mkdir(parents=True, exist_ok=True)
    a.latest.write_text(data)
    print(f"nový běh {latest['run']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
