#!/usr/bin/env python3
"""Preview build: root-relative links → page-relative, optional noindex.

A project site on GitHub Pages lives under a subpath (user.github.io/<repo>/), where `/Climate/`
points outside the site. This rewrites `/x` in href/src/srcset (HTML) and url() (CSS) to a path
relative to the page, so the build works under any prefix. `--noindex` adds
<meta name="robots" content="noindex"> so the preview never competes with the real domain in search.
Applied only to the build output (build_site.sh with PREVIEW=1), never to site/.

  python3 relativize.py _site [--noindex] [--exclude 'raw/*']
"""
from __future__ import annotations

import argparse
import fnmatch
import posixpath
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import CSS_URL as HTML_CSS_URL, URL_ATTR, iter_html, read_html, write_html  # noqa: E402

SRCSET = re.compile(r"""(?P<pre>(?<![\w-])srcset\s*=\s*)(?P<q>["'])(?P<val>[^"']*)(?P=q)""", re.IGNORECASE)
CSS_URL = re.compile(r"""url\(\s*(?P<q>["']?)(?P<url>/[^/)"'][^)"']*|/)(?P=q)\s*\)""")
HEAD = re.compile(r"<head[^>]*>", re.IGNORECASE)
NOINDEX = '<meta name="robots" content="noindex">'


def rel(url: str, page_rel: str) -> str:
    """'/a/b.html' seen from 'c/d.html' → '../a/b.html'. Non root-relative URLs are returned unchanged."""
    if not url.startswith("/") or url.startswith("//"):
        return url
    path, sep, rest = url.partition("#")
    path, qsep, query = path.partition("?")
    base = posixpath.dirname(page_rel) or "."
    target = path.lstrip("/") or "."
    out = posixpath.relpath(target, base)
    if path.endswith("/") and out != ".":
        out += "/"
    if out == ".":
        out = "./"
    return out + (qsep + query if qsep else "") + (sep + rest if sep else "")


def fix_html(text: str, page_rel: str, noindex: bool) -> tuple[str, int]:
    n = 0

    def attr(m):
        nonlocal n
        new = rel(m.group("url"), page_rel)
        if new == m.group("url"):
            return m.group(0)
        n += 1
        q = m.group("q") or ""
        return f'{m.group("pre")}{q}{new}{q}'

    def srcset(m):
        nonlocal n
        parts = []
        for cand in m.group("val").split(","):
            bits = cand.strip().split(None, 1)
            if bits:
                new = rel(bits[0], page_rel)
                n += new != bits[0]
                bits[0] = new
            parts.append(" ".join(bits))
        return f'{m.group("pre")}{m.group("q")}{", ".join(parts)}{m.group("q")}'

    def css(m):
        nonlocal n
        new = rel(m.group("url"), page_rel)
        n += new != m.group("url")
        return f'{m.group("pre")}{m.group("q")}{new}{m.group("q")}{m.group("post")}'

    text = URL_ATTR.sub(attr, text)
    text = SRCSET.sub(srcset, text)
    text = HTML_CSS_URL.sub(css, text)
    if noindex and 'name="robots"' not in text.lower():
        m = HEAD.search(text)
        text = text[:m.end()] + NOINDEX + text[m.end():] if m else NOINDEX + text
    return text, n


def fix_css(text: str, file_rel: str) -> tuple[str, int]:
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        return f'url({m.group("q")}{rel(m.group("url"), file_rel)}{m.group("q")})'

    return CSS_URL.sub(sub, text), n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--noindex", action="store_true")
    ap.add_argument("--exclude", action="append", default=[])
    a = ap.parse_args()

    pages = links = 0
    for p in iter_html(a.site):
        page_rel = p.relative_to(a.site).as_posix()
        if any(fnmatch.fnmatch(page_rel, g) for g in a.exclude):
            continue
        text, enc = read_html(p)
        new, n = fix_html(text, page_rel, a.noindex)
        if new != text:
            write_html(p, new, enc)
            pages += 1
            links += n
    for p in sorted(a.site.rglob("*.css")):
        file_rel = p.relative_to(a.site).as_posix()
        text = p.read_text(encoding="utf-8", errors="surrogateescape")
        new, n = fix_css(text, file_rel)
        if n:
            p.write_text(new, encoding="utf-8", errors="surrogateescape")
            links += n
    print(f"relativize: {links} odkazů v {pages} stránkách{', noindex' if a.noindex else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
