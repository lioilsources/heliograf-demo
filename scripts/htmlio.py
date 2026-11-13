"""Shared HTML read/write preserving encoding (pi-alpha is windows-1250, heliograf UTF-8).

Rule: a file is always written back in the SAME encoding it was read in.
Only convert_charset.py changes encoding (separate PR, plan §4.5 E).
"""
from __future__ import annotations

import codecs
import mimetypes
import re
from pathlib import Path

HTML_EXT = {".html", ".htm", ""}
META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.IGNORECASE
)
ALIASES = {"windows-1250": "cp1250", "windows1250": "cp1250", "win-1250": "cp1250", "win1250": "cp1250",
           "x-cp1250": "cp1250", "cp-1250": "cp1250", "utf8": "utf-8", "iso-8859-2": "iso8859_2"}


def has_real_ext(p: Path) -> bool:
    """Suffix a web server maps to a content type? `Pf.2018` or `pavel-ii.` has none → served as binary."""
    return bool(p.suffix) and len(p.suffix) > 1 and mimetypes.guess_type("x" + p.suffix.lower())[0] is not None


def is_html(p: Path) -> bool:
    """HTML file? Pages without a real extension (pi-alpha `/Editor`, `/Duka/Blog/…-pf-2018`) by content."""
    if p.suffix.lower() in (".html", ".htm"):
        return True
    if not has_real_ext(p) and p.is_file():
        head = p.read_bytes()[:512].lstrip().lower()
        return head.startswith((b"<!doctype html", b"<html", b"<head", b"<meta"))
    return False


def iter_html(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts) and is_html(p):
            yield p


def read_globs(path: Path | None) -> list[str]:
    """Glob list file: one pattern per line, `#` comments and blank lines ignored, missing file = []."""
    if not path or not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def detect_charset(raw: bytes, default: str = "utf-8") -> str:
    m = META_CHARSET.search(raw[:4096])
    if m:
        cs = m.group(1).decode("ascii").lower()
        cs = ALIASES.get(cs, cs)
        try:
            return codecs.lookup(cs).name
        except LookupError:
            pass  # unknown name in meta → guess below
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return default


def read_html(p: Path) -> tuple[str, str]:
    """→ (text, encoding). Undecodable bytes via surrogateescape so writing returns the exact original."""
    raw = p.read_bytes()
    enc = detect_charset(raw, default="cp1250")
    return raw.decode(enc, errors="surrogateescape"), enc


def write_html(p: Path, text: str, enc: str) -> bool:
    """Writes only on change. Characters outside the encoding → HTML entities (safe for cp1250)."""
    data = text.encode(enc, errors="surrogateescape") if _encodable(text, enc) else _encode_entities(text, enc)
    if p.read_bytes() == data:
        return False
    p.write_bytes(data)
    return True


def _encodable(text: str, enc: str) -> bool:
    try:
        text.encode(enc, errors="surrogateescape")
        return True
    except UnicodeEncodeError:
        return False


def _encode_entities(text: str, enc: str) -> bytes:
    out = bytearray()
    for ch in text:
        try:
            out += ch.encode(enc, errors="surrogateescape")
        except UnicodeEncodeError:
            out += f"&#x{ord(ch):x};".encode("ascii")
    return bytes(out)


# URL attributes: quoted and unquoted (pi-alpha writes `href=foo.html`)
URL_ATTR = re.compile(
    r"""(?P<pre>(?<![\w-])(?P<attr>href|src|poster|data-src|background)\s*=\s*)(?P<q>["'])?(?P<url>(?(q)[^"'>]*|[^\s>"']+))(?(q)(?P=q))""",
    re.IGNORECASE,
)
# url(...) in inline style attributes and <style> blocks; `post` keeps the closing part
CSS_URL = re.compile(r"""(?P<pre>url\(\s*)(?P<q>["']?)(?P<url>[^)"'\s]+)(?P=q)(?P<post>\s*\))""", re.IGNORECASE)
