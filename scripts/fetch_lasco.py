#!/usr/bin/env python3
"""Downloads new LASCO C3 frames from NASA and prepares them for R2 (plan §4.2 item 3a, workflow frames.yml).

Source: https://soho.nascom.nasa.gov/data/REPROCESSING/Completed/YYYY/c3/YYYYMMDD/YYYYMMDD_HHMM_c3_1024.jpg
(same names as heliograf.org uses; NASA cadence is ~12 min, heliograf takes 1 frame / 3 h).
Selection: for each slot (--slots, default 00:30,03:30,…) the frame closest to the slot within --tolerance min.

Output: OUT/YYYY/MM/DD/<stem>_<size>.jpg for each size from --sizes (1024 = original unchanged).
Already existing files (locally or in the --have listing from `rclone lsjson`) are skipped → cron is cheap.

  python3 fetch_lasco.py --days 3 --out build/lasco [--have list.json] [--sizes 160,512,1024]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

BASE = "https://soho.nascom.nasa.gov/data/REPROCESSING/Completed"
UA = "pi-alpha-heliograf-mirror/1.0 (+https://heliograf.org/)"
NAME = re.compile(r'href="(\d{8}_(\d{2})(\d{2})_c3_1024\.jpg)"')


def get(url: str, tries: int = 3) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError("unreachable")


def pick(names: list[tuple[str, int]], slots: list[int], tol: int) -> list[str]:
    """names = [(file, minute of day)] → closest file to each slot."""
    out = []
    for s in slots:
        best = min(names, key=lambda n: abs(n[1] - s), default=None)
        if best and abs(best[1] - s) <= tol and best[0] not in out:
            out.append(best[0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=3, help="how many days back (NASA fills in with a delay)")
    ap.add_argument("--date", help="specific day YYYY-MM-DD (backfill), otherwise today UTC")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--have", type=Path, help="rclone lsjson -R bucket listing — what is already in R2")
    ap.add_argument("--sizes", default="160,512,1024")
    ap.add_argument("--slots", default="00:30,03:30,06:30,09:30,12:30,15:30,18:30,21:30")
    ap.add_argument("--tolerance", type=int, default=30, help="minutes")
    ap.add_argument("--prune", action="store_true", help="delete OUT/YYYY/MM/DD days older than the --days window")
    a = ap.parse_args()

    sizes = sorted(int(s) for s in a.sizes.split(","))
    slots = [int(h) * 60 + int(m) for h, m in (s.split(":") for s in a.slots.split(","))]
    have = {e["Path"] for e in json.loads(a.have.read_text())} if a.have and a.have.exists() else set()
    end = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(dt.timezone.utc).date()

    new = missing_days = 0
    for k in range(a.days):
        day = end - dt.timedelta(days=k)
        ymd = day.strftime("%Y%m%d")
        try:
            listing = get(f"{BASE}/{day.year}/c3/{ymd}/").decode("utf-8", "replace")
        except Exception as e:
            print(f"{day}: adresář zatím není ({e})")
            missing_days += 1
            continue
        names = [(m[1], int(m[2]) * 60 + int(m[3])) for m in NAME.finditer(listing)]
        for fname in pick(names, slots, a.tolerance):
            stem = fname[: -len("_1024.jpg")]
            rel_dir = f"{day.year}/{day.month:02d}/{day.day:02d}"
            targets = {s: f"{rel_dir}/{stem}_{s}.jpg" for s in sizes}
            if all(t in have or (a.out / t).exists() for t in targets.values()):
                continue
            raw = get(f"{BASE}/{day.year}/c3/{ymd}/{fname}")
            with Image.open(io.BytesIO(raw)) as im:
                im = im.convert("RGB")
                for s, rel in targets.items():
                    dst = a.out / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if s >= im.width:
                        dst.write_bytes(raw)          # original without recompression
                    else:
                        im.resize((s, round(im.height * s / im.width)), Image.LANCZOS).save(dst, "JPEG", quality=85, optimize=True)
            new += 1
            print(f"  + {stem}")
            time.sleep(0.5)
    print(f"nových snímků: {new}, dní bez dat: {missing_days}")
    if a.prune:
        print(f"smazáno starších dní: {prune(a.out, end - dt.timedelta(days=a.days - 1))}")
    return 0


def prune(out: Path, first: dt.date) -> int:
    """Removes day directories YYYY/MM/DD before `first` (rolling window for the Pages demo)."""
    n = 0
    for d in sorted(out.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]")):
        y, m, dd = (int(x) for x in d.relative_to(out).parts)
        if dt.date(y, m, dd) < first:
            shutil.rmtree(d)
            n += 1
    for d in sorted(out.glob("[0-9]*/[0-9]*"), reverse=True) + sorted(out.glob("[0-9]*")):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return n


if __name__ == "__main__":
    sys.exit(main())
