# -- coding: utf-8 --
"""NodeSeek check-in and lottery replies. Default execution is read-only preview.

Copyright (c) 2024 [Hosea]. Licensed under the MIT License.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

import setuptools  # noqa: F401  # undetected-chromedriver needs distutils on recent Python.
import undetected_chromedriver as uc
from dotenv import load_dotenv

from browser_actions import PageBlocked, assert_account, click_sign_icon, discover_posts, ensure_page, prepare_reply
from discovery import DiscoveryError, DiscoveryResult
from lottery import DAILY_LIMIT, beijing_day, default_comments, fetch_posts, parse_feed, run_replies, used_quota, utc_now
from state_store import FileStateStore, GitHubStateStore


def detect_chrome_runtime():
    chrome_executable = os.environ.get("CHROME_PATH") or uc.find_chrome_executable()
    if not chrome_executable:
        raise RuntimeError("未找到 Chrome 或 Chromium 可执行文件")
    try:
        version_result = subprocess.run([chrome_executable, "--version"],
                                        capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return handle_chrome_version_failure(chrome_executable, str(error))
    version_output = f"{version_result.stdout} {version_result.stderr}".strip()
    version_match = re.search(r"\b(\d+)(?:\.\d+){3}\b", version_output)
    if version_result.returncode != 0 or not version_match:
        return handle_chrome_version_failure(chrome_executable, version_output or "无输出")
    return chrome_executable, int(version_match.group(1))


def handle_chrome_version_failure(chrome_executable, details):
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("无法读取 Chrome/Chromium 版本")
    print("警告：无法读取 Chrome/Chromium 版本，将使用 UC 默认版本检测")
    return chrome_executable, None


def setup_driver_and_cookies():
    driver = None
    try:
        cookie = os.environ.get("NS_COOKIE") or os.environ.get("COOKIE")
        if not cookie or not any("=" in item for item in cookie.split(";")):
            print("未找到有效 Cookie 配置")
            return None
        chrome_executable, major = detect_chrome_runtime()
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        if os.environ.get("HEADLESS", "true").strip().lower() == "true":
            options.add_argument("--headless=new")
        arguments = {"options": options, "browser_executable_path": chrome_executable}
        if major is not None:
            arguments["version_main"] = major
        driver = uc.Chrome(**arguments)
        driver.set_page_load_timeout(45)
        driver.get("https://www.nodeseek.com/")
        added = 0
        for item in cookie.split(";"):
            if "=" not in item:
                continue
            name, value = item.strip().split("=", 1)
            if name and value:
                driver.add_cookie({"name": name, "value": value, "domain": ".nodeseek.com", "path": "/"})
                added += 1
        if not added:
            raise ValueError("Cookie 中没有有效键值对")
        driver.refresh()
        ensure_page(driver)
        return driver
    except Exception as error:
        print(f"浏览器或登录初始化失败：{type(error).__name__}")
        if driver is not None:
            driver.quit()
        return None


def comment_library():
    custom = os.environ.get("NS_COMMENT_TEXTS", "").strip()
    if not custom:
        return default_comments
    comments = [part.strip() for part in custom.split("|") if part.strip()]
    if not comments:
        raise ValueError("NS_COMMENT_TEXTS 没有有效评论")
    return comments


def discovery_options():
    keywords = tuple(dict.fromkeys(word.strip() for word in
                     (os.environ.get("NS_SEARCH_KEYWORDS") or "抽奖").split("|") if word.strip()))
    if not 1 <= len(keywords) <= 5 or any(not 2 <= len(word) <= 30 for word in keywords):
        raise ValueError("NS_SEARCH_KEYWORDS 需 1–5 个关键词，每个 2–30 字，用 | 分隔")
    try:
        recent = int(os.environ.get("NS_RECENT_PAGES") or "5")
        search = int(os.environ.get("NS_SEARCH_PAGES") or "2")
    except ValueError as error:
        raise ValueError("搜索页数必须是整数") from error
    if not 1 <= recent <= 20 or not 1 <= search <= 3:
        raise ValueError("NS_RECENT_PAGES 范围 1–20；NS_SEARCH_PAGES 范围 1–3")
    return {"keywords": keywords, "recent_pages": recent, "search_pages": search}


def run_search_preview(store, user_id):
    options = discovery_options()
    state = store.load()
    if state["account_id"] not in {None, user_id}:
        raise ValueError("状态已绑定另一个账号，请使用独立状态文件/分支")
    driver = setup_driver_and_cookies()
    if driver is None:
        return 1
    try:
        assert_account(driver, user_id)
        discovery = discover_posts(driver, user_id, exclude_ids=set(state["replies"]), **options)
        moment = utc_now()
        result = run_replies(discovery.posts, store, None, comments=comment_library(), now=lambda: moment)
        for item in result["preview"]:
            item["validation"] = "已读取原帖；未填写或发布评论"
        print(json.dumps({"mode": "search-preview", "discovery": discovery.report,
                          "beijing_date": beijing_day(moment), **result}, ensure_ascii=False, indent=2))
        return 0
    finally:
        driver.quit()


def run_live(store, user_id):
    options = discovery_options()
    state = store.load()
    if state["account_id"] not in {None, user_id}:
        raise ValueError("状态已绑定另一个账号，请使用独立状态文件/分支")
    driver = setup_driver_and_cookies()
    if driver is None:
        return 1
    try:
        assert_account(driver, user_id)
        if state["account_id"] is None:
            state["account_id"] = user_id
            store.save(state)
        day = beijing_day(utc_now())
        sign_status = state["checkins"].get(day)
        if not sign_status:
            # A check-in failure must not suppress discovery/comments unless the page is blocked.
            sign_status = click_sign_icon(driver)
            if sign_status in {"confirmed", "already"}:
                state["checkins"][beijing_day(utc_now())] = sign_status
                store.save(state)
        print(f"签到结果：{sign_status}")
        if used_quota(state, beijing_day(utc_now())) >= DAILY_LIMIT:
            discovery = DiscoveryResult([], {"skipped": "daily_quota_full"})
        else:
            discovery = discover_posts(driver, user_id, exclude_ids=set(state["replies"]), **options)
        result = run_replies(discovery.posts, store,
                             lambda post, text: prepare_reply(driver, post, text, user_id),
                             live=True, comments=comment_library(), pause_seconds=60)
        print(json.dumps({"discovery": discovery.report, **result}, ensure_ascii=False, indent=2))
        return 0 if sign_status in {"confirmed", "already"} and result["halted"] is None else 1
    except Exception as error:
        print(f"任务停止：{type(error).__name__}；未确认结果不会自动重试")
        if isinstance(error, (DiscoveryError, PageBlocked)):
            print(str(error))
        return 1
    finally:
        driver.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="NodeSeek 抽奖筛选；默认只预览，不签到、不评论")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="实际签到和评论；需 NS_COOKIE、NS_USER_ID")
    mode.add_argument("--search-preview", action="store_true", help="登录后只读搜索与原帖；不签到、不填编辑器、不写状态")
    parser.add_argument("--feed-file", type=Path, help="预览本地 RSS 样本，不访问论坛")
    parser.add_argument("--at", help="本地样本预览的 ISO 时间（必须含时区）")
    parser.add_argument("--state-file", type=Path, default=Path("state/state.json"))
    args = parser.parse_args(argv)
    load_dotenv(override=False)
    try:
        if (args.live or args.search_preview) and (args.feed_file or args.at):
            raise ValueError("样本和指定时间只能用于预览")
        if args.at and not args.feed_file:
            raise ValueError("--at 仅用于本地 RSS 样本")
        backend = os.environ.get("NS_STATE_BACKEND", "local").strip().lower()
        if backend not in {"local", "github"}:
            raise ValueError("NS_STATE_BACKEND 只支持 local 或 github，禁止静默切换存储")
        if backend == "github":
            store = GitHubStateStore(os.environ.get("GITHUB_REPOSITORY"),
                                     os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"),
                                     os.environ.get("NS_STATE_BRANCH", "automation-state"))
        else:
            store = FileStateStore(args.state_file)
        if args.live or args.search_preview:
            user_id = os.environ.get("NS_USER_ID", "").strip()
            if not re.fullmatch(r"[1-9]\d*", user_id):
                raise ValueError("浏览器搜索/实际执行需要 NS_USER_ID（个人主页 /space/ 后的数字）")
            if os.environ.get("GITHUB_EVENT_NAME") in {"pull_request", "pull_request_target"}:
                raise ValueError("PR 环境禁止账号操作")
            if args.search_preview:
                return run_search_preview(store, user_id)
            with store.lock():
                return run_live(store, user_id)
        posts = parse_feed(args.feed_file.read_bytes()) if args.feed_file else fetch_posts()
        moment = utc_now()
        if args.at:
            from datetime import datetime
            moment = datetime.fromisoformat(args.at)
            if moment.tzinfo is None:
                raise ValueError("预览时间必须包含时区")
        result = run_replies(posts, store, None, comments=comment_library(), now=lambda: moment)
        print(json.dumps({"mode": "preview", "feed_items": len(posts),
                          "beijing_date": beijing_day(moment), **result}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        # Do not log Cookie, tokens, request bodies or page HTML.
        print(f"配置或读取失败：{type(error).__name__}")
        if isinstance(error, (ValueError, PageBlocked, DiscoveryError)):
            print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
