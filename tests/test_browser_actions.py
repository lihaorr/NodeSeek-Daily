import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import setuptools  # noqa: F401
import nodeseek_daily
from browser_actions import PageBlocked, assert_account, reply_entries, ensure_page, prepare_reply
from lottery import Post
from state_store import empty_state


def html_reply(identifier, author, text):
    return (f'<div class="nsk-post" id="{identifier}"><div class="author-name">'
            f'<a href="/space/{author}">User</a></div>'
            f'<div class="post-content">{text}</div></div>')


class BrowserContractTests(unittest.TestCase):
    def test_challenge_page_aborts_instead_of_attempting_editor_or_checkin(self):
        driver = Mock(page_source='<html><title>Just a moment...</title></html>')
        with self.assertRaises(PageBlocked):
            ensure_page(driver)

    def test_account_identity_must_be_from_header_not_an_author_or_mention(self):
        driver = Mock(page_source='<header><a href="/space/12">Other</a></header>'
                      + html_reply("reply-1", "42", "test"))
        with self.assertRaises(PageBlocked):
            assert_account(driver, "42")

    def test_confirmation_needs_stable_new_reply_id_exact_text_and_own_author(self):
        page = (html_reply("post-1", "7", "original")
                + html_reply("comment-2", "42", "参与一下")
                + html_reply("comment-3", "7", "参与一下")
                + html_reply("comment-4", "42", "别的内容"))
        self.assertEqual(reply_entries(page, "42", "参与一下"), {"comment-2"})
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
        driver = Mock(page_source='<header><a href="/space/42">Me</a></header><h1>抽奖</h1>'
                      + html_reply("post-1", "7", "已开奖，感谢大家参与"))
        with patch("browser_actions.WebDriverWait") as wait:
            wait.return_value.until.return_value = True
            self.assertIsNone(prepare_reply(driver, candidate, "参与一下", "42"))
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
             patch.object(nodeseek_daily, "fetch_posts", return_value=[]), \
             patch.object(nodeseek_daily, "run_replies", return_value={"halted": None}) as replies:
            code = nodeseek_daily.run_live(store, "42")
        replies.assert_called_once()
        driver.quit.assert_called_once()
        self.assertEqual(code, 1)  # Incomplete check-in must be visible to Actions.

    def test_feed_failure_still_attempts_checkin_and_closes_browser(self):
        driver = Mock()
        store = Mock()
        state = empty_state()
        state["account_id"] = "42"
        store.load.return_value = state
        with patch.object(nodeseek_daily, "setup_driver_and_cookies", return_value=driver), \
             patch.object(nodeseek_daily, "assert_account"), \
             patch.object(nodeseek_daily, "click_sign_icon", return_value="confirmed") as checkin, \
             patch.object(nodeseek_daily, "fetch_posts", side_effect=RuntimeError("RSS unavailable")):
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


if __name__ == "__main__":
    unittest.main()
