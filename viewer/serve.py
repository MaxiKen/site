#!/usr/bin/env python3
"""
Live comparison viewer: original PDF (rendered tiles) vs. extracted shapefiles (GeoJSON).

    python viewer/serve.py [--port 8080] [--host 0.0.0.0] [--rebuild]

On first start (or with --rebuild) it runs build_data.py, which renders the PDF tiles and
converts the shapefiles (about 30 s). Everything generated lives in viewer/build/.
"""
import argparse
import os
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      '.geojson': 'application/geo+json', '.json': 'application/json',
                      '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png'}

    def send_head(self):
        # serve pre-compressed GeoJSON/JSON when the browser accepts gzip
        path = self.translate_path(self.path)
        if (path.endswith('.geojson') or path.endswith('.json')) and os.path.exists(path + '.gz') \
                and 'gzip' in self.headers.get('Accept-Encoding', ''):
            f = open(path + '.gz', 'rb')
            st = os.fstat(f.fileno())
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(path))
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(st.st_size))
            self.send_header('Last-Modified', self.date_time_string(st.st_mtime))
            self.end_headers()
            return f
        return super().send_head()

    def end_headers(self):
        if '/build/tiles/' in self.path:
            self.send_header('Cache-Control', 'public, max-age=86400')
        else:
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        if '/build/tiles/' in self.path:   # keep the log readable
            return
        super().log_message(fmt, *args)


def ensure_build(rebuild=False):
    needed = [os.path.join(BUILD, 'data', 'meta.json'), os.path.join(BUILD, 'tiles', '9')]
    if rebuild or not all(os.path.exists(p) for p in needed):
        print('building viewer data (PDF tiles + GeoJSON) ...', flush=True)
        subprocess.check_call([sys.executable, os.path.join(HERE, 'build_data.py')])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()
    ensure_build(args.rebuild)
    httpd = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=HERE))
    httpd.daemon_threads = True
    print(f'viewer running at http://{args.host}:{args.port}/  (Ctrl-C to stop)', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
