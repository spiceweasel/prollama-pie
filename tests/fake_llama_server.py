#!/usr/bin/env python3
"""Deterministic fake backend for supervisor integration tests; no GGUF inference."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
p=argparse.ArgumentParser(add_help=False)
p.add_argument('--port', type=int, required=True)
p.add_argument('--host', default='127.0.0.1')
a, _ = p.parse_known_args()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data=(b'{"status":"ok"}' if self.path=='/health' else
              b'llamacpp:tokens_predicted_total 12\n' if self.path=='/metrics' else b'{}')
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args): pass
ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
