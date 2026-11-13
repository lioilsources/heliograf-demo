#!/usr/bin/env python3
"""Frame index for viewer.js (plan §4.2 item 2, §5.2). Format: see header of shared/viewer.js.

Input: either a local directory or the listing `rclone lsjson -R --files-only r2:bucket/lasco > list.json`.
Frames: YYYY/MM/DD/YYYYMMDD_HHMM_<anything>_<size>.jpg, e.g. 2026/05/01/20260501_0030_c3_1024.jpg.
Variants of the same frame (_160/_512/_1024) are merged into one item "f" = path without _<size>.jpg.
A frame gets into the index only if ALL sizes from --sizes exist (incomplete upload is ignored).

Output to OUT: ranges.json + index/YYYY/MM.json. Writes only changed files (small diff in the commit).

  python3 gen_index.py --dir frames/lasco --out build/lasco --sizes 160,512,1024
  python3 gen_index.py --lsjson list.json --out build/lasco --sizes 160,512,1024 [--months 2]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FRAME = re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})_(?P<H>\d{2})(?P<M>\d{2})(?P<rest>.*)_(?P<size>\d+)\.jpg$")


def collect(paths, sizes):
    frames = defaultdict(set)   # stem-path → {sizes}
    meta = {}
    for rel in paths:
        name = rel.rsplit("/", 1)[-1]
        m = FRAME.match(name)
        if not m:
            continue
        stem = rel[: -len(f"_{m['size']}.jpg")]
        frames[stem].add(int(m["size"]))
        meta[stem] = f"{m['y']}-{m['m']}-{m['d']}T{m['H']}:{m['M']}"
    need = set(sizes)
    by_month = defaultdict(list)
    for stem, have in frames.items():
        if need <= have:
            t = meta[stem]
            by_month[t[:7]].append({"t": t, "f": stem})
    for items in by_month.values():
        items.sort(key=lambda x: (x["t"], x["f"]))
    return by_month


def write_if_changed(path: Path, obj) -> bool:
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    if path.exists() and path.read_text() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", type=Path)
    src.add_argument("--lsjson", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sizes", default="512,1024")
    ap.add_argument("--months", type=int, default=0, help="rewrite only the last N months (cron); 0 = all")
    a = ap.parse_args()

    sizes = [int(s) for s in a.sizes.split(",")]
    if a.dir:
        paths = [p.relative_to(a.dir).as_posix() for p in a.dir.rglob("*.jpg")]
    else:
        paths = [e["Path"] for e in json.loads(a.lsjson.read_text()) if not e.get("IsDir")]
    by_month = collect(paths, sizes)
    if not by_month:
        print("žádné snímky", file=sys.stderr)
        return 1

    months = sorted(by_month)
    todo = months[-a.months:] if a.months else months
    changed = sum(write_if_changed(a.out / "index" / f"{mo[:4]}/{mo[5:]}.json", {"month": mo, "items": by_month[mo]}) for mo in todo)
    first, last = by_month[months[0]][0]["t"], by_month[months[-1]][-1]["t"]
    changed += write_if_changed(a.out / "ranges.json", {"from": first, "to": last, "sizes": sizes, "months": months})
    total = sum(len(v) for v in by_month.values())
    print(f"snímků: {total}, měsíců: {len(months)} ({first} … {last}), změněných souborů: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
