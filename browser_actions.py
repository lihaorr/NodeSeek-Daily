"""Browser adapters. Unexpected markup or a challenge stops account actions."""
import os
from dataclasses import replace
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from lottery import eligible, plain_text, utc_now


class PageBlocked(RuntimeError):
    pass


def ensure_page(driver):
    soup = BeautifulSoup(driver.page_source, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if (any(text in title for text in ("just a moment", "attention required", "access denied"))
            or soup.select_one("#challenge-running, #cf-challenge-running, #challenge-form")):
        raise PageBlocked("遇到站点验证页，停止操作；请人工检查运行环境")
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
    links = soup.select("header a[href], nav a[href], .user-panel a[href], .nsk-header a[href]")
    if not any(profile_id(link.get("href")) == user_id for link in links):
        raise PageBlocked("无法从导航栏确认当前登录账号与 NS_USER_ID 一致，停止操作")


def author_id(node):
    author = node.select_one(".author-name a[href], a.author-name[href]")
    return profile_id(author.get("href")) if author else None


def reply_entries(html, user_id, text=None):
    """Only stable IDs with an exact author/content match can confirm a reply."""
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for node in soup.select(".nsk-post"):
        if author_id(node) != user_id:
            continue
        content = node.select_one(".post-content")
        if content is None or (text is not None and plain_text(str(content)) != text.strip()):
            continue
        identifier = node.get("id")
        if not identifier:
            anchor = node.select_one('a[href*="#"]')
            identifier = urlsplit(anchor.get("href", "")).fragment if anchor else None
        if identifier:
            found.add(identifier)
    return found


def prepare_reply(driver, post, comment, user_id):
    driver.get(post.url)

    def loaded(browser):
        ensure_page(browser)
        return browser.find_elements(By.CSS_SELECTOR, ".nsk-post .post-content")

    WebDriverWait(driver, 20).until(loaded)
    assert_account(driver, user_id)
    soup = ensure_page(driver)
    original = soup.select_one(".nsk-post")
    content = original.select_one(".post-content") if original else None
    title = soup.select_one("h1")
    if content is None or title is None or author_id(original) is None:
        raise PageBlocked("原帖结构无法可靠识别，未发布评论")
    current = replace(post, title=title.get_text(" ", strip=True), body=plain_text(str(content)))
    if not eligible(current, utc_now(), full=True) or author_id(original) == user_id:
        return None
    # Also avoid visible manual participation by this account, regardless of wording.
    if any(author_id(node) == user_id for node in soup.select(".nsk-post")):
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
