import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, PropertyMock, patch

import nodeseek_daily


class LocalProfileTests(unittest.TestCase):
    def test_profile_session_starts_without_cookie_and_never_injects_cookie(self):
        driver = MagicMock()
        driver.page_source = '<html><title>NodeSeek</title></html>'
        with patch.dict(os.environ, {'NS_PROFILE_DIR': '/dedicated'}, clear=True), \
             patch('local_browser.open_profile_browser', return_value=driver), \
             redirect_stdout(io.StringIO()):
            result = nodeseek_daily.setup_driver_and_cookies()
        self.assertIs(result, driver)
        driver.add_cookie.assert_not_called()
        driver.refresh.assert_not_called()

    def test_refuses_existing_unmarked_profile_before_starting_browser(self):
        from local_browser import open_profile_browser
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'Local State').write_text('personal data')
            with patch('local_browser.webdriver.Chrome') as start:
                with self.assertRaisesRegex(ValueError, '专用'):
                    open_profile_browser(folder)
            start.assert_not_called()
            self.assertEqual(Path(folder, 'Local State').read_text(), 'personal data')

    def test_new_profile_is_marked_and_standard_chrome_uses_its_exact_path(self):
        from local_browser import open_profile_browser
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder, 'profile')
            with patch('local_browser.webdriver.Chrome', return_value=MagicMock()) as start:
                open_profile_browser(profile)
            options = start.call_args.kwargs['options']
            self.assertIn('--user-data-dir=' + str(profile.resolve()), options.arguments)
            self.assertNotIn('--headless=new', options.arguments)
            self.assertTrue((profile / '.nodeseek-profile').is_file())


class LocalRunnerTests(unittest.TestCase):
    def test_challenge_arriving_during_identity_check_stops_without_sleep(self):
        import local_runner
        driver = MagicMock()
        normal = '<title>NodeSeek</title>'
        challenge = '<title>请稍候...</title>'
        with patch.object(type(driver), 'page_source', new_callable=PropertyMock,
                          create=True, side_effect=[normal, challenge, challenge]), \
             patch('local_runner.open_profile_browser', return_value=driver), \
             patch('local_runner.time.monotonic', side_effect=[0, 1, 2, 901]), \
             patch('local_runner.time.sleep') as wait, redirect_stdout(io.StringIO()):
            self.assertEqual(local_runner.login('/dedicated', '42'), 1)
        wait.assert_not_called()
        driver.quit.assert_called_once()

    def test_log_option_accepts_spaced_equals_and_abbreviated_forms(self):
        import local_runner
        for form in ('spaced', 'equals', 'abbreviated'):
            with self.subTest(form=form), tempfile.TemporaryDirectory() as folder:
                log = Path(folder, 'run.log')
                flag = {'spaced': ['--log-file', str(log)],
                        'equals': ['--log-file=' + str(log)],
                        'abbreviated': ['--log-f', str(log)]}[form]
                with patch.dict(os.environ, {'NS_LOCAL_DIR': str(Path(folder, 'runtime'))}, clear=True), \
                     patch('local_runner.login', return_value=0):
                    self.assertEqual(local_runner.run(['--login', '--user-id', '42', *flag]), 0)
                self.assertIn('退出码：0', log.read_text(encoding='utf-8'))

    def test_login_stops_on_site_verification_without_polling_or_navigation_retry(self):
        import local_runner
        driver = MagicMock()
        driver.page_source = '<title>请稍候...</title><h2>正在进行安全验证</h2>'
        with patch('local_runner.open_profile_browser', return_value=driver), \
             patch('local_runner.time.monotonic', side_effect=[0, 1, 901]), \
             patch('local_runner.time.sleep') as wait, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(local_runner.login('/dedicated', '42'), 1)
        self.assertIn('站点安全验证', output.getvalue())
        wait.assert_not_called()
        driver.get.assert_called_once_with('https://www.nodeseek.com/')
        driver.refresh.assert_not_called()
        driver.quit.assert_called_once()

    def test_login_saves_only_after_exact_account_identity_is_visible(self):
        import local_runner
        driver = MagicMock()
        driver.page_source = '<title>NodeSeek</title><header><a href="/space/42">Me</a></header>'
        with patch('local_runner.open_profile_browser', return_value=driver), \
             patch('local_runner.time.sleep') as wait, redirect_stdout(io.StringIO()):
            self.assertEqual(local_runner.login('/dedicated', '42'), 0)
        wait.assert_not_called()
        driver.quit.assert_called_once()

    def test_github_login_failure_is_safe_and_never_calls_account_main(self):
        import local_runner
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {'NS_LOCAL_DIR': folder}, clear=True), \
             patch('local_runner.subprocess.run', return_value=subprocess.CompletedProcess(
                 ['gh'], 1, 'private-output', 'private-error')), \
             patch('local_runner.nodeseek_daily.main') as main, redirect_stdout(output):
            self.assertEqual(local_runner.run(['--live', '--user-id', '42']), 1)
        main.assert_not_called()
        self.assertNotIn('private-output', output.getvalue())
        self.assertNotIn('private-error', output.getvalue())

    def test_existing_process_lock_stops_before_browser_or_github_access(self):
        import local_runner
        from state_store import FileStateStore
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {'NS_LOCAL_DIR': folder}, clear=True), \
             patch('local_runner.subprocess.run') as remote, \
             patch('local_runner.nodeseek_daily.main') as main, redirect_stdout(io.StringIO()):
            with FileStateStore(Path(folder) / 'run').lock():
                self.assertEqual(local_runner.run(['--live', '--user-id', '42']), 1)
        remote.assert_not_called()
        main.assert_not_called()

    def test_local_runner_uses_shared_state_and_ignores_inherited_cookie(self):
        import local_runner
        observed = {}
        def main(args):
            observed.update({key: os.environ.get(key) for key in (
                'NS_STATE_BACKEND', 'GITHUB_REPOSITORY', 'NS_PROFILE_DIR', 'NS_USER_ID', 'NS_COOKIE')})
            self.assertEqual(args, ['--search-preview'])
            return 0
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {'NS_LOCAL_DIR': folder, 'NS_COOKIE': 'private-cookie'}, clear=True), \
             patch('local_runner.subprocess.run', return_value=subprocess.CompletedProcess(
                 ['gh'], 0, 'private-token\n', '')), \
             patch('local_runner.nodeseek_daily.main', side_effect=main):
            self.assertEqual(local_runner.run(['--search-preview', '--user-id', '42']), 0)
        self.assertEqual(observed['NS_STATE_BACKEND'], 'github')
        self.assertEqual(observed['GITHUB_REPOSITORY'], 'lihaorr/NodeSeek-Daily')
        self.assertEqual(observed['NS_USER_ID'], '42')
        self.assertIsNone(observed['NS_COOKIE'])


if __name__ == '__main__':
    unittest.main()
