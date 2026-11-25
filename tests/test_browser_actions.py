import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import setuptools  # noqa: F401
import nodeseek_daily
from browser_actions import PageBlocked, assert_account, reply_entries, ensure_page, prepare_reply
from lottery import Post
from state_store import empty_state


def html_reply(identifier, author, text):
    return (f'<div class="content-item" id="1" data-comment-id="{identifier}">'
            f'<a class="author-name" href="/space/{author}">User</a>'
            f'<article class="post-content">{text}</article></div>')


class BrowserContractTests(unittest.TestCase):
    def test_account_identity_accepts_real_right_panel_card(self):
        from types import SimpleNamespace
        page = ('<div id="nsk-right-panel-container"><div class="user-card">'
                '<div class="user-head"><a href="/space/40573">Avatar</a>'
                '<div class="menu"><a href="/space/40573">lihaorr</a></div>'
                '</div></div></div>')
        self.assertIsNone(assert_account(SimpleNamespace(page_source=page), "40573"))
        with self.assertRaises(PageBlocked):
            assert_account(SimpleNamespace(page_source=page), "42")

    def test_account_identity_rejects_profile_links_outside_account_card(self):
        from types import SimpleNamespace
        page = ('<div id="nsk-right-panel-container"><div class="user-card">'
                '<div class="user-head"><a href="/space/7">Other</a></div></div>'
                '<div class="new-users"><a href="/space/40573">New member</a></div></div>')
        with self.assertRaises(PageBlocked):
            assert_account(SimpleNamespace(page_source=page), "40573")

    def test_blocked_page_reports_fixed_category_without_raw_title(self):
        from types import SimpleNamespace
        for markup, category in [
                ('<title>Just a moment... private-detail</title>', 'site_verification'),
                ('<title>429 Too many requests private-detail</title>', 'rate_limited'),
                ('<title>403 Forbidden private-detail</title>', 'access_denied')]:
            with self.subTest(category=category), self.assertRaises(PageBlocked) as caught:
                ensure_page(SimpleNamespace(page_source=markup))
            self.assertIn(category, str(caught.exception))
            self.assertNotIn('private-detail', str(caught.exception))

    def test_challenge_page_aborts_instead_of_attempting_editor_or_checkin(self):
        driver = Mock(page_source='<html><title>Just a moment...</title></html>')
        with self.assertRaises(PageBlocked):
            ensure_page(driver)

    def test_chinese_challenge_title_stops_without_requiring_a_form_marker(self):
        for title in ('请稍候...', '请稍等...'):
            with self.subTest(title=title):
                driver = Mock(page_source=f'<html><title>{title}</title>'
                              '<h2>正在进行安全验证</h2></html>')
                with self.assertRaisesRegex(PageBlocked, 'page=site_verification'):
                    ensure_page(driver)

    def test_account_identity_must_be_from_header_not_an_author_or_mention(self):
        driver = Mock(page_source='<header><a href="/space/12">Other</a></header>'
                      + html_reply("reply-1", "42", "test"))
        with self.assertRaises(PageBlocked):
            assert_account(driver, "42")

    def test_confirmation_needs_stable_new_reply_id_exact_text_and_own_author(self):
        page = (html_reply("post-1", "7", "original")
                + html_reply("102", "42", "参与一下")
                + html_reply("103", "7", "参与一下")
                + html_reply("104", "42", "别的内容"))
        self.assertEqual(reply_entries(page, "42", "参与一下"), {"102"})
        self.assertEqual(reply_entries(html_reply("", "42", "参与一下"), "42", "参与一下"), set())

    def test_failed_reward_click_is_not_reported_as_success(self):
        driver = Mock(page_source='<header><span title="签到"></span></header>')
        with patch("browser_actions.WebDriverWait") as wait:
            wait.return_value.until.side_effect = TimeoutError("no reward button")
            self.assertEqual(nodeseek_daily.click_sign_icon(driver), "unknown")

    def test_false_string_selects_fixed_checkin_reward(self):
        import os
        from browser_actions import reward_xpath
        with patch.dict(os.environ, {"NS_RANDOM": "false"}):
            self.assertIn("鸡腿", reward_xpath())
            self.assertNotIn("试试手气", reward_xpath())

    def test_ended_current_body_is_skipped_before_editor_is_filled(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        candidate = Post("1", "抽奖", "https://www.nodeseek.com/post-1-1", "回复参与", now - timedelta(hours=1))
        from forum_fixtures import original
        driver = Mock(page_source=original('1', body='已开奖，感谢大家参与'))
        with patch("browser_actions.WebDriverWait") as wait:
            wait.return_value.until.return_value = True
            self.assertIsNone(prepare_reply(driver, candidate, "参与一下", "42"))
        driver.execute_script.assert_not_called()

    def test_recent_candidate_cannot_override_an_old_original_publication_date(self):
        from forum_fixtures import original
        candidate = Post('1', '抽奖', 'https://www.nodeseek.com/post-1-1', '回复参与', datetime.now(timezone.utc))
        driver = Mock(page_source=original('1', published='2026-01-01T00:00:00Z'))
        with patch('browser_actions.WebDriverWait') as wait:
            wait.return_value.until.return_value = True
            self.assertIsNone(prepare_reply(driver, candidate, '参与一下', '42'))
        driver.execute_script.assert_not_called()


class LiveOrchestrationTests(unittest.TestCase):
    def test_checkin_failure_does_not_prevent_comment_task_and_browser_is_closed(self):
        driver = Mock()
        store = Mock()
        state = empty_state()
        state["account_id"] = "42"
        store.load.return_value = state
        with patch.object(nodeseek_daily, "setup_driver_and_cookies", return_value=driver), \
             patch.object(nodeseek_daily, "assert_account"), \
             patch.object(nodeseek_daily, "click_sign_icon", return_value="unknown"), \
             patch.object(nodeseek_daily, "discover_posts", return_value=nodeseek_daily.DiscoveryResult([], {})), \
             patch.object(nodeseek_daily, "run_replies", return_value={"halted": None}) as replies:
            code = nodeseek_daily.run_live(store, "42")
        replies.assert_called_once()
        driver.quit.assert_called_once()
        self.assertEqual(code, 1)  # Incomplete check-in must be visible to Actions.

    def test_search_failure_still_attempts_checkin_and_closes_browser(self):
        driver = Mock()
        store = Mock()
        state = empty_state()
        state["account_id"] = "42"
        store.load.return_value = state
        with patch.object(nodeseek_daily, "setup_driver_and_cookies", return_value=driver), \
             patch.object(nodeseek_daily, "assert_account"), \
             patch.object(nodeseek_daily, "click_sign_icon", return_value="confirmed") as checkin, \
             patch.object(nodeseek_daily, "discover_posts", side_effect=RuntimeError("Search unavailable")):
            self.assertEqual(nodeseek_daily.run_live(store, "42"), 1)
        checkin.assert_called_once()
        driver.quit.assert_called_once()

    def test_account_change_aborts_before_browser_initialization(self):
        store = Mock()
        state = empty_state()
        state["account_id"] = "7"
        store.load.return_value = state
        with patch.object(nodeseek_daily, "setup_driver_and_cookies") as setup:
            with self.assertRaises(ValueError):
                nodeseek_daily.run_live(store, "42")
        setup.assert_not_called()

    def test_search_preview_never_checks_in_prepares_publishes_or_saves_state(self):
        import io
        from contextlib import redirect_stdout
        from test_discovery import NOW
        from discovery import DiscoveryResult
        store, driver = Mock(), Mock()
        store.load.return_value = empty_state()
        post = Post('12', '抽奖福利', 'https://www.nodeseek.com/post-12-1', '回复参与抽奖', NOW)
        with patch.object(nodeseek_daily, 'setup_driver_and_cookies', return_value=driver), \
             patch.object(nodeseek_daily, 'assert_account'), \
             patch.object(nodeseek_daily, 'utc_now', return_value=NOW), \
             patch.object(nodeseek_daily, 'discover_posts', return_value=DiscoveryResult([post], {})), \
             patch.object(nodeseek_daily, 'click_sign_icon') as sign, \
             patch.object(nodeseek_daily, 'prepare_reply') as prepare, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(nodeseek_daily.run_search_preview(store, '42'), 0)
        self.assertIn('search-preview', out.getvalue())
        sign.assert_not_called()
        prepare.assert_not_called()
        store.save.assert_not_called()
        driver.quit.assert_called_once()

    def test_search_configuration_is_bounded_and_terms_deduplicated(self):
        import os
        with patch.dict(os.environ, {'NS_SEARCH_KEYWORDS': '抽奖|盖楼|抽奖', 'NS_SEARCH_PAGES': '2', 'NS_RECENT_PAGES': '5'}):
            self.assertEqual(nodeseek_daily.discovery_options()['keywords'], ('抽奖', '盖楼'))
        for config in [{'NS_SEARCH_PAGES': '100'}, {'NS_RECENT_PAGES': '0'}, {'NS_SEARCH_KEYWORDS': '抽'}]:
            with patch.dict(os.environ, config), self.assertRaises(ValueError):
                nodeseek_daily.discovery_options()

    def test_full_daily_quota_skips_search_but_still_checks_in(self):
        store, driver = Mock(), Mock()
        state = empty_state()
        day = nodeseek_daily.beijing_day(nodeseek_daily.utc_now())
        state['account_id'] = '42'
        state['replies'] = {str(i): {'status': 'confirmed', 'quota_dates': [day]} for i in range(10)}
        store.load.return_value = state
        with patch.object(nodeseek_daily, 'setup_driver_and_cookies', return_value=driver), \
             patch.object(nodeseek_daily, 'assert_account'), \
             patch.object(nodeseek_daily, 'click_sign_icon', return_value='confirmed') as sign, \
             patch.object(nodeseek_daily, 'discover_posts') as search, \
             patch.object(nodeseek_daily, 'run_replies', return_value={'halted': None}):
            self.assertEqual(nodeseek_daily.run_live(store, '42'), 0)
        sign.assert_called_once()
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
