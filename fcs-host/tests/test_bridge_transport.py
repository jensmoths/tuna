from __future__ import annotations

import socket
import socketserver
import threading
import time
import unittest

from fcs_bridge.bridge_transport import BridgeTransport, probe_single_client_behavior


class _SingleClientHandler(socketserver.BaseRequestHandler):
    active_lock = None
    active_conn = None
    accepted = None

    def handle(self):
        with self.server.active_lock:
            if self.server.active_conn is not None:
                try:
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.request.close()
                return
            self.server.active_conn = self.request
            self.server.accepted.set()

        try:
            while True:
                data = self.request.recv(1024)
                if not data:
                    return
                self.request.sendall(data)
        finally:
            with self.server.active_lock:
                if self.server.active_conn is self.request:
                    self.server.active_conn = None


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _start_single_client_server():
    server = _ThreadingTCPServer(("127.0.0.1", 0), _SingleClientHandler)
    server.active_lock = threading.Lock()
    server.active_conn = None
    server.accepted = threading.Event()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class BridgeTransportTests(unittest.TestCase):
    def test_connect_send_recv_disconnect(self):
        server = _start_single_client_server()
        host, port = server.server_address
        try:
            transport = BridgeTransport(host, port, timeout_seconds=1.0)
            self.assertFalse(transport.is_connected)

            transport.connect()
            self.assertTrue(transport.is_connected)

            transport.send(b"abc")
            self.assertEqual(transport.recv(3), b"abc")

            transport.disconnect()
            self.assertFalse(transport.is_connected)
        finally:
            server.shutdown()
            server.server_close()

    def test_probe_reports_second_client_rejected(self):
        server = _start_single_client_server()
        host, port = server.server_address
        try:
            result = probe_single_client_behavior(host, port, timeout_seconds=1.0)
            self.assertTrue(result.first_connected)
            self.assertTrue(result.second_connected)
            self.assertTrue(result.second_rejected)
        finally:
            server.shutdown()
            server.server_close()

    def test_server_returns_to_idle_after_disconnect(self):
        server = _start_single_client_server()
        host, port = server.server_address
        try:
            first = BridgeTransport(host, port, timeout_seconds=1.0)
            first.connect()
            first.disconnect()
            time.sleep(0.1)

            second = BridgeTransport(host, port, timeout_seconds=1.0)
            second.connect()
            second.send(b"z")
            self.assertEqual(second.recv(1), b"z")
            second.disconnect()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
