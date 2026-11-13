#!/usr/bin/env python3
"""cp1250 → UTF-8 with round-trip validation, per file. Plan §4.1 item 3, risk §9.

For each HTML file declared as windows-1250:
  1. strict cp1250 decoding (no replacement characters),
  2. round-trip: text.encode(cp1250) == original bytes,
  3. check that the file has no UTF-8 sequences accidentally saved into a cp1250 file (mojibake "Ä›", "Å¡"),
  4. rewrite <meta charset> / http-equiv to UTF-8.
A file that fails is NOT CONVERTED and is listed. It must be fixed by hand before deploy:
GitHub Pages sends `Content-Type: text/html; charset=utf-8`, which overrides <meta charset>
(verified 2026-11-12), so leaving cp1250 is not an option on Pages.

--keep-originals DIR copies the original bytes of every converted file to DIR/<same path>
(signed originals, plan §4.1 item 6: published as /raw/…).

Separate PR — never in the same commit as mobilize.py (plan §4.5 E).

  python3 convert_charset.py site/ [--apply] [--report build/charset-report.json] [--keep-originals site/raw]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from htmlio import detect_charset, iter_html  # noqa: E402

META_HTTP_EQUIV = re.compile(r"""<meta\s+http-equiv\s*=\s*["']?content-type["']?[^>]*>""", re.IGNORECASE)
META_CHARSET = re.compile(r"""<meta\s+charset\s*=\s*["']?[\w-]+["']?\s*/?>""", re.IGNORECASE)
# UTF-8 bytes decoded as cp1250: lead byte C3–C5 ("Ă","Ä","Ĺ") + continuation 0x80–0xBF
_CONT = re.escape(bytes(range(0x80, 0xC0)).decode("cp1250", errors="ignore"))
MOJIBAKE = re.compile(f"[ĂÄĹ][{_CONT}]")


def convert(raw: bytes) -> tuple[str | None, str]:
    try:
        text = raw.decode("cp1250", errors="strict")
    except UnicodeDecodeError as e:
        return None, f"nedekódovatelné bajty na pozici {e.start}"
    if text.encode("cp1250") != raw:
        return None, "round-trip nesouhlasí"
    if m := MOJIBAKE.search(text):
        return None, f"podezření na UTF-8 uvnitř cp1250: {text[max(0, m.start() - 20):m.end() + 20]!r}"
    new = META_HTTP_EQUIV.sub('<meta http-equiv="Content-Type" content="text/html; charset=utf-8">', text)
    if META_CHARSET.search(new):
        new = META_CHARSET.sub('<meta charset="utf-8">', new)
    elif new == text:  # no meta present — insert right after <head>
        new, n = re.subn(r"(<head[^>]*>)", r'\1\n<meta charset="utf-8">', new, count=1, flags=re.IGNORECASE)
        if not n:
            new = '<meta charset="utf-8">\n' + new
    return new, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--keep-originals", type=Path, help="copy original bytes here before converting")
    a = ap.parse_args()
    keep = a.keep_originals.resolve() if a.keep_originals else None

    report = {"converted": [], "skipped_utf8": [], "failed": {}}
    for p in iter_html(a.site):
        if keep and keep in p.resolve().parents:
            continue                       # never convert the kept originals themselves
        rel = p.relative_to(a.site).as_posix()
        raw = p.read_bytes()
        if detect_charset(raw, default="cp1250") != "cp1250":
            report["skipped_utf8"].append(rel)
            continue
        new, why = convert(raw)
        if new is None:
            report["failed"][rel] = why
            continue
        report["converted"].append(rel)
        if a.apply:
            if keep:
                dst = keep / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(raw)
            p.write_bytes(new.encode("utf-8"))

    print(f"cp1250 → UTF-8: {len(report['converted'])} {'převedeno' if a.apply else 'lze převést (dry-run)'}")
    print(f"již UTF-8 / jiné: {len(report['skipped_utf8'])}")
    print(f"NEPROŠLO validací (zůstávají cp1250, na Pages se rozbijí — opravit ručně): {len(report['failed'])}")
    for rel, why in report["failed"].items():
        print(f"  {rel}: {why}")
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["failed"] and a.apply else 0


if __name__ == "__main__":
    sys.exit(main())
