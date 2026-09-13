from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('fetch_local', SCRIPTS / 'fetch_local.py')
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/article')
            self.end_headers()
            return
        if self.path == '/missing':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/pdf' if self.path == '/binary' else 'text/html; charset=utf-8')
        self.end_headers()
        body = '<html><title>Fixture</title><nav>NOT_ARTICLE</nav><script>NOT_ARTICLE</script>'
        if self.path != '/empty':
            body += '<article><h1>Source evidence</h1><p>First verified paragraph.</p><p>Second paragraph with context.</p><p>Third paragraph with limitations.</p></article>'
        self.wfile.write((body + '</html>').encode())

    def log_message(self, *args):
        pass


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), PageHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_fetch(self, path):
        return subprocess.run([sys.executable, str(SCRIPTS / 'fetch_local.py'), self.url + path, '--prefer', 'stdlib'], capture_output=True, text=True, timeout=10, env={**os.environ, 'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'})

    def test_article_and_redirect_extract_body(self):
        for path in ('/article', '/redirect'):
            result = self.run_fetch(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('First verified paragraph', result.stdout)
            self.assertNotIn('NOT_ARTICLE', result.stdout)
            self.assertIn('tier=local status=ok', result.stderr)

    def test_failure_never_emits_body(self):
        for path in ('/missing', '/empty', '/binary'):
            result = self.run_fetch(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('status=fail', result.stderr)

    def test_non_http_and_credentials_rejected_before_network(self):
        for url in ('file:///etc/hosts', 'ftp://example.com/page', 'https://user:SECRET@example.com'):
            with patch.object(fetcher.urllib.request, 'build_opener', side_effect=AssertionError('network forbidden')):
                with self.assertRaises(ValueError):
                    fetcher.fetch_html(url)

    def test_redirect_cannot_switch_to_file(self):
        handler = fetcher.SourceRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, 'redirect', {}, 'file:///etc/hosts')

    def test_response_limit(self):
        with patch.object(fetcher, 'MAX_RESPONSE_BYTES', 8):
            with self.assertRaises(ValueError):
                fetcher.fetch_html(self.url + '/article')

    def test_copied_install_works_without_retired_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            scripts = home / 'lookup/scripts'
            scripts.mkdir(parents=True)
            for name in ('fetch.sh', 'fetch_local.py'):
                shutil.copy2(SCRIPTS / name, scripts / name)
            env = {**os.environ, 'HOME': str(home), 'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}
            result = subprocess.run(['/bin/bash', str(scripts / 'fetch.sh'), self.url + '/article', '--prefer', 'stdlib'], cwd=home, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('First verified paragraph', result.stdout)
            self.assertFalse((home / '.agents/skills/read').exists())


if __name__ == '__main__':
    unittest.main()
