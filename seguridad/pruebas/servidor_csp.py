"""Sirve frontend/ con las cabeceras de deploy/cloudfront-security-headers.json y reenvía /api/* a la API local,
igual que CloudFront (mismo origen)."""
import http.server
import json
import sys
import urllib.error
import urllib.request

FRONTEND, POLICY, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])
cfg = json.load(open(POLICY))
CSP = cfg["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"].replace("; upgrade-insecure-requests", "")  # el servidor de prueba es HTTP
HEADERS = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"}


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=FRONTEND, **k)

    def end_headers(self):
        for k, v in HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def _proxy(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        req = urllib.request.Request("http://127.0.0.1:58000" + self.path[4:], data=body, method=self.command,
                                     headers={k: v for k, v in self.headers.items() if k.lower() != "host"})
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            resp = e
        data = resp.read()
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        super().end_headers()
        self.wfile.write(data)

    def do_GET(self):
        return self._proxy() if self.path.startswith("/api/") else super().do_GET()

    def do_POST(self):
        return self._proxy()


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
