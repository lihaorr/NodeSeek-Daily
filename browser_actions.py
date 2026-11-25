"""Browser adapters. Unexpected markup or a challenge stops account actions."""
import os
import time
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from lottery import SIGNAL, eligible, plain_text, utc_now
from discovery import BASE_URL, DiscoveryResult, parse_listing, parse_original, search_url


class PageBlocked(RuntimeError):
    pass


def ensure_page(driver):
    soup = BeautifulSoup(driver.page_source, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    category = None
    if (any(text in title for text in ("just a moment", "attention required"))
            or soup.select_one("#challenge-running, #cf-challenge-running, #challenge-form")):
        category = "site_verification"
    elif any(text in title for text in ("too many requests", "429")):
        category = "rate_limited"
    elif any(text in title for text in ("access denied", "403 forbidden")):
        category = "access_denied"
    if category:
        # Fixed categories are useful in public CI logs; never print page content.
        raise PageBlocked(f"page={category}；遇到访问受限或站点验证页，停止操作；请人工检查运行环境")
    return soup


def profile_id(link):
    if not link:
        return None
    parts = urlsplit(link)
    if parts.netloc and parts.netloc not in {"www.nodeseek.com", "nodeseek.com"}:
        return None
    import re
    match = re.fullmatch(r"/space/([1-9]\d*)/?", parts.path)
    return match.group(1) if match else None


def assert_account(driver, user_id):
    soup = ensure_page(driver)
    links = soup.select("header a[href], nav a[href], .user-panel a[href], .nsk-header a[href], #nsk-head a[href], "
                        "#nsk-right-panel-container > .user-card .user-head a[href]")
    if not any(profile_id(link.get("href")) == user_id for link in links):
        raise PageBlocked("无法从导航栏或账号卡片确认当前登录账号与 NS_USER_ID 一致，停止操作")


def author_id(node):
    author = node.select_one(".author-name a[href], a.author-name[href]")
    return profile_id(author.get("href")) if author else None


def reply_entries(html, user_id, text=None):
    """Only stable IDs with an exact author/content match can confirm a reply."""
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for node in soup.select('.content-item:not([id="0"])'):
        if author_id(node) != user_id:
            continue
        content = node.select_one(".post-content")
        if content is None or (text is not None and plain_text(str(content)) != text.strip()):
            continue
        identifier = node.get("data-comment-id")
        if identifier and identifier.isdigit():
            found.add(identifier)
    return found


def prepare_reply(driver, post, comment, user_id):
    driver.get(post.url)

    def loaded(browser):
        ensure_page(browser)
        return browser.find_elements(By.CSS_SELECTOR, '.content-item[id="0"] article.post-content')

    WebDriverWait(driver, 20).until(loaded)
    assert_account(driver, user_id)
    soup = ensure_page(driver)
    original = soup.select_one('.content-item[id="0"]')
    current = parse_original(driver.page_source, post)
    if author_id(original) is None:
        raise PageBlocked("原帖结构无法可靠识别，未发布评论")
    if not eligible(current, utc_now(), full=True) or author_id(original) == user_id:
        return None
    # Also avoid visible manual participation by this account, regardless of wording.
    if any(author_id(node) == user_id for node in soup.select(".content-item")):
        return None
    before = reply_entries(driver.page_source, user_id, comment)
    editor = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".CodeMirror")))
    filled = driver.execute_script("""
        const cm = arguments[0].CodeMirror;
        if (!cm || cm.getValue().trim()) return false;
        cm.setValue(arguments[1]);
        return cm.getValue() === arguments[1];
    """, editor, comment)
    if filled is not True:
        raise PageBlocked("无法确认编辑器内容，未发布评论")
    button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH,
        "//button[contains(@class,'submit') and contains(@class,'btn') and contains(.,'发布评论')]")))

    def publish():
        # The caller has durably checkpointed a pending record before invoking this.
        button.click()
        def confirmed(browser):
            ensure_page(browser)
            return reply_entries(browser.page_source, user_id, comment) - before
        try:
            new_ids = WebDriverWait(driver, 20).until(confirmed)
            # A client may optimistically add a comment before the server accepts it.
            driver.refresh()
            assert_account(driver, user_id)
            def persisted(browser):
                ensure_page(browser)
                return reply_entries(browser.page_source, user_id, comment) & new_ids
            WebDriverWait(driver, 20).until(persisted)
            return "confirmed"
        except TimeoutException:
            return "unknown"
    return publish


def discover_posts(driver, user_id, *, keywords=("抽奖",), recent_pages=5, search_pages=2,
                   max_inspections=40, exclude_ids=(), pause_seconds=3, sleep=time.sleep, now=utc_now):
    """Read only: list/search pages, then actual original dates and participation rules."""
    report = {"pages": {}, "stops": {}, "inspected": 0, "inspection_limit_reached": False}
    visits = 0

    def read(url):
        nonlocal visits
        if visits and pause_seconds:
            sleep(pause_seconds)
        visits += 1
        driver.get(url)
        ensure_page(driver)
        actual, expected = urlsplit(driver.current_url), urlsplit(url)
        if (actual.scheme, actual.netloc, actual.path, parse_qs(actual.query)) != (
                expected.scheme, expected.netloc, expected.path, parse_qs(expected.query)):
            raise PageBlocked("论坛页面发生重定向，可能登录已失效；未将其视作零结果")
        WebDriverWait(driver, 20).until(lambda d: ensure_page(d).select_one("#nsk-frame"))
        assert_account(driver, user_id)
        return driver.page_source

    links = {}
    sources = [("newest", BASE_URL + "/?sortBy=postTime", recent_pages, None)]
    sources += [("search:" + word, search_url(word), search_pages, word) for word in keywords]
    for source, url, limit, query in sources:
        signatures = set()
        report["pages"][source] = 0
        for _ in range(limit):
            page = parse_listing(read(url), url, query=query, newest=query is None)
            report["pages"][source] += 1
            signature = tuple(link.id for link in page.links)
            if signature in signatures:
                report["stops"][source] = "repeated_page"
                break
            signatures.add(signature)
            for link in page.links:
                if link.id not in exclude_ids and (query is not None or SIGNAL.search(link.title)):
                    links.setdefault(link.id, link)
            if page.next_url is None:
                report["stops"][source] = "end"
                break
            url = page.next_url
        else:
            report["stops"][source] = "page_limit"
    report["candidate_links"] = len(links)
    report["inspection_limit_reached"] = len(links) > max_inspections
    posts = []
    for link in list(links.values())[:max_inspections]:
        html = read(link.url)
        post = parse_original(html, link)
        report["inspected"] += 1
        soup = BeautifulSoup(html, "html.parser")
        if (eligible(post, now(), full=True)
                and not any(author_id(node) == user_id for node in soup.select(".content-item"))):
            posts.append(post)
    return DiscoveryResult(posts, report)


def reward_xpath():
    if os.environ.get("NS_RANDOM", "false").strip().lower() == "true":
        return "//button[contains(.,'试试手气')]"
    return "//button[contains(.,'鸡腿 x 5') or contains(.,'鸡腿 × 5')]"


def checkin_status(driver):
    ensure_page(driver)
    # Restrict confirmation to feedback UI; a forum post mentioning check-in is not proof.
    for feedback in driver.find_elements(By.CSS_SELECTOR,
            ".msc-confirm, .msc-alert, .toast, .message, [role='alert'], .sign-panel"):
        if not feedback.is_displayed():
            continue
        text = feedback.text
        if "签到成功" in text:
            return "confirmed"
        if any(word in text for word in ("今日已签到", "今天已签到", "今天已经签到")):
            return "already"
    return None


def click_sign_icon(driver):
    try:
        ensure_page(driver)
        icon = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//span[@title='签到']")))
        icon.click()
        def reward_or_status(browser):
            return checkin_status(browser) or EC.element_to_be_clickable((By.XPATH, reward_xpath()))(browser)
        selection = WebDriverWait(driver, 10).until(reward_or_status)
        if isinstance(selection, str):
            return selection
        selection.click()
        return WebDriverWait(driver, 15).until(checkin_status)
    except PageBlocked:
        raise
    except Exception as error:
        print(f"签到结果未确认：{type(error).__name__}")
        return "unknown"
