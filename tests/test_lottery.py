import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lottery import Post, default_comments, eligible, parse_feed, run_replies
from state_store import FileStateStore


NOW = datetime(2026, 11, 25, 8, tzinfo=timezone.utc)


def post(number, title="抽奖送一台小鸡", body="评论参与，随机抽取一位。", age=1):
    return Post(str(number), title, f"https://www.nodeseek.com/post-{number}-1",
                body, NOW - timedelta(hours=age))


class LotteryRulesTests(unittest.TestCase):
    def test_identifies_giveaway_synonyms_but_rejects_ended_or_unrelated_posts(self):
        cases = [
            ("黑五抽奖", "回帖参与", True),
            ("盖楼送鸡", "随机抽一位评论的朋友", True),
            ("Giveaway", "回帖即可参加", True),
            ("福利：随机送一台服务器", "评论参与", True),
            ("抽一台 VPS", "回帖参加", True),
            ("抽奖已结束", "评论参与", False),
            ("抽奖", "已开奖，中奖名单如下", False),
            ("求推荐抽奖工具", "怎么统计评论？", False),
            ("抽奖算法分享", "评论讨论", False),
            ("便宜 VPS 出售", "评论参与讨论", False),
        ]
        for title, body, want in cases:
            with self.subTest(title=title):
                self.assertEqual(eligible(post(1, title, body), NOW), want)

    def test_full_post_requires_general_forum_participation_and_current_age(self):
        self.assertFalse(eligible(post(1, body="前往 Telegram 群参加抽奖"), NOW, full=True))
        self.assertFalse(eligible(post(1, body="评论口令：我要中奖"), NOW, full=True))
        self.assertFalse(eligible(post(1, age=25), NOW))
        self.assertFalse(eligible(post(1, age=-1), NOW))
        self.assertTrue(eligible(post(1, body="回复参与，明晚开奖"), NOW, full=True))

    def test_explicit_past_deadline_is_skipped_without_ended_label(self):
        self.assertFalse(eligible(post(1, body="回复参与，开奖时间：2026-11-24 20:00"), NOW, full=True))
        self.assertFalse(eligible(post(1, body="回复参与，11月25日 12:00 开奖"), NOW, full=True))
        self.assertTrue(eligible(post(1, body="回复参与，2026-11-26 20:00 开奖"), NOW, full=True))

    def test_feed_canonicalizes_and_deduplicates_posts_and_ignores_unsafe_or_undated_links(self):
        xml = '''<rss><channel>
          <item><title>抽奖</title><description>&lt;p&gt;回帖参与&lt;/p&gt;</description>
            <link>https://www.nodeseek.com/post-42-2#99</link><pubDate>Wed, 25 Nov 2026 07:00:00 GMT</pubDate></item>
          <item><title>重复</title><link>https://www.nodeseek.com/post-42-1</link><pubDate>Wed, 25 Nov 2026 07:00:00 GMT</pubDate></item>
          <item><title>抽奖</title><link>https://evil.example/post-43-1</link><pubDate>Wed, 25 Nov 2026 07:00:00 GMT</pubDate></item>
          <item><title>抽奖</title><link>https://www.nodeseek.com/post-44-1</link></item>
        </channel></rss>'''
        items = parse_feed(xml)
        self.assertEqual([(p.id, p.url, p.body) for p in items],
                         [("42", "https://www.nodeseek.com/post-42-1", "回帖参与")])


class ReplyBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "state.json"
        self.store = FileStateStore(self.path)
        self.sent = []

    def prepare(self, candidate, comment):
        def publish():
            # A disk checkpoint must exist before the external action starts.
            checkpoint = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["replies"][candidate.id]["status"], "pending")
            self.sent.append((candidate.id, comment))
            return "confirmed"
        return publish

    def run_batch(self, posts, **kwargs):
        return run_replies(posts, self.store, kwargs.pop("prepare", self.prepare),
                           now=kwargs.pop("now", lambda: NOW), **kwargs)

    def test_default_preview_does_not_prepare_publish_or_change_state(self):
        result = self.run_batch([post(1)], prepare=lambda *_: self.fail("preview touched browser"))
        self.assertEqual(len(result["preview"]), 1)
        self.assertIn(result["preview"][0]["comment"], default_comments)
        self.assertFalse(self.path.exists())

    def test_hard_cap_is_ten_across_multiple_runs_not_ten_per_run(self):
        self.run_batch([post(i) for i in range(1, 8)], live=True)
        self.run_batch([post(i) for i in range(8, 20)], live=True)
        self.assertEqual([p[0] for p in self.sent], [str(i) for i in range(1, 11)])

    def test_daily_count_resets_at_beijing_midnight_but_post_history_remains(self):
        self.run_batch([post(1)], live=True)
        tomorrow = NOW + timedelta(hours=16)
        self.run_batch([post(1), post(2, age=-15)], live=True, now=lambda: tomorrow)
        self.assertEqual([p[0] for p in self.sent], ["1", "2"])

    def test_no_new_eligible_posts_never_calls_prepare(self):
        self.run_batch([post(1)], live=True)
        result = self.run_batch([post(1), post(2, title="机器出售", body="明盘 100 元"), post(3, age=30)],
                                live=True, prepare=lambda *_: self.fail("no eligible new posts"))
        self.assertEqual(result["confirmed"], [])

    def test_unknown_submission_is_persisted_stops_batch_and_is_never_retried(self):
        result = self.run_batch([post(1), post(2)], live=True,
                                prepare=lambda *_: lambda: "unknown")
        self.assertEqual(result["halted"], "unknown")
        self.assertEqual(self.store.load()["replies"]["1"]["status"], "unknown")
        self.run_batch([post(1)], live=True, prepare=lambda *_: self.fail("duplicate"))

    def test_checkpoint_write_failure_prevents_publication(self):
        class BrokenStore(FileStateStore):
            def save(self, state):
                raise OSError("disk full")
        with self.assertRaises(OSError):
            run_replies([post(1)], BrokenStore(self.path), self.prepare, live=True, now=lambda: NOW)
        self.assertEqual(self.sent, [])

    def test_submission_exception_leaves_unknown_record_and_stops(self):
        def error():
            raise TimeoutError("connection lost after click")
        self.run_batch([post(1), post(2)], live=True, prepare=lambda *_: error)
        self.assertEqual(self.store.load()["replies"]["1"]["status"], "unknown")

    def test_cross_midnight_submission_reserves_both_calendar_dates(self):
        before = datetime(2026, 11, 25, 15, 59, 59, tzinfo=timezone.utc)
        after = before + timedelta(seconds=2)
        current = [before]
        def prepare(*_):
            def submit():
                current[0] = after
                return "confirmed"
            return submit
        self.run_batch([post(1)], live=True, prepare=prepare, now=lambda: current[0])
        self.assertEqual(self.store.load()["replies"]["1"]["quota_dates"], ["2026-11-25", "2026-11-26"])

    def test_duplicate_feed_items_are_only_published_once(self):
        self.run_batch([post(1), post(1)], live=True)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
