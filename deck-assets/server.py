#!/usr/bin/env python3
"""Static file server for the presentation assets.

Serves deck-assets/ over HTTP so the Google Slides API can fetch images from a
public URL. Bound to 0.0.0.0 and shown as a live preview; nothing here is part
of the CyberSyn application.
"""
import functools
import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8099"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    handler = functools.partial(Handler, directory=ROOT)
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"serving {ROOT} on http://0.0.0.0:{PORT}", flush=True)
        httpd.serve_forever()
