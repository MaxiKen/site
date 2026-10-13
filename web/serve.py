"""Static server for the geological-map comparison viewer (binds 0.0.0.0).

The scan itself lives one level up in the repository and is served from there
so it is not duplicated into web/.
"""
import http.server, socketserver, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
HERE = os.getcwd()
ROOT = os.path.dirname(HERE)
SCAN = 'pic NGSA geological-map-of-nigeria-.jpg'


class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.geojson': 'application/geo+json', '.jpg': 'image/jpeg'}

    def translate_path(self, path):
        if path.split('?')[0].lstrip('/') == 'original.jpg':
            return os.path.join(ROOT, SCAN)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *a):
        pass


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(('0.0.0.0', int(os.environ.get('PORT', '8000'))), H) as httpd:
    print('serving', HERE, 'on 0.0.0.0', httpd.server_address[1], flush=True)
    httpd.serve_forever()
