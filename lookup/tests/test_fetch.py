from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
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
sys.modules[spec.name] = fetcher
spec.loader.exec_module(fetcher)

ARTICLE = ('<html><title>Fixture</title><nav>NOT_ARTICLE</nav><script>NOT_ARTICLE</script>'
           '<article><h1>Source evidence</h1><p>First verified paragraph.</p>'
           '<p>Second paragraph with context.</p><p>Third paragraph with limitations.</p></article></html>')
PLAIN = 'Keep <script>literal code</script> and <item>data</item>.\n    indented code\n'
LONG_PARAGRAPH = '完整正文。' * 1000
LARGE_TEXT = 'bounded evidence ' * 4000


class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/article')
            self.end_headers()
            return
        if self.path.startswith('/missing'):
            self.send_error(404)
            return
        fixtures = {
            '/article': ('text/html; charset=utf-8', ARTICLE.encode()),
            '/pre': ('text/html', b'<p>Before pre.</p><pre>one\n    indented\n</pre><p>After pre.</p>'),
            '/table': ('text/html', b'<table><tr><th>Cost</th><th>Total</th></tr><tr><td>10</td><td>20</td></tr></table>'),
            '/paragraph': ('text/html', ('<article><p>' + LONG_PARAGRAPH + '</p></article>').encode()),
            '/plain': ('text/plain', PLAIN.encode()),
            '/markdown': ('text/markdown', b'# Heading\n\n[relative](./target) and <literal>\n'),
            '/large': ('text/plain', LARGE_TEXT.encode()),
            '/empty': ('text/html', b'<title>Not body</title><nav>NOT_ARTICLE</nav>'),
            '/binary': ('application/pdf', b'%PDF'),
            '/no-type': (None, ARTICLE.encode()),
            '/quoted-charset': ('text/html; charset="gb18030"', '<p>中文正文完整保留。</p>'.encode('gb18030')),
            '/meta-charset': ('text/html', '<meta charset="gb18030"><p>网页声明的中文编码。</p>'.encode('gb18030')),
            '/bad-charset': ('text/html; charset=unknown-fixture-codec', b'<p>text</p>'),
            '/bad-bytes': ('text/html; charset=utf-8', b'<p>\xff\xfe</p>'),
        }
        content_type, body = fixtures[self.path]
        self.send_response(200)
        if content_type:
            self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(body)

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

    def run_fetch(self, route, *args):
        return subprocess.run(
            [sys.executable, '-B', str(SCRIPTS / 'fetch_local.py'), self.url + route, '--prefer', 'stdlib', *args],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, 'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'})

    def metadata(self, result):
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        data = json.loads(result.stderr)
        self.assertEqual(data['provider'], 'lookup/fetch')
        return data

    def test_article_and_redirect_use_final_source(self):
        for route in ('/article', '/redirect'):
            result = self.run_fetch(route)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('First verified paragraph', result.stdout)
            self.assertNotIn('NOT_ARTICLE', result.stdout)
            self.assertIn('> Source: ' + self.url + '/article\n', result.stdout)
            data = self.metadata(result)
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['redirected'], route == '/redirect')
            self.assertEqual(data['requested_url'], self.url + route)
            self.assertEqual(data['final_url'], self.url + '/article')
            self.assertEqual(datetime.fromisoformat(data['fetched_at'].replace('Z', '+00:00')).tzinfo, timezone.utc)
            self.assertFalse(data['truncated'])

    def test_long_single_paragraph_is_valid_content(self):
        result = self.run_fetch('/paragraph')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(LONG_PARAGRAPH, result.stdout)
        self.assertEqual(self.metadata(result)['content_chars'], len(LONG_PARAGRAPH))

    def test_stdlib_table_cells_do_not_merge_values(self):
        result = self.run_fetch('/table')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'Cost\s+Total')
        self.assertRegex(result.stdout, r'10\s+20')
        self.assertEqual(self.metadata(result)['extractor'], 'stdlib')

    def test_stdlib_pre_preserves_indentation_and_paragraph_boundaries(self):
        result = self.run_fetch('/pre')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'Before pre\.\n{2,}one\n    indented\n{2,}After pre\.')
        self.assertEqual(self.metadata(result)['extractor'], 'stdlib')

    def test_plain_text_and_markdown_do_not_go_through_html_parser(self):
        for route, expected in (('/plain', PLAIN.strip()), ('/markdown', '[relative](./target) and <literal>')):
            result = self.run_fetch(route)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertEqual(self.metadata(result)['extractor'], 'text')

    def test_quoted_and_meta_charsets_are_decoded(self):
        for route, expected in (('/quoted-charset', '中文正文完整保留。'), ('/meta-charset', '网页声明的中文编码。')):
            result = self.run_fetch(route)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertNotIn('\ufffd', result.stdout)

    def test_failure_never_emits_body_or_signed_url(self):
        cases = {'/missing?access_token=private-fixture': 'HTTP_ERROR', '/empty': 'EMPTY_CONTENT',
                 '/binary': 'UNSUPPORTED_CONTENT_TYPE', '/no-type': 'UNSUPPORTED_CONTENT_TYPE',
                 '/bad-charset': 'DECODING_FAILED', '/bad-bytes': 'DECODING_FAILED'}
        for route, code in cases.items():
            result = self.run_fetch(route)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
            data = self.metadata(result)
            self.assertEqual(data['status'], 'error')
            self.assertEqual(data['error']['code'], code)
            self.assertNotIn('private-fixture', result.stderr)
            self.assertNotIn(self.url, result.stderr)

    def test_output_cap_marks_partial_and_can_be_increased(self):
        for options, cap in (((), 40000), (('--max-output-chars', '512'), 512), (('--max-chars', '256'), 256)):
            result = self.run_fetch('/large', *options)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertLessEqual(len(result.stdout), cap)
            self.assertIn('[TRUNCATED:', result.stdout)
            data = self.metadata(result)
            self.assertEqual(data['status'], 'partial')
            self.assertTrue(data['truncated'])
            self.assertEqual(data['output_chars'], len(result.stdout))
        complete = self.run_fetch('/large', '--max-output-chars', '100000')
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertIn(LARGE_TEXT.strip(), complete.stdout)

    def test_invalid_budget_is_an_argument_error(self):
        for value in ('0', '255', '5000001', 'nan'):
            result = self.run_fetch('/article', '--max-output-chars', value)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')

    def test_non_http_and_credentials_rejected_before_network(self):
        for url in ('file:///fixture', 'ftp://example.invalid/page', 'https://user:private-fixture@example.invalid'):
            with patch.object(fetcher.urllib.request, 'build_opener', side_effect=AssertionError('network forbidden')):
                with self.assertRaises(fetcher.FetchFailure):
                    fetcher.fetch_page(url)

    def test_redirect_revalidates_scheme_and_credentials(self):
        handler = fetcher.SourceRedirectHandler()
        for url in ('file:///fixture', 'https://user:private-fixture@example.invalid'):
            with self.assertRaises(fetcher.FetchFailure):
                handler.redirect_request(None, None, 302, 'redirect', {}, url)

    def test_response_limit_prevents_extraction(self):
        with patch.object(fetcher, 'MAX_RESPONSE_BYTES', 8):
            with self.assertRaises(fetcher.FetchFailure) as raised:
                fetcher.fetch_page(self.url + '/article')
        self.assertEqual(raised.exception.code, 'RESPONSE_LIMIT')

    def test_auto_extractor_failure_falls_back_but_forced_mode_reports_it(self):
        page = fetcher.FetchedPage(ARTICLE, 'text/html', 'https://example.invalid/final')
        with patch.object(fetcher, 'extract_with_readability', side_effect=RuntimeError('fixture')):
            content, used = fetcher.extract_page(page, 'auto')
            self.assertIn('First verified paragraph', content.text)
            self.assertEqual(used, 'stdlib')
            with self.assertRaises(fetcher.FetchFailure) as raised:
                fetcher.extract_page(page, 'readability')
            self.assertEqual(raised.exception.code, 'EXTRACTION_FAILED')

    def test_missing_optional_extractor_is_an_explicit_error(self):
        page = fetcher.FetchedPage(ARTICLE, 'text/html', 'https://example.invalid/article')
        with patch.object(fetcher, 'extract_with_readability', return_value=None):
            with self.assertRaises(fetcher.FetchFailure) as raised:
                fetcher.extract_page(page, 'readability')
        self.assertEqual(raised.exception.code, 'EXTRACTOR_UNAVAILABLE')

    def test_readability_resolves_relative_links_from_final_url_when_available(self):
        if not all(importlib.util.find_spec(name) for name in ('readability', 'html2text')):
            self.skipTest('optional readability dependencies are not installed')
        paragraph = ('This is a detailed fixture paragraph containing sufficient article evidence. ' * 10)
        html = '<html><title>Evidence</title><article><p>' + paragraph + '<a href="../target">verified source</a></p></article></html>'
        content = fetcher.extract_with_readability(html, 'https://source.example/a/b/')
        self.assertIsNotNone(content)
        self.assertIn('https://source.example/a/target', content.text)

    def test_copied_install_works_without_retired_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp)
            scripts = fixture / 'lookup/scripts'
            scripts.mkdir(parents=True)
            for name in ('fetch.sh', 'fetch_local.py'):
                shutil.copy2(SCRIPTS / name, scripts / name)
            result = subprocess.run(
                ['/bin/bash', str(scripts / 'fetch.sh'), self.url + '/article', '--prefer', 'stdlib'],
                cwd=fixture, env={**os.environ, 'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('First verified paragraph', result.stdout)
            self.assertFalse((fixture / '.agents/skills/read').exists())


if __name__ == '__main__':
    unittest.main()
