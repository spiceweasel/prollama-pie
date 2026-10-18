"""Optional real nginx integration: adding listener must not cut existing SSE.

Run: pytest -q tests/test_nginx_streaming.py
Requires nginx and openssl on Linux; no root and no production nginx edits.
"""
import http.client
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from prollama.nginx_apply import render

pytestmark = pytest.mark.skipif(not shutil.which('nginx') or not shutil.which('openssl'), reason='requires nginx and openssl')

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def test_nginx_reload_preserves_active_stream(tmp_path):
    class StreamHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self):
            if self.path == '/stream':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                for i in range(14):
                    try:
                        self.wfile.write(f'data: {i}\n\n'.encode())
                        self.wfile.flush()
                    except BrokenPipeError: return
                    time.sleep(.18)
            else:
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'ok')
        def log_message(self, *args): pass
    backend = ThreadingHTTPServer(('127.0.0.1', 0), StreamHandler)
    th=threading.Thread(target=backend.serve_forever, daemon=True)
    th.start()
    unique = set()
    while len(unique) < 3: unique.add(free_port())
    first, second, admin = sorted(unique)
    cert = tmp_path / 'cert.pem'; key = tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    settings = {'admin_public_port': admin, 'admin_backend_port': 29991, 'cert': str(cert),
                'key': str(key), 'server_name':'localhost', 'listen_address': '127.0.0.1'}
    routes = [{'public_port':first,'backend_port':backend.server_port}]
    conf = tmp_path / 'generated.conf'
    conf.write_text(render(settings, {'routes': routes}))
    main = tmp_path / 'nginx.conf'
    main.write_text(f'''worker_processes 1;
pid {tmp_path}/nginx.pid;
error_log {tmp_path}/nginx-error.log warn;
events {{ worker_connections 64; }}
http {{ include /etc/nginx/mime.types; include {conf}; }}
''')
    subprocess.run(['nginx','-t','-c',str(main),'-p',str(tmp_path)], check=True, capture_output=True)
    nginx = subprocess.Popen(['nginx','-c',str(main),'-p',str(tmp_path),'-g','daemon off;'],
                             stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        context=ssl._create_unverified_context()
        connection=None
        for _ in range(25):
            try:
                connection=http.client.HTTPSConnection('127.0.0.1', first, context=context, timeout=8)
                connection.request('GET','/stream')
                response=connection.getresponse()
                assert response.status == 200
                assert response.readline() == b'data: 0\n'
                break
            except (OSError, http.client.HTTPException):
                time.sleep(.1)
        else: pytest.fail('nginx listener did not start')
        # Add a separate live port. No restart, only graceful reload.
        routes.append({'public_port':second,'backend_port':free_port()})
        conf.write_text(render(settings, {'routes':routes}))
        subprocess.run(['nginx','-t','-c',str(main),'-p',str(tmp_path)], check=True, capture_output=True)
        subprocess.run(['nginx','-s','reload','-c',str(main),'-p',str(tmp_path)], check=True, capture_output=True)
        # Stream initiated under old worker continues for seconds after reload.
        lines=[response.readline() for _ in range(9)]
        assert b'data: 1\n' in lines
        assert b'data: 4\n' in lines
        connection.close()
        test=http.client.HTTPSConnection('127.0.0.1',second, context=context, timeout=3)
        for _ in range(20):
            try:
                test.request('GET','/ping')
                assert test.getresponse().status==502
                break
            except OSError:
                time.sleep(.1)
        else: pytest.fail('new nginx listener did not bind')
        test.close()
    finally:
        subprocess.run(['nginx','-s','quit','-c',str(main),'-p',str(tmp_path)], capture_output=True)
        try: nginx.wait(timeout=6)
        except subprocess.TimeoutExpired: nginx.kill(); nginx.wait(timeout=3)
        backend.shutdown()
        backend.server_close()
