#!/usr/bin/env python3
"""Splits the site mirror into a repo part (site/) and an asset part (assets/ → R2). Plan §4.1 item 2.

A file goes to assets when:
  - it has a "heavy" extension (zip, pdf, mp4, …) and is also > --min-heavy (default 0 = always), or
  - it is larger than --threshold (default 1 MB), or
  - --force-glob lists it.
HTML/CSS/JS always stay in the repo, and so does anything matching --keep-glob: files whose URL is built
in JavaScript (pi-alpha `cz/Volby2025/*` builds `file+'.svg'`, `Sc26/Video/*`) cannot be rewritten to R2.

Output: assets-map.json  {"Climate/foo.zip": "https://assets.pi-alpha.org/Climate/foo.zip", ...}
Without --apply only prints the plan (dry-run). With --apply MOVES files from <src> to <assets>.

  python3 split_assets.py mirror/pi-alpha.org --assets build/assets \
      --base-url https://assets.pi-alpha.org --map build/assets-map.json [--apply]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

KEEP_EXT = {".html", ".htm", ".css", ".js", ".json", ".txt", ".xml", ".svg", ".ico", ".cer", ".p7s", ".tsr"}
HEAVY_EXT = {".zip", ".7z", ".rar", ".gz", ".tgz", ".pdf", ".mp4", ".webm", ".mov", ".avi", ".mkv",
             ".mp3", ".wav", ".ogg", ".tif", ".tiff", ".nc", ".grib", ".grib2", ".iso", ".exe"}


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def classify(rel: str, size: int, a) -> str | None:
    ext = Path(rel).suffix.lower()
    if any(fnmatch.fnmatch(rel, g) for g in a.keep_glob):
        return None
    if any(fnmatch.fnmatch(rel, g) for g in a.force_glob):
        return "forced"
    if ext in KEEP_EXT or ext == "":
        return None
    if ext in HEAVY_EXT and size >= a.min_heavy:
        return "heavy-ext"
    if size > a.threshold:
        return "size"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--threshold", type=int, default=1024 * 1024)
    ap.add_argument("--min-heavy", type=int, default=0)
    ap.add_argument("--force-glob", action="append", default=[])
    ap.add_argument("--keep-glob", action="append", default=[], help="stays in the repo (URL built in JS)")
    ap.add_argument("--sizes", type=Path, help="write {path: bytes} of moved files (for mobilize --file-sizes)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    base = a.base_url.rstrip("/")
    mapping = json.loads(a.map.read_text()) if a.map.exists() else {}
    stats, sizes, repo_bytes = Counter(), Counter(), 0
    moves = []
    sizes_out = json.loads(a.sizes.read_text()) if a.sizes and a.sizes.exists() else {}
    for p in sorted(a.src.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(a.src).as_posix()
        size = p.stat().st_size
        why = classify(rel, size, a)
        if why is None:
            repo_bytes += size
            continue
        stats[why] += 1
        sizes[why] += size
        mapping[rel] = f"{base}/{quote(rel)}"
        sizes_out[rel] = size
        moves.append((p, a.assets / rel))

    print(f"repo zůstává: {human(repo_bytes)}")
    for why in stats:
        print(f"→ R2 ({why}): {stats[why]} souborů, {human(sizes[why])}")
    if repo_bytes > 900 * 1024**2:
        print("VAROVÁNÍ: repo-část > 900 MB, Pages limit je 1 GB — snížit --threshold", file=sys.stderr)

    if a.apply:
        for src, dst in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
        a.map.parent.mkdir(parents=True, exist_ok=True)
        a.map.write_text(json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
        if a.sizes:
            a.sizes.write_text(json.dumps(sizes_out, ensure_ascii=False, indent=1, sort_keys=True))
        print(f"přesunuto {len(moves)}, mapa: {a.map}")
    else:
        for src, _ in moves[:20]:
            print("  ", src.relative_to(a.src))
        if len(moves) > 20:
            print(f"   … a dalších {len(moves) - 20}  (dry-run, --apply provede)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
