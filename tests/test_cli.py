import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / "nodeseek_daily.py"), *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                   "NS_STATE_BACKEND": "local", **(env or {})}, timeout=20)

    def test_offline_preview_outputs_two_candidates_and_never_creates_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state.json"
            result = self.invoke("--feed-file", "tests/fixtures/giveaways.xml", "--at",
                                 "2026-11-25T08:00:00+00:00", "--state-file", str(state))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual([item["id"] for item in payload["preview"]], ["1001", "1002"])
            self.assertEqual(payload["confirmed"], [])
            self.assertFalse(state.exists())

    def test_invalid_backend_cannot_silently_use_an_empty_local_quota(self):
        result = self.invoke("--feed-file", "tests/fixtures/giveaways.xml",
                             env={"NS_STATE_BACKEND": "githbu"})
        self.assertEqual(result.returncode, 1)

    def test_pull_request_environment_never_allows_live_account_actions(self):
        result = self.invoke("--live", env={"GITHUB_EVENT_NAME": "pull_request", "NS_USER_ID": "42"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("PR", result.stdout)

    def test_search_preview_rejects_sample_mode_and_pull_request_account_access(self):
        for args, env in [(('--search-preview', '--feed-file', 'tests/fixtures/giveaways.xml'), {}),
                          (('--search-preview',), {'GITHUB_EVENT_NAME': 'pull_request', 'NS_USER_ID': '42'})]:
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args, env=env).returncode, 1)

    def test_search_preview_reports_site_failure_instead_of_zero_results(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        import nodeseek_daily
        from discovery import DiscoveryError
        message = '站点拒绝搜索：请求限流；本轮不重试'
        with patch.dict(os.environ, {'NS_STATE_BACKEND': 'local', 'NS_USER_ID': '42'}, clear=True), \
             patch.object(nodeseek_daily, 'load_dotenv'), \
             patch.object(nodeseek_daily, 'run_search_preview', side_effect=DiscoveryError(message)), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(nodeseek_daily.main(['--search-preview']), 1)
        self.assertIn(message, out.getvalue())


if __name__ == "__main__":
    unittest.main()
