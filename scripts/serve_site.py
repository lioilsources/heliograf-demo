#!/usr/bin/env python3
"""Local static server that behaves like GitHub Pages (plan 00 §5.3, plan 01 block D1).

  - /Foo        → Foo.html when Foo itself does not exist
  - /dir        → 301 to /dir/, then dir/index.html
  - missing     → 404 with 404.html when present
  - .html is sent as `text/html; charset=utf-8`, like Pages: a cp1250 page shows broken
    diacritics here exactly as it would on Pages
  - query strings are ignored (Pages ignores them too)

  python3 scripts/serve_site.py _site --port 8090
"""
from __future__ import annotations

import argparse
import http.server
import os
import posixpath
from functools import partial
from urllib.parse import unquote, urlsplit


class PagesHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".webp": "image/webp",
        "": "application/octet-stream",
    }

    def _resolve(self) -> str | None:
        path = unquote(urlsplit(self.path).path)
        fs = os.path.join(self.directory, *[p for p in posixpath.normpath(path).split("/") if p not in ("", "..")])
        if os.path.isdir(fs):
            if not path.endswith("/"):
                return "redirect"
            fs = os.path.join(fs, "index.html")
        elif not os.path.exists(fs) and os.path.isfile(fs + ".html"):
            fs += ".html"
        return fs if os.path.isfile(fs) else None

    def send_head(self):
        fs = self._resolve()
        if fs == "redirect":
            self.send_response(301)
            self.send_header("Location", urlsplit(self.path).path + "/")
            self.end_headers()
            return None
        if fs is None:
            nf = os.path.join(self.directory, "404.html")
            body = open(nf, "rb").read() if os.path.isfile(nf) else b"404 Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return _Body(body)
        f = open(fs, "rb")
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(fs))
        self.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser aborted the load (navigation, lazy image) — not an error

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ("200", "301", "304"):
            super().log_message(fmt, *args)


class _Body:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, *_):
        d, self.data = self.data, b""
        return d

    def close(self):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    handler = partial(PagesHandler, directory=os.path.abspath(a.root))
    with http.server.ThreadingHTTPServer((a.bind, a.port), handler) as srv:
        print(f"serving {a.root} on http://{a.bind}:{a.port}/ (GitHub Pages rules)")
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
