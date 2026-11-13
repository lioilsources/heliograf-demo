#!/usr/bin/env python3
"""Mobile layer — purely additive, reversible (plan §4.5 A–C).

What it does to each HTML page:
  - <meta name="viewport"> (when missing),
  - with --pwa-config: manifest link, theme-color, apple-touch-icon, shared/pwa.js (SW registration),
  - <link rel="stylesheet" href=…/mobile.css> and <link rel="preconnect"> to the assets domain,
  - <img>: loading="lazy" (except the first image on the page — LCP), decoding="async",
           width/height from the local file or the variants manifest (when both are missing),
           srcset/sizes from the variants manifest (img_variants.py), unless the image is blacklisted,
  - <video> without autoplay: preload="none",
  - <a> to a PDF/ZIP/video ≥ 5 MB (sizes from --file-sizes): data-mob-size="PDF, 12 MB", shown by mobile.css,
  - layout tables (all first-row cells have width in %) → data-mob-stack (stacked on mobile).
Pages with <meta name="mobile-layer" content="off"> (own mobile layout) get only the PWA tags.
Everything added is marked (data-mob / data-mob-add); `--undo` removes it and restores the page to its original state.
Page content and texts are not changed. File encoding is preserved.

  python3 mobilize.py site/ --css /shared/mobile.css --assets https://assets.pi-alpha.org \
      --variants build/variants.json --blacklist-file data/srcset-blacklist.txt [--apply | --undo]
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import json
import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import iter_html, read_globs, read_html, write_html  # noqa: E402

ATTR = re.compile(r"""([\w:-]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>"']+))?""")
IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
VIDEO = re.compile(r"<video\b[^>]*>", re.IGNORECASE)
ANCHOR = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
BIG_FILE = 5 * 1024 * 1024
SIZE_EXT = {".pdf", ".zip", ".7z", ".rar", ".gz", ".mp4", ".webm", ".mov", ".avi", ".mkv", ".mp3", ".wav",
            ".tif", ".tiff", ".ods", ".xlsx", ".docx", ".pptx", ".iso"}
TABLE = re.compile(r"<table\b[^>]*>", re.IGNORECASE)
LAYER_OFF = re.compile(r"""<meta\s+name=["']?mobile-layer["']?\s+content=["']?off""", re.IGNORECASE)
HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)
HEAD_START = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
MARK_TAG = re.compile(r"[ \t]*<(?:meta|link|script)\b[^>]*\bdata-mob\b[^>]*>(?:</script>)?\n?", re.IGNORECASE)
SIZES = "(max-width: 768px) 100vw, 800px"


def sizes_for(width: str) -> str:
    """sizes from the width the author gave the image: width=100% → 100vw, width=640 → 640px."""
    w = width.strip()
    if w.endswith("%") and w[:-1].isdigit():
        return f"(max-width: 768px) 100vw, {w[:-1]}vw"
    if w.isdigit():
        return f"(max-width: 768px) min(100vw, {w}px), {w}px"
    return SIZES


def attrs_of(tag: str) -> dict[str, str]:
    inner = re.sub(r"^<\w+|/?>$", "", tag)
    return {k.lower(): (v or "").strip("\"'") for k, v in ATTR.findall(inner)}


def add_attrs(tag: str, new: dict[str, str]) -> str:
    """Appends attributes to the end of the tag + records their names in data-mob-add (for --undo).
    The added block is contiguous and whitespace before `>`/`/>` is kept → undo restores a byte-identical tag."""
    if not new:
        return tag
    end = "/>" if tag.endswith("/>") else ">"
    body = tag[: -len(end)]
    stripped = body.rstrip()
    parts = " ".join(f'{k}="{v}"' for k, v in new.items())
    return f'{stripped} {parts} data-mob-add="{",".join(new)}"{body[len(stripped):]}{end}'


def undo_attrs(tag: str) -> str:
    m = re.search(r'data-mob-add="([^"]*)"', tag)
    if not m:
        return tag
    block = "".join(rf' {re.escape(k)}="[^"]*"' for k in m.group(1).split(",")) + r' data-mob-add="[^"]*"'
    return re.sub(block, "", tag, count=1)


def human(n: int) -> str:
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{round(n / 1024**2)} MB"


def load_sizes(path: Path | None) -> dict[str, int]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text())
    if isinstance(data, list):                       # rclone lsjson -R
        return {e["Path"]: e["Size"] for e in data if not e.get("IsDir")}
    return {k: int(v) for k, v in data.items()}


def image_size(path: Path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


class Mobilizer:
    def __init__(self, a):
        self.a = a
        self.variants = json.loads(a.variants.read_text()) if a.variants and a.variants.exists() else {}
        self.sizes = load_sizes(a.file_sizes)
        cfg = getattr(a, "pwa_config", None)
        self.pwa = json.loads(cfg.read_text()) if cfg and cfg.exists() else None
        self.stats = {"pages": 0, "viewport": 0, "css": 0, "img": 0, "srcset": 0, "dims": 0, "video": 0, "stack": 0,
                      "size": 0, "pwa": 0}

    def local_rel(self, url: str, page_rel: str) -> str | None:
        # URL on the assets base (absolute https://assets.… or root-relative /_assets) → manifest key
        prefix = self.a.assets.rstrip("/") + "/" if self.a.assets else None
        if prefix and url.startswith(prefix):
            return unquote(url[len(prefix):].split("?")[0])
        s = urlsplit(url)
        if s.scheme or s.netloc:
            return None
        path = unquote(s.path)
        if not path.startswith("/"):
            path = posixpath.join(posixpath.dirname("/" + page_rel), path)
        return posixpath.normpath(path).lstrip("/")

    def img(self, tag: str, page_rel: str, first: bool) -> str:
        at = attrs_of(tag)
        new: dict[str, str] = {}
        if "loading" not in at and not first:
            new["loading"] = "lazy"
        if "decoding" not in at:
            new["decoding"] = "async"
        rel = self.local_rel(at.get("src", ""), page_rel) if at.get("src") else None
        info = self.variants.get(rel) if rel else None
        blacklisted = rel and any(fnmatch.fnmatch(rel, g) for g in self.a.blacklist)
        if "width" not in at and "height" not in at and "style" not in at:
            wh = (info["w"], info["h"]) if info else (image_size(self.a.site / rel) if rel and (self.a.site / rel).is_file() else None)
            if wh:
                new["width"], new["height"] = str(wh[0]), str(wh[1])
                self.stats["dims"] += 1
        if info and not blacklisted and "srcset" not in at and info.get("variants"):
            cands = [f"{u} {w}w" for w, u in sorted(info["variants"].items(), key=lambda x: int(x[0]))]
            cands.append(f'{at["src"]} {info["w"]}w')   # original = largest candidate, desktop loses nothing
            new["srcset"] = ", ".join(cands)
            new["sizes"] = sizes_for(at.get("width", ""))
            self.stats["srcset"] += 1
        if new:
            self.stats["img"] += 1
        return add_attrs(tag, new)

    def stack_tables(self, text: str) -> str:
        def sub(m):
            tag = m.group(0)
            if "data-mob-stack" in tag:
                return tag
            row = re.search(r"<tr\b.*?(?:</tr>|<tr\b)", text[m.end(): m.end() + 4000], re.IGNORECASE | re.DOTALL)
            if not row:
                return tag
            tds = re.findall(r"<td\b[^>]*>", row.group(0), re.IGNORECASE)
            widths = [attrs_of(t).get("width", "") for t in tds]
            if len(tds) >= 2 and all(w.endswith("%") for w in widths) and "<th" not in row.group(0).lower():
                self.stats["stack"] += 1
                end = "/>" if tag.endswith("/>") else ">"
                return tag[: -len(end)] + " data-mob-stack" + end
            return tag
        return TABLE.sub(sub, text)

    def apply(self, text: str, page_rel: str) -> str:
        head_add = []
        if not re.search(r"<meta[^>]+name\s*=\s*[\"']?viewport", text, re.IGNORECASE):
            head_add.append('<meta name="viewport" content="width=device-width, initial-scale=1" data-mob>')
            self.stats["viewport"] += 1
        if self.a.assets.startswith(("https://", "http://")) and f'href="{self.a.assets}"' not in text:
            head_add.append(f'<link rel="preconnect" href="{self.a.assets}" crossorigin data-mob>')
        off = bool(LAYER_OFF.search(text))      # page has its own mobile layout (heliograf viewer): PWA only
        if self.a.css not in text and not off:
            head_add.append(f'<link rel="stylesheet" href="{self.a.css}" data-mob>')
            self.stats["css"] += 1
        if self.pwa and 'rel="manifest"' not in text:
            head_add += [
                '<link rel="manifest" href="/manifest.webmanifest" data-mob>',
                f'<meta name="theme-color" content="{html.escape(self.pwa.get("theme_color", "#ffffff"))}" data-mob>',
                '<link rel="apple-touch-icon" href="/shared/icons/icon-192.png" data-mob>',
                '<script src="/shared/pwa.js" defer data-mob></script>',
            ]
            self.stats["pwa"] += 1
        if head_add:
            block = "\n".join(head_add) + "\n"
            if HEAD_END.search(text):
                text = HEAD_END.sub(lambda m: block + m.group(0), text, count=1)
            elif m := HEAD_START.search(text):
                text = text[: m.end()] + "\n" + block + text[m.end():]
            else:
                text = block + text

        if off:
            return text
        n = [0]

        def img_sub(m):
            n[0] += 1
            return self.img(m.group(0), page_rel, first=n[0] == 1)

        text = IMG.sub(img_sub, text)

        def video_sub(m):
            at = attrs_of(m.group(0))
            if "preload" in at or "autoplay" in at:
                return m.group(0)
            self.stats["video"] += 1
            return add_attrs(m.group(0), {"preload": "none"})

        text = VIDEO.sub(video_sub, text)

        def anchor_sub(m):
            at = attrs_of(m.group(0))
            rel = self.local_rel(at.get("href", ""), page_rel) if at.get("href") else None
            size = self.sizes.get(rel) if rel else None
            if not size or size < BIG_FILE or "data-mob-size" in at or Path(rel).suffix.lower() not in SIZE_EXT:
                return m.group(0)
            self.stats["size"] += 1
            return add_attrs(m.group(0), {"data-mob-size": f"{Path(rel).suffix[1:].upper()}, {human(size)}"})

        text = ANCHOR.sub(anchor_sub, text)
        return self.stack_tables(text)

    @staticmethod
    def undo(text: str) -> str:
        text = MARK_TAG.sub("", text)
        text = re.sub(r"<(?:img|video|a)\b[^>]*>", lambda m: undo_attrs(m.group(0)), text, flags=re.IGNORECASE)
        return re.sub(r"(<table\b[^>]*?) data-mob-stack", r"\1", text, flags=re.IGNORECASE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--css", default="/shared/mobile.css")
    ap.add_argument("--assets", default="", help="https://assets.<domain> (preconnect + manifest keys)")
    ap.add_argument("--variants", type=Path, help="variants.json from img_variants.py")
    ap.add_argument("--file-sizes", type=Path,
                    help="asset sizes: {path: bytes} from split_assets.py --sizes, or `rclone lsjson -R` output")
    ap.add_argument("--blacklist", action="append", default=[], help="glob of images without srcset (maps, charts)")
    ap.add_argument("--blacklist-file", type=Path, help="file with --blacklist globs, one per line (missing = none)")
    ap.add_argument("--exclude", action="append", default=[], help="glob of pages that must not be changed")
    ap.add_argument("--pwa-config", type=Path, help="data/pwa.json: add manifest, theme-color, icon and pwa.js")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    a.site = a.site.resolve()
    a.blacklist += read_globs(a.blacklist_file)

    mob = Mobilizer(a)
    changed = 0
    for p in iter_html(a.site):
        rel = p.relative_to(a.site).as_posix()
        if any(fnmatch.fnmatch(rel, g) for g in a.exclude):
            continue
        text, enc = read_html(p)
        new = mob.undo(text) if a.undo else mob.apply(text, rel)
        mob.stats["pages"] += 1
        if new != text:
            changed += 1
            if a.apply or a.undo:
                write_html(p, new, enc)
    mode = "undo" if a.undo else ("apply" if a.apply else "dry-run")
    print(f"[{mode}] změněno stránek: {changed}/{mob.stats['pages']}")
    if not a.undo:
        print("  " + ", ".join(f"{k}={v}" for k, v in mob.stats.items() if k != "pages"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
