"""Loopback UI and job runner for Triple M. The board can serve the snapshot separately."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread
from urllib.parse import urlsplit

from triple_m_batches import BatchStore, publish_latest, read_json


PORT = 19534
HOST = f'127.0.0.1:{PORT}'


def serve(plan_batch, run_batch, cache, workers, assets):
    latest = cache / 'latest.json'
    lock = Lock()
    status = {'state':'idle'}
    try:
        previous = BatchStore(cache, read_json(cache / 'last-attempt.json')['id'])
        report = previous.report(include_trace=False)
        if report['state'] == 'pending':
            status.update(state='error', batch_id=report['id'], message='The batch stopped before all cases ran. You can retry the remaining cases.')
        elif report['compute']['errors']:
            status.update(state=report['state'], batch_id=report['id'], message='Some cases could not run.')
    except (FileNotFoundError, ValueError, KeyError):
        pass
    latest_seen = None
    latest_id = None

    def update(**fields):
        with lock:
            status.update(fields)

    def report_id():
        nonlocal latest_seen, latest_id
        try:
            stamp = latest.stat().st_mtime_ns
            if stamp != latest_seen:
                latest_id = read_json(latest).get('id')
                latest_seen = stamp
            return latest_id
        except (OSError, ValueError):
            return None

    def run(batch):
        try:
            report = run_batch(batch.manifest['settings'], workers, cache, batch=batch,
                               progress=lambda fields: update(**fields))
            if any(row['result'] is not None for row in report['cases']):
                publish_latest(latest, report)
            update(state=report['state'], message='Some cases could not run.' if report['compute']['errors'] else None)
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
                    snapshot = dict(status, local=True, has_report=latest.is_file(), report_id=report_id())
                return self.send_json(snapshot)
            if path == '/api/triple-m/report':
                return self.send_json(read_json(latest)) if latest.is_file() else self.send_error(404)
            if path.startswith('/api/triple-m/batches/'):
                return self.get_batch(path.split('/')[4:])
            return super().do_GET()

        def get_batch(self, route):
            try:
                batch = BatchStore(cache, route[0])
                with lock:
                    running = status['state'] == 'running' and status.get('batch_id') == route[0]
                if route[1:] == ['manifest']:
                    return self.send_json(batch.manifest)
                if route[1:] in (['summary'], ['report']):
                    return self.send_json(batch.report(include_trace=route[1] == 'report', running=running))
                if len(route) == 3 and route[1] == 'cases':
                    return self.send_json(batch.case(route[2]))
            except (FileNotFoundError, KeyError):
                pass
            return self.send_error(404)

        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') != f'http://{HOST}':
                return self.send_error(403)
            route = self.path.split('/')
            if len(route) == 6 and route[:4] == ['', 'api', 'triple-m', 'batches'] and route[5] == 'retry':
                return self.start_batch(batch_id=route[4])
            if self.path != '/api/triple-m/run':
                return self.send_error(404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if self.headers.get_content_type() != 'application/json' or not 0 < size <= 4096:
                    raise ValueError('Send a Triple M plan as JSON.')
                options = json.loads(self.rfile.read(size))
            except ValueError as exc:
                return self.send_json({'message':str(exc)}, 400)
            return self.start_batch(options=options)

        def start_batch(self, *, options=None, batch_id=None):
            with lock:
                if status['state'] == 'running':
                    return self.send_json({'message':'A batch is already running.'}, 409)
                try:
                    if batch_id is None:
                        batch = BatchStore.create(cache, plan_batch(options))
                    else:
                        batch = BatchStore(cache, batch_id)
                        if not batch.matches(plan_batch(batch.manifest['settings'])):
                            return self.send_json({'message':'Simulation inputs changed. Run a new batch.'}, 409)
                        counts = batch.report(include_trace=False)['counts']
                        if not counts['pending'] and not counts['error']:
                            return self.send_json({'message':'This batch already has all its results.'}, 409)
                    batch.mark_attempt()
                except FileNotFoundError:
                    return self.send_json({'message':'Batch or simulation input was not found.'}, 404)
                except ValueError as exc:
                    return self.send_json({'message': str(exc)}, 400)
                status.clear()
                status.update(state='running', batch_id=batch.manifest['id'])
            Thread(target=run, args=(batch,), daemon=True).start()
            return self.send_json({'state':'running', 'batch_id': batch.manifest['id']}, 202)

    with ThreadingHTTPServer(('127.0.0.1', PORT), Handler) as server:
        print(f'Triple M runner at http://{HOST}/triple-m.html', flush=True)
        server.serve_forever()
