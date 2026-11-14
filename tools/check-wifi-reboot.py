"""Exercise the reboot page over loopback without calling systemctl."""

from http.client import HTTPConnection
from pathlib import Path
import runpy
import subprocess
from threading import Thread
import unittest
from unittest.mock import Mock


reboot = runpy.run_path(str(Path(__file__).with_name('wifi-reboot.py')))


class RebootTests(unittest.TestCase):
    def setUp(self):
        self.schedule = Mock()
        self.server = reboot['RebootServer'](('127.0.0.1', 0), self.schedule)
        self.server.RequestHandlerClass = type('QuietPage', (reboot['RebootPage'],),
                                               {'log_message': lambda *args: None})
        self.port = self.server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'
        self.worker = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.worker.join)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def confirm(self, body=b'confirm=reboot', **headers):
        return self.request('POST', '/reboot', body,
                            {'Origin': self.origin, 'Content-Type': 'application/x-www-form-urlencoded',
                             **headers})

    def test_page_is_read_only_and_confirms_once(self):
        code, headers, page = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'Confirm reboot', page)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/reboot')[0], 405)
        self.schedule.assert_not_called()
        self.assertEqual(self.confirm()[0], 202)
        self.assertEqual(self.confirm()[0], 409)
        self.schedule.assert_called_once_with()

    def test_cross_origin_and_rebound_host_cannot_submit(self):
        for origin in ('http://other.invalid', 'null'):
            self.assertEqual(self.confirm(Origin=origin)[0], 403)
        self.assertEqual(self.confirm(Host=f'other.invalid:{self.port}',
                                      Origin=f'http://other.invalid:{self.port}')[0], 403)
        self.assertEqual(self.request('POST', '/reboot', b'confirm=reboot')[0], 403)
        code, headers, _ = self.request('OPTIONS', '/reboot', headers={
            'Origin': 'http://other.invalid', 'Access-Control-Request-Method': 'POST'})
        self.assertGreaterEqual(code, 400)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.schedule.assert_not_called()

    def test_wrong_confirmation_and_unbounded_input_are_rejected(self):
        for body in (b'', b'confirm=cancel', b'confirm=reboot&extra=true'):
            self.assertEqual(self.confirm(body)[0], 400)
        self.assertEqual(self.confirm(b'', **{'Content-Length': '1000000000'})[0], 400)
        self.assertEqual(self.confirm(**{'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.confirm(**{'Content-Type': 'text/plain'})[0], 400)
        self.schedule.assert_not_called()

    def test_definite_failure_allows_retry_but_timeout_does_not(self):
        self.schedule.side_effect = [
            subprocess.CalledProcessError(1, 'stub'),
            subprocess.TimeoutExpired('stub', 3),
        ]
        self.assertEqual(self.confirm()[0], 503)
        self.assertEqual(self.confirm()[0], 504)
        self.assertEqual(self.confirm()[0], 409)
        self.assertEqual(self.schedule.call_count, 2)


if __name__ == '__main__':
    unittest.main()
