import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from lottery import default_comments, eligible
import discovery
import browser_actions
from forum_fixtures import listing, original


NOW = datetime(2026, 11, 25, 8, tzinfo=timezone.utc)
BASE = "https://www.nodeseek.com"


class DiscoveryParsingTests(unittest.TestCase):
    def test_ten_unique_short_comments(self):
        self.assertEqual(len(set(default_comments)), 10)
        self.assertTrue(all(3 <= len(text) <= 5 for text in default_comments))

    def test_search_pagination_preserves_term_and_canonicalizes_post_links(self):
        page = discovery.parse_listing(listing([("12", "抽奖")], '/search?q=抽奖&page=2'),
                                       BASE + '/search?q=抽奖', query="抽奖")
        self.assertEqual([p.id for p in page.links], ["12"])
        self.assertEqual(page.links[0].url, BASE + '/post-12-1')
        self.assertIn('page=2', page.next_url)

    def test_empty_results_stop_even_when_next_link_is_wrong(self):
        page = discovery.parse_listing(listing(next_href='/search?q=抽奖&page=2'),
                                       BASE + '/search?q=抽奖', query="抽奖")
        self.assertIsNone(page.next_url)

    def test_next_links_cannot_leave_site_change_term_or_repeat_page(self):
        for href in ['https://evil.test/search?q=抽奖&page=2', '/search?q=交易&page=2',
                     '/search?q=抽奖&page=1', '/search?q=抽奖&page=99']:
            with self.subTest(href=href), self.assertRaises(discovery.DiscoveryError):
                discovery.parse_listing(listing([("12", "抽奖")], href),
                                        BASE + '/search?q=抽奖', query="抽奖")

    def test_newest_pagination_retains_explicit_sort(self):
        page = discovery.parse_listing(listing([("12", "盖楼")], '/page-2', newest=True),
                                       BASE + '/?sortBy=postTime', newest=True)
        self.assertEqual(page.next_url, BASE + '/page-2?sortBy=postTime')
        with self.assertRaises(discovery.DiscoveryError):
            discovery.parse_listing(listing([("12", "盖楼")]), BASE + '/?sortBy=postTime', newest=True)

    def test_no_frame_rate_limits_and_bad_query_are_failures_not_empty_success(self):
        for html in ['<h1>登录</h1>', listing().replace('<ul', '搜索词太短<ul'),
                     listing().replace('<ul', '今日搜索次数已用完<ul'), '<title>429 Too Many Requests</title>']:
            with self.subTest(html=html), self.assertRaises(discovery.DiscoveryError):
                discovery.parse_listing(html, BASE + '/search?q=抽奖', query="抽奖")

    def test_original_date_cannot_be_replaced_by_latest_reply_or_edit_date(self):
        link = discovery.PostLink("12", "抽奖", BASE + '/post-12-1')
        html = original("12", published='2026-10-01T00:00:00Z').replace('</article>',
                   '</article><span class="date-updated"><time datetime="2026-11-25T07:59:00Z"></time></span>')
        post = discovery.parse_original(html, link)
        self.assertFalse(eligible(post, NOW, full=True))
        with self.assertRaises(discovery.DiscoveryError):
            discovery.parse_original(original("12", published='2026-11-25T07:00:00'), link)

    def test_original_identity_and_date_are_mandatory(self):
        link = discovery.PostLink("12", "抽奖", BASE + '/post-12-1')
        for html in [original("13"), original("12").replace('date-created', 'date-updated')]:
            with self.assertRaises(discovery.DiscoveryError):
                discovery.parse_original(html, link)

    def test_official_draw_link_with_past_timestamp_is_skipped(self):
        link = discovery.PostLink("12", "抽奖", BASE + '/post-12-1')
        stamp = int(datetime(2026, 11, 25, 6, tzinfo=timezone.utc).timestamp() * 1000)
        post = discovery.parse_original(original("12", body=f'回复即可参与抽奖<a href="/lucky?post=12&time={stamp}&count=1">开奖链接</a>'), link)
        self.assertFalse(eligible(post, NOW, full=True))


class BrowserDiscoveryTests(unittest.TestCase):
    def discover(self, pages, **kwargs):
        driver = SimpleNamespace(page_source='', current_url='', visits=[])
        def get(url):
            driver.visits.append(url)
            driver.page_source = pages[url]
            driver.current_url = url
        driver.get = get
        with patch.object(browser_actions, 'WebDriverWait') as wait:
            wait.return_value.until.side_effect = lambda predicate: predicate(driver)
            result = browser_actions.discover_posts(driver, '42', now=lambda: NOW,
                                                    pause_seconds=0, **kwargs)
        return result, driver.visits

    def test_discovers_beyond_rss_and_deduplicates_keywords_pages_and_old_bumps(self):
        pages = {
            BASE + '/?sortBy=postTime': listing([('11', '盖楼福利'), ('99', '技术交流')], '/page-2', newest=True),
            BASE + '/page-2?sortBy=postTime': listing([('12', '送鸡抽奖')], newest=True),
            BASE + '/search?q=%E6%8A%BD%E5%A5%96': listing([('12', '送鸡抽奖'), ('13', '抽奖')]),
            BASE + '/search?q=%E7%9B%96%E6%A5%BC': listing([('11', '盖楼'), ('14', '抽奖')]),
            BASE + '/post-11-1': original('11'),
            BASE + '/post-12-1': original('12'),
            BASE + '/post-13-1': original('13', published='2026-10-01T00:00:00Z'),
        }
        result, visits = self.discover(pages, keywords=('抽奖', '盖楼'), recent_pages=2,
                                      search_pages=1, exclude_ids={'14'})
        self.assertEqual([p.id for p in result.posts], ['11', '12'])
        self.assertEqual(visits.count(BASE + '/post-12-1'), 1)
        self.assertEqual(result.report['inspected'], 3)

    def test_repeated_results_stop_paging_and_inspection_limit_is_visible(self):
        pages = {
            BASE + '/?sortBy=postTime': listing([('11', '抽奖'), ('12', '抽奖')], newest=True),
            BASE + '/search?q=%E6%8A%BD%E5%A5%96': listing([('11', '抽奖')], '/search?q=抽奖&page=2'),
            BASE + '/search?q=%E6%8A%BD%E5%A5%96&page=2': listing([('11', '抽奖')], '/search?q=抽奖&page=3'),
            BASE + '/post-11-1': original('11'),
        }
        result, visits = self.discover(pages, recent_pages=1, search_pages=3, max_inspections=1)
        self.assertEqual(len(visits), 4)
        self.assertTrue(result.report['inspection_limit_reached'])
        self.assertEqual(result.report['stops']['search:抽奖'], 'repeated_page')

    def test_redirect_to_guest_google_search_is_reported_not_silently_empty(self):
        driver = SimpleNamespace(page_source=listing(), current_url='https://www.google.com/search?q=x')
        driver.get = lambda _: None
        with self.assertRaises(browser_actions.PageBlocked):
            browser_actions.discover_posts(driver, '42', recent_pages=1, pause_seconds=0)

    def test_rate_limit_stops_without_retry_and_requests_are_spaced(self):
        driver = SimpleNamespace(page_source='', current_url='', visits=[])
        def get(url):
            driver.current_url = url
            driver.visits.append(url)
            driver.page_source = listing(newest=True) if len(driver.visits) == 1 else '<title>429 Too Many Requests</title>'
        driver.get = get
        from unittest.mock import Mock
        sleep = Mock()
        with patch.object(browser_actions, 'WebDriverWait') as wait:
            wait.return_value.until.side_effect = lambda predicate: predicate(driver)
            with self.assertRaises(browser_actions.PageBlocked):
                browser_actions.discover_posts(driver, '42', recent_pages=1, sleep=sleep)
        self.assertEqual(len(driver.visits), 2)
        sleep.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
