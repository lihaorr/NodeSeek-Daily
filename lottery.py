"""Read-only feed discovery and checkpointed daily reply quota."""
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import requests


BEIJING = timezone(timedelta(hours=8))
DAILY_LIMIT = 10
FEED_URL = "https://rss.nodeseek.com/"

default_comments = [
    "感谢楼主的抽奖活动，参与一下，祝大家好运！",
    "来参加抽奖，感谢楼主送出的福利！",
    "参与一下，期待这次能有好运气。",
    "感谢分享福利，我也来试试手气！",
    "报名参与抽奖，祝活动顺利！",
    "来凑个热闹，感谢楼主，祝各位好运！",
    "支持一下抽奖活动，希望好运能轮到我。",
    "谢谢楼主的福利，参与抽奖试试运气！",
    "这次抽奖我也参加，感谢楼主！",
    "参与一波，祝大家都能收获好心情！",
]


@dataclass(frozen=True)
class Post:
    id: str
    title: str
    url: str
    body: str
    published_at: datetime


def utc_now():
    return datetime.now(timezone.utc)


def beijing_day(moment):
    return moment.astimezone(BEIJING).date().isoformat()


def canonical_post_url(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/post-([1-9]\d*)-\d+/?", parts.path)
    if (parts.scheme != "https" or parts.netloc not in {"www.nodeseek.com", "nodeseek.com"}
            or not match or parts.query):
        return None
    post_id = match.group(1)
    return post_id, f"https://www.nodeseek.com/post-{post_id}-1"


def plain_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("blockquote, script, style"):
        node.decompose()
    return soup.get_text(" ", strip=True)


def parse_feed(xml):
    root = ET.fromstring(xml)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("响应不是预期的 RSS，停止发现任务")
    result, seen = [], set()
    for item in root.findall("./channel/item"):
        target = canonical_post_url(item.findtext("link", ""))
        if not target or target[0] in seen:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
        except (ValueError, TypeError):
            continue
        if published.tzinfo is None:
            continue
        body = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
        body = body or item.findtext("description", "")
        result.append(Post(target[0], item.findtext("title", ""), target[1],
                           plain_text(body), published))
        seen.add(target[0])
    return result


def fetch_posts():
    response = requests.get(FEED_URL, timeout=30)
    response.raise_for_status()
    return parse_feed(response.content)


SIGNAL = re.compile(r"抽奖|抽獎|盖楼|蓋樓|送(?:小?鸡|小?雞)|回[帖贴]有奖|回复有奖|"
                    r"随机(?:抽|送|选)|隨機(?:抽|送|選)|抽(?:一|两|三|几|\d+)\s*(?:台|个|位|名)|"
                    r"\b(?:giveaway|raffle)\b", re.I)
CLOSED = re.compile(r"已(?:开奖|開獎|结束|結束|截止|关闭|關閉)|(?:抽奖|活動|活动|福利)(?:已)?(?:结束|結束|取消)|中奖名单|中獎名單")
IRRELEVANT = re.compile(r"(?:非|不是)抽奖|抽奖(?:工具|脚本|程序|系统|算法)|抽獎(?:工具|程式|系統)|求.*抽奖|求.*抽獎")
SPECIAL_REPLY = re.compile(r"口令|指定(?:内容|內容|回复|回覆)|(?:回[复覆]|评论|評論)格式|按.{0,12}格式|"
                           r"(?:回[复覆]|评论|評論).{0,8}[“\"「『]|(?:付费|付費|购买|購買).{0,8}(?:参与|參與)")
PARTICIPATION = re.compile(r"(?:回复|回覆|回帖|回贴|评论|評論|盖楼|蓋樓).{0,18}(?:参与|參與|参加|參加|抽|有奖|有獎)|"
                           r"(?:抽|随机|隨機).{0,18}(?:评论|評論|回帖|楼层|樓層)|盖楼|蓋樓")
DATE_TEXT = (r"(?:(?P<year>20\d{2})[-/年])?(?P<month>\d{1,2})[-/月](?P<day>\d{1,2})日?"
             r"(?:\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2}))?")
DEADLINES = [re.compile(r"(?:开奖|截止|结束)(?:时间)?\s*[:：]?\s*" + DATE_TEXT),
             re.compile(DATE_TEXT + r"\s*(?:开奖|截止|结束)")]


def expired_deadline(text, now):
    local_now = now.astimezone(BEIJING)
    for pattern in DEADLINES:
        for match in pattern.finditer(text):
            fields = match.groupdict()
            try:
                deadline = datetime(int(fields["year"] or local_now.year), int(fields["month"]),
                                    int(fields["day"]), int(fields["hour"] or 23),
                                    int(fields["minute"] or 59), 59, tzinfo=BEIJING)
            except ValueError:
                # A malformed explicitly labelled date is not a safe candidate.
                return True
            if deadline < local_now:
                return True
    return False


def eligible(post, now, full=False):
    age = now - post.published_at
    if not timedelta(0) <= age <= timedelta(hours=24):
        return False
    text = f"{post.title}\n{post.body}"
    if not SIGNAL.search(text) or CLOSED.search(text) or IRRELEVANT.search(post.title):
        return False
    if full and (SPECIAL_REPLY.search(text) or not PARTICIPATION.search(text) or expired_deadline(text, now)):
        return False
    return True


def used_quota(state, day):
    return sum(record["status"] in {"pending", "unknown"}
               or (record["status"] == "confirmed" and day in record["quota_dates"])
               for record in state["replies"].values())


def run_replies(posts, store, prepare, *, live=False, now=utc_now,
                comments=None, pause_seconds=0, sleep=time.sleep):
    """prepare only inspects/fills an editor; its returned callable may publish."""
    state = store.load()
    comments = comments if comments is not None else default_comments
    if not comments or any(not text.strip() for text in comments):
        raise ValueError("评论库不能为空")
    result = {"preview": [], "confirmed": [], "skipped": [], "halted": None}
    seen = set()
    for post in posts:
        if post.id in seen or post.id in state["replies"] or not eligible(post, now()):
            continue
        seen.add(post.id)
        if used_quota(state, beijing_day(now())) >= DAILY_LIMIT:
            break
        comment = random.choice(comments)
        if not live:
            if len(result["preview"]) >= DAILY_LIMIT - used_quota(state, beijing_day(now())):
                break
            result["preview"].append({"id": post.id, "title": post.title, "url": post.url,
                                      "comment": comment, "validation": "待浏览器复核原帖"})
            continue
        if result["confirmed"] and pause_seconds:
            sleep(pause_seconds)
        publish = prepare(post, comment)
        if publish is None:
            result["skipped"].append(post.id)
            continue
        started = now()
        if not eligible(post, started) or used_quota(state, beijing_day(started)) >= DAILY_LIMIT:
            break
        record = {"status": "pending", "quota_dates": [beijing_day(started)],
                  "url": post.url, "comment": comment, "updated_at": started.isoformat()}
        state["replies"][post.id] = record
        store.save(state)  # Must succeed BEFORE any external submission.
        try:
            outcome = publish()
        except Exception:
            outcome = "unknown"
        record["status"] = outcome if outcome in {"confirmed", "rejected"} else "unknown"
        ended = now()
        record["quota_dates"] = sorted({beijing_day(started), beijing_day(ended)})
        record["updated_at"] = ended.isoformat()
        store.save(state)
        if outcome == "confirmed":
            result["confirmed"].append(post.id)
        else:
            result["halted"] = record["status"]
            break
    result["used_quota"] = used_quota(state, beijing_day(now()))
    return result
