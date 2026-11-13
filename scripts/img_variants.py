#!/usr/bin/env python3
"""Responsive image variants for srcset (plan §4.5 B.2). Pillow; libvips would be faster,
but Pillow is available in the ubuntu runner and locally without install — switch once the build gets slow.

foo.jpg → foo.w480.webp, foo.w960.webp, foo.w1920.webp (only smaller than the original, never upscale).
The original stays as fallback in src= and as the <a href> target (tap → full resolution).
Incremental: a variant is regenerated only when it is older than the source.

Output: variants.json  {"Climate/foo.jpg": {"w": 3000, "h": 2000,
                         "variants": {"480": "https://assets…/Climate/foo.w480.webp", …}}}

  python3 img_variants.py SRC_DIR --out OUT_DIR --base-url https://assets.pi-alpha.org \
      --manifest build/variants.json [--min-bytes 102400] [--widths 480,960,1920] [--blacklist-file data/srcset-blacklist.txt]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import read_globs  # noqa: E402

EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
Image.MAX_IMAGE_PIXELS = 400_000_000   # large maps (SRTM, BlueMarble)


def variant_name(rel: str, w: int) -> str:
    p = Path(rel)
    return (p.parent / f"{p.stem}.w{w}.webp").as_posix()


def process(job):
    src, out_dir, rel, widths, quality = job
    try:
        with Image.open(src) as im:
            if getattr(im, "is_animated", False):
                return rel, None, "animovaný — přeskočeno"
            im = ImageOps.exif_transpose(im)
            W, H = im.size
            made = []
            for w in widths:
                if w >= W:
                    continue
                dst = out_dir / variant_name(rel, w)
                made.append(w)
                if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                h = round(H * w / W)
                rgb = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
                rgb.resize((w, h), Image.LANCZOS).save(dst, "WEBP", quality=quality, method=5)
            return rel, {"w": W, "h": H, "made": made}, None
    except Exception as e:  # a corrupted file must not break the build
        return rel, None, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--min-bytes", type=int, default=100 * 1024)
    ap.add_argument("--widths", default="480,960,1920")
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--blacklist", action="append", default=[])
    ap.add_argument("--blacklist-file", type=Path, help="file with --blacklist globs, one per line (missing = none)")
    ap.add_argument("-j", "--jobs", type=int, default=None)
    a = ap.parse_args()

    a.blacklist += read_globs(a.blacklist_file)
    widths = sorted(int(w) for w in a.widths.split(","))
    base = a.base_url.rstrip("/")
    manifest = json.loads(a.manifest.read_text()) if a.manifest.exists() else {}
    jobs = []
    for p in sorted(a.src.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXT or (p.suffix == ".webp" and ".w" in p.stem):  # our own variants
            continue
        rel = p.relative_to(a.src).as_posix()
        if p.stat().st_size < a.min_bytes or any(fnmatch.fnmatch(rel, g) for g in a.blacklist):
            continue
        jobs.append((p, a.out, rel, widths, a.quality))

    errors = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        for rel, info, err in ex.map(process, jobs, chunksize=4):
            if err:
                errors += 1
                print(f"  ! {rel}: {err}", file=sys.stderr)
                continue
            manifest[rel] = {"w": info["w"], "h": info["h"],
                             "variants": {str(w): f"{base}/{quote(variant_name(rel, w))}" for w in info["made"]}}

    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    a.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"obrázků: {len(jobs)}, chyb: {errors}, manifest: {a.manifest} ({len(manifest)} položek)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
