import io
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import setuptools  # noqa: F401  # Enables distutils compatibility on Python 3.14.

import nodeseek_daily


class ChromeDriverInitializationTests(unittest.TestCase):
    def test_blocked_refresh_logs_stage_and_category_without_page_or_cookie(self):
        fake_driver = MagicMock()
        fake_driver.page_source = '<title>Just a moment... private-page-detail</title>'
        output = io.StringIO()
        with patch.dict(os.environ, {'NS_COOKIE': 'session=private-cookie'}, clear=True), \
             patch.object(nodeseek_daily, 'detect_chrome_runtime', return_value=('/chrome', 150)), \
             patch.object(nodeseek_daily.uc, 'Chrome', return_value=fake_driver), \
             redirect_stdout(output):
            result = nodeseek_daily.setup_driver_and_cookies()
        self.assertIsNone(result)
        self.assertIn('authenticated-refresh', output.getvalue())
        self.assertIn('site_verification', output.getvalue())
        self.assertNotIn('private-cookie', output.getvalue())
        self.assertNotIn('private-page-detail', output.getvalue())
        fake_driver.quit.assert_called_once()

    def test_uses_installed_chrome_major_version_for_uc(self):
        chrome_path = "/usr/bin/chromium-browser"
        fake_driver = MagicMock()
        fake_driver.page_source = "<html><title>NodeSeek</title></html>"

        with patch.dict(os.environ, {
                 "NS_COOKIE": "session=value",
                 "HEADLESS": "true",
                 "GITHUB_ACTIONS": "true",
             }, clear=True), \
             patch.object(nodeseek_daily.uc, "find_chrome_executable", return_value=chrome_path), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(
                 args=[chrome_path, "--version"],
                 returncode=0,
                 stdout="Chromium 150.0.7871.128\n",
                 stderr="",
             )) as run_version, \
             patch.object(nodeseek_daily.uc, "Chrome", return_value=fake_driver) as create_driver, \
             patch.object(nodeseek_daily.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                result = nodeseek_daily.setup_driver_and_cookies()

        self.assertIs(result, fake_driver)
        self.assertEqual(create_driver.call_args.kwargs.get("browser_executable_path"), chrome_path)
        self.assertEqual(create_driver.call_args.kwargs.get("version_main"), 150)
        self.assertEqual(run_version.call_args.args[0], [chrome_path, "--version"])

    def test_does_not_start_browser_when_chrome_version_cannot_be_read(self):
        chrome_path = "/usr/bin/chromium-browser"

        with patch.dict(os.environ, {
                 "NS_COOKIE": "session=value",
                 "HEADLESS": "true",
                 "GITHUB_ACTIONS": "true",
             }, clear=True), \
             patch.object(nodeseek_daily.uc, "find_chrome_executable", return_value=chrome_path), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(
                 args=[chrome_path, "--version"],
                 returncode=0,
                 stdout="Chromium version unavailable\n",
                 stderr="",
             )), \
             patch.object(nodeseek_daily.uc, "Chrome") as create_driver, \
             patch.object(nodeseek_daily.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                result = nodeseek_daily.setup_driver_and_cookies()

        self.assertIsNone(result)
        create_driver.assert_not_called()

    def test_local_run_falls_back_when_chrome_version_cannot_be_read(self):
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        fake_driver = MagicMock()
        fake_driver.page_source = "<html><title>NodeSeek</title></html>"

        with patch.dict(os.environ, {"NS_COOKIE": "session=value", "HEADLESS": "true"}, clear=True), \
             patch.object(nodeseek_daily.uc, "find_chrome_executable", return_value=chrome_path), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(
                 args=[chrome_path, "--version"],
                 returncode=0,
                 stdout="正在现有的浏览器会话中打开。\n",
                 stderr="",
             )), \
             patch.object(nodeseek_daily.uc, "Chrome", return_value=fake_driver) as create_driver, \
             patch.object(nodeseek_daily.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                result = nodeseek_daily.setup_driver_and_cookies()

        self.assertIs(result, fake_driver)
        self.assertEqual(create_driver.call_args.kwargs.get("browser_executable_path"), chrome_path)
        self.assertNotIn("version_main", create_driver.call_args.kwargs)

    def test_local_run_falls_back_when_chrome_version_command_times_out(self):
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        fake_driver = MagicMock()
        fake_driver.page_source = "<html><title>NodeSeek</title></html>"

        with patch.dict(os.environ, {"NS_COOKIE": "session=value", "HEADLESS": "true"}, clear=True), \
             patch.object(nodeseek_daily.uc, "find_chrome_executable", return_value=chrome_path), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                 cmd=[chrome_path, "--version"],
                 timeout=10,
             )), \
             patch.object(nodeseek_daily.uc, "Chrome", return_value=fake_driver) as create_driver, \
             patch.object(nodeseek_daily.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                result = nodeseek_daily.setup_driver_and_cookies()

        self.assertIs(result, fake_driver)
        self.assertEqual(create_driver.call_args.kwargs.get("browser_executable_path"), chrome_path)
        self.assertNotIn("version_main", create_driver.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
