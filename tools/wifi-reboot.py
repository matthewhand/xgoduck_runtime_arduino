"""Optional, unauthenticated UNO Q reboot page for a trusted Wi-Fi network."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import subprocess
import time


PORT = 9528
CONFIRM = b'confirm=reboot'
COOLDOWN_S = 60
REBOOT = ('/usr/bin/sudo', '-n', '/usr/bin/systemctl', '--when=+5s', 'reboot')


class RebootPage(BaseHTTPRequestHandler):
    timeout = 3

    def page(self, status, title, content, allow=None):
        body = (f'<!doctype html><html lang="en"><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>{title} · Duck Lab</title><main><h1>{title}</h1>{content}'
                '</main></html>').encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if allow:
            self.send_header('Allow', allow)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        ip, port = self.connection.getsockname()
        host = f'{ip}:{port}'
        return host if self.headers.get_all('Host') == [host] else None

    def do_GET(self):
        if not self.valid_host():
            self.page(403, 'Open the Wi-Fi IP address directly', '')
        elif self.path == '/':
            self.page(200, 'Restart the UNO Q?',
                      '<p>This restarts the whole board and interrupts Duck Lab. '
                      'Stop any running trial and turn motor torque off first.</p>'
                      '<form method="post" action="/reboot">'
                      '<button type="submit" name="confirm" value="reboot">Confirm reboot</button>'
                      '</form>')
        elif self.path == '/reboot':
            self.page(405, 'Reboot requires confirmation', '<p><a href="/">Open confirmation</a></p>',
                      allow='POST')
        else:
            self.page(404, 'Page not found', '')

    def do_POST(self):
        if self.path != '/reboot':
            self.page(404, 'Page not found', '')
            return
        host = self.valid_host()
        if not host or self.headers.get_all('Origin') != [f'http://{host}']:
            self.page(403, 'Open the confirmation page directly', '')
            return
        if (self.headers.get_all('Transfer-Encoding')
                or self.headers.get_all('Content-Type') != ['application/x-www-form-urlencoded']
                or self.headers.get_all('Content-Length') != [str(len(CONFIRM))]
                or self.rfile.read(len(CONFIRM)) != CONFIRM):
            self.page(400, 'Missing reboot confirmation', '')
            return
        if time.monotonic() < self.server.retry_at:
            self.page(409, 'A reboot was already requested', '<p>Wait for the board to return.</p>')
            return
        try:
            self.server.schedule_reboot()
        except subprocess.TimeoutExpired:
            self.server.retry_at = time.monotonic() + COOLDOWN_S
            self.page(504, 'Reboot status unknown',
                      '<p>Wait for the board before trying again.</p>')
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            self.log_error('Could not schedule reboot: %s', exc)
            self.page(503, 'Reboot could not be scheduled', '<p>Check the UNO Q service log.</p>')
            return
        self.server.retry_at = time.monotonic() + COOLDOWN_S
        self.page(202, 'Reboot scheduled',
                  '<p>The UNO Q will restart in about five seconds. '
                  'Give it a minute, then reopen Duck Lab over Wi-Fi.</p>')


class RebootServer(HTTPServer):
    def __init__(self, address, schedule_reboot, interface=None):
        self.schedule_reboot = schedule_reboot
        self.retry_at = 0
        self.interface = interface
        super().__init__(address, RebootPage)

    def server_bind(self):
        if self.interface:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                   self.interface.encode() + b'\0')
        super().server_bind()


def schedule_reboot():
    subprocess.run(REBOOT, check=True, timeout=3, stdin=subprocess.DEVNULL)


if __name__ == '__main__':
    with RebootServer(('0.0.0.0', PORT), schedule_reboot, interface='wlan0') as server:
        server.serve_forever()
