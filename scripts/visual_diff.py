#!/usr/bin/env python3
"""Visual regression of the mobile layer (plan 00 §9 risk "overlay breaks a desktop layout", plan 01 D2).

Serves two builds of the same site (BEFORE = MOBILE=0, AFTER = MOBILE=1) with scripts/serve_site.py
and, for every page:
  - desktop 1280×800: screenshot BEFORE vs AFTER with images blacked out (srcset may legitimately pick
    a WebP variant, so image content is not compared — their position and size are). Fails when more
    than --max-changed of the pixels differ by more than --tolerance (0–255).
  - mobile 360×740 (AFTER only): fails when document.documentElement.scrollWidth > 360
    (horizontal page scroll; innerWidth is not used, mobile Chrome widens it to fit the content).

  python3 scripts/visual_diff.py _site_before _site / /Climate/ /Shmitah
  … --pages-file pages.txt --out run/visual   (diff images for failures)
Exit 1 when any check fails.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
MOBILE_W = 360


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(root: Path):
    port = free_port()
    p = subprocess.Popen([sys.executable, str(HERE / "serve_site.py"), str(root), "--port", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p, f"http://127.0.0.1:{port}"


def changed_fraction(a: Path, b: Path, tolerance: int) -> tuple[float, tuple | None]:
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return 1.0, None
    diff = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > tolerance else 0)
    hist = diff.histogram()
    return hist[255] / (ia.width * ia.height), diff.getbbox()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--pages-file", type=Path)
    ap.add_argument("--tolerance", type=int, default=40)
    ap.add_argument("--max-changed", type=float, default=0.0005, help="fraction of pixels (0.0005 = 0.05 %%)")
    ap.add_argument("--out", type=Path, default=Path("run") / "visual")
    a = ap.parse_args()

    pages = list(a.pages)
    if a.pages_file:
        pages += [ln.strip() for ln in a.pages_file.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    if not pages:
        ap.error("no pages")
    a.out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    (pb, ub), (pa, ua) = serve(a.before), serve(a.after)
    time.sleep(0.8)
    failed = 0
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            desk = br.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
            mob = br.new_context(viewport={"width": MOBILE_W, "height": 740}, device_scale_factor=2, is_mobile=True, has_touch=True)
            dpage, mpage = desk.new_page(), mob.new_page()
            for url in pages:
                slug = url.strip("/").replace("/", "_") or "index"
                shots = []
                for name, base in (("before", ub), ("after", ua)):
                    dpage.goto(base + url, wait_until="networkidle")
                    # compare layout, not pixels inside images: srcset may legitimately pick a WebP variant
                    dpage.add_style_tag(content="img,video,picture{filter:brightness(0)!important}")
                    path = a.out / f"{slug}_desktop_{name}.png"
                    dpage.screenshot(path=path)
                    shots.append(path)
                frac, bbox = changed_fraction(*shots, a.tolerance)
                desk_ok = frac <= a.max_changed
                mpage.goto(ua + url, wait_until="networkidle")
                # compare with the device width: mobile Chrome widens innerWidth to fit overflowing content
                sw = mpage.evaluate("document.documentElement.scrollWidth")
                iw = MOBILE_W
                mob_ok = sw <= iw
                if not mob_ok:
                    mpage.screenshot(path=a.out / f"{slug}_mobile_after.png", full_page=False)
                if desk_ok:
                    for s in shots:
                        s.unlink()
                status = "OK  " if desk_ok and mob_ok else "FAIL"
                failed += not (desk_ok and mob_ok)
                print(f"{status} {url:28} desktop změna {frac * 100:6.3f} %{'' if desk_ok else f' bbox={bbox}'}"
                      f" | mobil scrollWidth {sw}/{iw}{'' if mob_ok else ' ← horizontální scroll'}")
            br.close()
    finally:
        pb.terminate()
        pa.terminate()
    print(f"\n{len(pages) - failed}/{len(pages)} stránek OK" + (f", detaily v {a.out}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
