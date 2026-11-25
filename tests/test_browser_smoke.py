"""Optional real-Chrome checks against a loopback-only synthetic forum.

NS_BROWSER_SMOKE=true python -m unittest discover -s tests -p test_browser_smoke.py -v
No NodeSeek session, cookie, sign-in or real comment is used.
"""
import html
import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

import browser_actions
from lottery import Post
from forum_fixtures import listing


class Forum(BaseHTTPRequestHandler):
    comments = []
    optimistic = False

    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in {'/', '/page-2', '/search'}:
            rows = [('1001', '抽奖 VPS')] if path == '/' else [('1002', '盖楼送鸡')]
            next_href = '/page-2' if path == '/' else None
            page = listing(rows, next_href, newest=path != '/search')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode())
            return
        comments = "".join(f'<div class="content-item" id="{i}" data-comment-id="{i}">'
                           f'<a class="author-name" href="/space/42">Me</a>'
                           f'<article class="post-content">{html.escape(text)}</article></div>'
                           for i, text in enumerate(type(self).comments, 100))
        page = '''<!doctype html><html><head><meta charset="utf-8"><title>Fixture</title></head><body>
          <header><a href="/space/42">Me</a></header><div id="nsk-frame">
          <h1><a class="post-title-link" href="POST_PATH">抽奖送 VPS</a></h1>
          <div class="content-item" id="0" data-comment-id="1"><a class="author-name" href="/space/7">OP</a>
          <span class="date-created"><time datetime="PUBLISHED">1h ago</time></span>
          <article class="post-content">回复参与，随机抽一位。</article></div>
          COMMENTS
          <div class="CodeMirror"><textarea id="editor"></textarea></div>
          <button class="submit btn" onclick="publish()">发布评论</button>
          <script>
            const editor = document.getElementById('editor');
            document.querySelector('.CodeMirror').CodeMirror = {
              getValue: () => editor.value, setValue: text => editor.value = text
            };
            async function publish() {
              const response = await fetch('/reply', {method:'POST', body:JSON.stringify({text:editor.value})});
              const result = await response.json();
              const node = document.createElement('div');
              node.className = 'content-item'; node.id = result.id;
              node.setAttribute('data-comment-id', result.id);
              node.innerHTML = '<a class="author-name" href="/space/42">Me</a><article class="post-content"></article>';
              node.querySelector('.post-content').textContent = editor.value;
              document.body.appendChild(node);
            }
          </script></div></body></html>'''.replace("COMMENTS", comments).replace('POST_PATH', path).replace(
              'PUBLISHED', (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())

    def do_POST(self):
        text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"]
        number = 100 + len(type(self).comments)
        if not type(self).optimistic:
            type(self).comments.append(text)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": number}).encode())


@unittest.skipUnless(os.environ.get("NS_BROWSER_SMOKE") == "true", "opt-in loopback Chrome test")
class RealChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        if os.environ.get("CHROME_PATH"):
            options.binary_location = os.environ["CHROME_PATH"]
        service = Service(executable_path=os.environ.get("CHROMEDRIVER_PATH"))
        cls.driver = webdriver.Chrome(options=options, service=service)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Forum)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def prepare(self):
        candidate = Post("1001", "抽奖", "https://www.nodeseek.com/post-1001-1", "回复参与",
                         datetime.now(timezone.utc) - timedelta(hours=1))
        navigate = self.driver.get
        with patch.object(self.driver, "get", side_effect=lambda _: navigate(
                f"http://127.0.0.1:{self.server.server_port}/post-1001-1")):
            return browser_actions.prepare_reply(self.driver, candidate, "参与一下", "42")

    def test_reply_must_survive_a_fresh_page_load(self):
        Forum.comments, Forum.optimistic = [], False
        action = self.prepare()
        self.assertEqual(action(), "confirmed")
        self.assertEqual(Forum.comments, ["参与一下"])
        self.assertIsNone(self.prepare())  # Visible participation cannot be repeated.

    def test_optimistic_dom_without_server_persistence_is_unknown(self):
        Forum.comments, Forum.optimistic = [], True
        with patch.object(browser_actions, "WebDriverWait", side_effect=lambda d, t: WebDriverWait(d, min(t, 2))):
            self.assertEqual(self.prepare()(), "unknown")
        self.assertEqual(Forum.comments, [])

    def test_async_already_checked_in_feedback_does_not_need_a_reward_button(self):
        self.driver.get(f"http://127.0.0.1:{self.server.server_port}/post-1001-1")
        self.driver.execute_script("""
            const icon = document.createElement('span'); icon.title = '签到'; icon.textContent = '签到';
            icon.onclick = () => setTimeout(() => {
              const alert = document.createElement('div'); alert.setAttribute('role','alert');
              alert.textContent = '今日已签到'; document.body.appendChild(alert);
            }, 100);
            document.querySelector('header').appendChild(icon);
        """)
        with patch.object(browser_actions, "WebDriverWait", side_effect=lambda d, t: WebDriverWait(d, min(t, 2))):
            self.assertEqual(browser_actions.click_sign_icon(self.driver), "already")

    def test_hidden_success_template_is_not_checkin_evidence(self):
        self.driver.get(f"http://127.0.0.1:{self.server.server_port}/post-1001-1")
        self.driver.execute_script("""
            const template = document.createElement('div'); template.className='msc-alert';
            template.style.display='none'; template.textContent='签到成功'; document.body.appendChild(template);
        """)
        self.assertIsNone(browser_actions.checkin_status(self.driver))

    def test_search_and_newest_pagination_read_real_pages_without_filling_or_posting(self):
        # Map only transport to the loopback server; preserve the public route contract.
        Forum.comments = []
        driver, port = self.driver, self.server.server_port
        class LocalTransport:
            current_url = ''
            def get(self, url):
                self.current_url = url
                parts = urlsplit(url)
                driver.get(f'http://127.0.0.1:{port}{parts.path}?{parts.query}')
            @property
            def page_source(self):
                return driver.page_source
        result = browser_actions.discover_posts(LocalTransport(), '42', recent_pages=2,
                                                search_pages=1, pause_seconds=0)
        self.assertEqual([post.id for post in result.posts], ['1001', '1002'])
        self.assertEqual(result.report['pages'], {'newest': 2, 'search:抽奖': 1})
        self.assertEqual(Forum.comments, [])
        self.assertEqual(self.driver.execute_script('return document.querySelector("textarea").value'), '')


if __name__ == "__main__":
    unittest.main()
