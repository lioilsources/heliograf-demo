#!/usr/bin/env python3
"""Rewrites href/src to assets moved to R2 according to assets-map.json. Plan §4.1 item 4.

Idempotent: already absolute https://assets.… URLs are not changed. File encoding is preserved.
Handles relative (`../Sun/x.mp4`), root (`/Climate/a.zip`) and absolute links to our own domain.

  python3 rewrite_links.py site/ --map build/assets-map.json --domain pi-alpha.org [--apply]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import posixpath
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import CSS_URL, URL_ATTR, iter_html, read_html, write_html  # noqa: E402


def resolve(url: str, page_rel: str, domains: set[str]) -> tuple[str, str] | None:
    """→ (path within the site without leading /, fragment) or None for foreign/unsuitable URLs."""
    if not url or url.startswith(("#", "mailto:", "javascript:", "data:", "tel:")):
        return None
    s = urlsplit(url)
    if s.scheme and s.scheme not in ("http", "https"):
        return None
    if s.netloc and s.netloc.lower().removeprefix("www.") not in domains:
        return None
    if s.query:            # ?raw, ?View=… → dynamic, not an asset
        return None
    path = unquote(s.path)
    if not path.startswith("/"):
        path = posixpath.join(posixpath.dirname("/" + page_rel), path)
    path = posixpath.normpath(path).lstrip("/")
    return path, s.fragment


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--domain", action="append", required=True, help="own domain (repeatable)")
    ap.add_argument("--exclude", action="append", default=[], help="glob of pages to leave untouched (raw/*)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    mapping: dict[str, str] = json.loads(a.map.read_text())
    domains = {d.lower().removeprefix("www.") for d in a.domain}
    files = links = 0
    missing: dict[str, int] = {}

    for p in iter_html(a.site):
        page_rel = p.relative_to(a.site).as_posix()
        if any(fnmatch.fnmatch(page_rel, g) for g in a.exclude):
            continue
        text, enc = read_html(p)
        count = 0

        def sub(m):
            nonlocal count
            r = resolve(m.group("url").strip(), page_rel, domains)
            if not r:
                return m.group(0)
            path, frag = r
            new = mapping.get(path)
            if not new:
                if not (a.site / path).exists() and Path(path).suffix:
                    missing[path] = missing.get(path, 0) + 1
                return m.group(0)
            count += 1
            post = m.groupdict().get("post")
            q = m.group("q") or ("" if post is not None else '"')
            return f'{m.group("pre")}{q}{new}{"#" + frag if frag else ""}{q}{post or ""}'

        new_text = CSS_URL.sub(sub, URL_ATTR.sub(sub, text))
        if count:
            files += 1
            links += count
            print(f"{page_rel}: {count} odkazů")
            if a.apply:
                write_html(p, new_text, enc)

    print(f"\n{'přepsáno' if a.apply else 'k přepsání (dry-run)'}: {links} odkazů v {files} souborech")
    if missing:
        print(f"\nOdkazy na neexistující soubory (ani v repu, ani v mapě): {len(missing)}")
        for path, n in sorted(missing.items(), key=lambda x: -x[1])[:30]:
            print(f"  {n:4d}× {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
