"""Parse NodeSeek's HTML search/list pages; list activity times are NOT publication times."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from lottery import Post, canonical_post_url, plain_text


BASE_URL = "https://www.nodeseek.com"


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostLink:
    id: str
    title: str
    url: str


@dataclass
class Listing:
    links: list[PostLink]
    next_url: str | None


@dataclass
class DiscoveryResult:
    posts: list[Post]
    report: dict


def search_url(query, page=1):
    params = {"q": query}
    if page > 1:
        params["page"] = page
    return BASE_URL + "/search?" + urlencode(params)


def parse_listing(html, url, *, query=None, newest=False):
    soup = BeautifulSoup(html, "html.parser")
    frame = soup.select_one("#nsk-frame #nsk-body-left")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if frame is None or re.search(r"429|too many requests", title, re.I):
        raise DiscoveryError("未收到论坛搜索/列表页面，可能需要登录或已被限流")
    rows = frame.select("ul.post-list > li.post-list-item")
    if not rows:
        message = frame.get_text(" ", strip=True)
        if re.search(r"太短|过[于於]?频繁|頻繁|搜索.{0,12}(?:次数|次數|上限|限制)|429|too many requests", message, re.I):
            raise DiscoveryError("站点拒绝搜索：关键词过短、请求限流或搜索额度不足；本轮不重试")
        if frame.select_one("ul.post-list") is None:
            raise DiscoveryError("搜索/列表结构无法识别，不能把错误页当作零结果")
    if newest and frame.select_one('[data-sort="postTime"].selected') is None:
        raise DiscoveryError("新帖列表未按发布时间排序，停止扫描")
    links, seen = [], set()
    for row in rows:
        if "blocked-post" in row.get("class", []):
            continue
        anchor = row.select_one(".post-title a[href]")
        target = canonical_post_url(urljoin(BASE_URL, anchor["href"])) if anchor else None
        if not target or target[0] in seen:
            continue
        seen.add(target[0])
        links.append(PostLink(target[0], anchor.get_text(" ", strip=True), target[1]))
    # A search past its end can still render a bogus next link. Empty always stops.
    next_anchor = frame.select_one("a.pager-next[href]")
    if not links or next_anchor is None:
        return Listing(links, None)
    current, target = urlsplit(url), urlsplit(urljoin(url, next_anchor["href"]))
    params = parse_qs(target.query)
    if target.scheme != "https" or target.netloc != "www.nodeseek.com" or target.fragment:
        raise DiscoveryError("分页链接离开预期的 NodeSeek 页面，停止扫描")
    if query is not None:
        page = int(parse_qs(current.query).get("page", ["1"])[0])
        if (target.path != "/search" or params.get("q") != [query]
                or params.get("page") != [str(page + 1)] or set(params) - {"q", "page"}):
            raise DiscoveryError("搜索分页改变了关键词或页码，停止扫描")
        next_url = search_url(query, page + 1)
    else:
        page_match = re.fullmatch(r"/page-(\d+)", current.path)
        page = int(page_match.group(1)) if page_match else 1
        if target.path != f"/page-{page + 1}" or params not in ({}, {"sortBy": ["postTime"]}):
            raise DiscoveryError("新帖分页改变了排序或页码，停止扫描")
        next_url = BASE_URL + target.path + "?sortBy=postTime"
    return Listing(links, next_url)


def parse_original(html, link):
    soup = BeautifulSoup(html, "html.parser")
    original = soup.select_one('.content-item[id="0"]')
    content = original.select_one("article.post-content") if original else None
    created = original.select_one(".date-created time[datetime]") if original else None
    title = soup.select_one("h1 a.post-title-link[href]")
    target = canonical_post_url(urljoin(BASE_URL, title["href"])) if title else None
    if content is None or created is None or target is None or target[0] != link.id:
        raise DiscoveryError("无法识别原帖、原始发布时间或帖子身份，未准备评论")
    try:
        published = datetime.fromisoformat(created["datetime"].replace("Z", "+00:00"))
    except ValueError as error:
        raise DiscoveryError("原帖发布时间无效") from error
    if published.tzinfo is None:
        raise DiscoveryError("原帖发布时间缺少时区，不能判断是否为新帖")
    draw_times = []
    for anchor in content.select('a[href]'):
        parts = urlsplit(urljoin(BASE_URL, anchor["href"]))
        params = parse_qs(parts.query)
        if (parts.scheme == "https" and parts.netloc == "www.nodeseek.com"
                and parts.path == "/lucky" and params.get("post") == [link.id] and "time" in params):
            try:
                draw_times.append(datetime.fromtimestamp(int(params["time"][0]) / 1000, timezone.utc))
            except (ValueError, OverflowError, OSError) as error:
                raise DiscoveryError("原帖中的官方开奖时间无效，未准备评论") from error
    return Post(link.id, title.get_text(" ", strip=True), link.url, plain_text(str(content)),
                published, min(draw_times) if draw_times else None)
