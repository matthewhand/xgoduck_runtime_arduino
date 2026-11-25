"""Loopback UI and job runner for Triple M. The board can serve the snapshot separately."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread
from urllib.parse import urlsplit


PORT = 19534
HOST = f'127.0.0.1:{PORT}'


def serve(run_batch, atomic_json, cache, workers, assets):
    latest = cache / 'latest.json'
    lock = Lock()
    status = {'state':'idle'}

    def update(**fields):
        with lock:
            status.update(fields)

    def run(options):
        try:
            report = run_batch(options, workers, cache, progress=lambda fields: update(**fields))
            atomic_json(latest, report)
            update(state='complete')
        except Exception as exc:
            update(state='error', message=str(exc))

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(assets), **kwargs)

        def allowed(self):
            return self.headers.get('Host') == HOST

        def send_json(self, payload, code=200):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed():
                return self.send_error(403)
            path = urlsplit(self.path).path
            if path == '/api/triple-m/status':
                with lock:
                    snapshot = dict(status, local=True, has_report=latest.is_file())
                return self.send_json(snapshot)
            if path == '/api/triple-m/report':
                return self.send_json(json.loads(latest.read_text(encoding='utf-8'))) if latest.is_file() else self.send_error(404)
            return super().do_GET()

        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') != f'http://{HOST}':
                return self.send_error(403)
            if self.path != '/api/triple-m/run':
                return self.send_error(404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if self.headers.get_content_type() != 'application/json' or not 0 < size <= 4096:
                    raise ValueError('Send a Triple M plan as JSON.')
                options = json.loads(self.rfile.read(size))
            except ValueError as exc:
                return self.send_json({'message':str(exc)}, 400)
            with lock:
                if status['state'] == 'running':
                    return self.send_json({'message':'A batch is already running.'}, 409)
                status.clear()
                status.update(state='running')
            Thread(target=run, args=(options,), daemon=True).start()
            self.send_json({'state':'running'}, 202)

    with ThreadingHTTPServer(('127.0.0.1', PORT), Handler) as server:
        print(f'Triple M runner at http://{HOST}/triple-m.html', flush=True)
        server.serve_forever()
