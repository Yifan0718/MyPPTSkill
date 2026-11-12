"""Bounded update metadata transport against tiny loopback HTTP fixtures."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import check_update as update


class UpdateTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='update-transport-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'VERSION').write_text('1.0', encoding='utf8')
        self.stopping = threading.Event()
        stopping = self.stopping
        valid = b'{"latest_version":"1.0","history":[]}'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                mode = self.path.split('/')[1]
                if mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/valid/updates.json')
                    self.end_headers()
                    return
                self.send_response(200)
                bodies = {'valid': valid, 'invalid': b'{', 'schema': b'[]',
                          'encoding': b'\xff', 'oversize': b' ' * 513,
                          'no-length-oversize': b' ' * 513, 'no-length': valid}
                body = bodies.get(mode, b'{}')
                if mode == 'truncated':
                    self.send_header('Content-Length', '100')
                elif mode == 'slow':
                    self.send_header('Content-Length', '10000')
                elif not mode.startswith('no-length'):
                    self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    if mode == 'slow':
                        while not stopping.is_set():
                            self.wfile.write(b' ')
                            self.wfile.flush()
                            stopping.wait(.02)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])

    def stop_server(self):
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def invoke(self, mode):
        (self.root / 'updates.json').write_text(
            json.dumps({'update_source': self.url + '/' + mode}), encoding='utf8')
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['check_update', '--skill-root', str(self.root)]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = update.main()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertNotIn('Traceback', err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def test_valid_metadata_redirect_and_unknown_length_succeed(self):
        for mode in ('valid', 'redirect', 'no-length'):
            with self.subTest(mode=mode):
                code, out, err = self.invoke(mode)
                self.assertEqual(code, 0, err)
                self.assertIn('Up to date', out)

    def test_truncated_http_response_is_transport_failure(self):
        code, out, err = self.invoke('truncated')
        self.assertEqual(code, 3)
        self.assertEqual(out, '')
        self.assertIn('IncompleteRead', err)
        self.assertIn('remote version is unverified', err)

    def test_slow_stream_is_stopped_by_wall_clock_deadline(self):
        with patch.object(update, 'HTTP_FETCH_TIMEOUT', .4):
            started = time.monotonic()
            code, out, err = self.invoke('slow')
            elapsed = time.monotonic() - started
        self.assertEqual(code, 3)
        self.assertEqual(out, '')
        self.assertIn('wall-clock deadline', err)
        self.assertLess(elapsed, 3)

    def test_hung_dns_is_stopped_by_parent_deadline(self):
        worker = ('import socket, time\n'
                  'socket.getaddrinfo = lambda *args, **kwargs: time.sleep(30)\n'
                  + update.HTTP_FETCH_WORKER)
        with patch.object(update, 'HTTP_FETCH_WORKER', worker), \
                patch.object(update, 'HTTP_FETCH_TIMEOUT', .4):
            started = time.monotonic()
            code, out, err = self.invoke('valid')
            elapsed = time.monotonic() - started
        self.assertEqual(code, 3)
        self.assertEqual(out, '')
        self.assertIn('wall-clock deadline', err)
        self.assertLess(elapsed, 3)

    def test_metadata_limit_applies_with_and_without_content_length(self):
        with patch.object(update, 'HTTP_METADATA_LIMIT', 512):
            for mode in ('oversize', 'no-length-oversize'):
                with self.subTest(mode=mode):
                    code, out, err = self.invoke(mode)
                    self.assertEqual(code, 3)
                    self.assertEqual(out, '')
                    self.assertIn('byte limit', err)

    def test_encoding_json_and_schema_failures_remain_metadata_status_four(self):
        for mode in ('encoding', 'invalid', 'schema'):
            with self.subTest(mode=mode):
                code, out, err = self.invoke(mode)
                self.assertEqual(code, 4)
                self.assertEqual(out, '')
                self.assertIn('ERR', err)

    def test_worker_launch_failure_preserves_local_version(self):
        with patch.object(update.subprocess, 'run', side_effect=OSError('worker unavailable')):
            code, out, err = self.invoke('valid')
        self.assertEqual(code, 3)
        self.assertEqual(out, '')
        self.assertIn('remote version is unverified', err)


if __name__ == '__main__':
    unittest.main()
