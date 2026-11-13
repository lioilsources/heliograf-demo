#!/usr/bin/env python3
"""Give extensionless HTML pages a .html suffix (plan §4.1 item 5).

The old server maps /Editor → Editor.html; wget saved such pages without a suffix. GitHub Pages
serves an extensionless file as application/octet-stream (download), but resolves /Editor to
Editor.html on its own — so renaming keeps every old URL working.

  - Foo (HTML) → Foo.html
  - Foo and Foo.html both exist and are identical → Foo is removed
  - they differ, or a directory Foo/ exists → left alone and reported (decide by hand)
Only files recognised as HTML by content are touched. Without --apply only prints the plan.

  python3 add_html_ext.py site/ [--apply] [--skip-glob 'Duka/Blog/www.facebook.com*']
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import has_real_ext, is_html  # noqa: E402


def plan(site: Path, skip: list[str]):
    rename, dedupe, conflict = [], [], []
    for p in sorted(site.rglob("*")):
        rel = p.relative_to(site).as_posix()
        if any(part.startswith(".") for part in p.relative_to(site).parts) or any(fnmatch.fnmatch(rel, g) for g in skip):
            continue
        if has_real_ext(p) or not p.is_file() or not is_html(p):
            continue
        target = p.with_name(p.name + ".html")
        if target.exists():
            (dedupe if target.read_bytes() == p.read_bytes() else conflict).append(rel)
        else:
            rename.append(rel)
    return rename, dedupe, conflict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-glob", action="append", default=[], help="paths to leave alone (crawler traps)")
    a = ap.parse_args()

    rename, dedupe, conflict = plan(a.site, a.skip_glob)
    if a.apply:
        for rel in rename:
            (a.site / rel).rename(a.site / (rel + ".html"))
        for rel in dedupe:
            (a.site / rel).unlink()
    mode = "provedeno" if a.apply else "dry-run"
    print(f"[{mode}] přejmenovat → .html: {len(rename)}, smazat shodné duplicity: {len(dedupe)}, konflikty: {len(conflict)}")
    for rel in conflict:
        print(f"  ! {rel} a {rel}.html se liší — rozhodnout ručně")
    return 1 if conflict and a.apply else 0


if __name__ == "__main__":
    sys.exit(main())
