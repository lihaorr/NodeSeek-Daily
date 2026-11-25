"""Synthetic HTML shaped like the observed public forum DOM; no real account data."""


def listing(rows=(), next_href=None, *, newest=False):
    items = ''.join(f'<li class="post-list-item"><div class="post-title"><a href="/post-{pid}-1">{title}</a></div>'
                    '<time datetime="2026-11-25T07:59:00Z">just replied</time></li>' for pid, title in rows)
    pager = f'<a class="pager-next" href="{next_href}">next</a>' if next_href else '<span class="pager-next"></span>'
    sort = '<a data-sort="postTime" class="selected">新帖子</a>' if newest else ''
    return f'<title>NodeSeek</title><header><a href="/space/42">Me</a></header><div id="nsk-frame"><div id="nsk-body-left">{sort}<ul class="post-list">{items}</ul>{pager}</div></div>'


def original(pid, *, published="2026-11-25T07:00:00Z", body="回复即可参与，随机抽一位", author="7"):
    return (f'<title>NodeSeek</title><header><a href="/space/42">Me</a></header><div id="nsk-frame">'
            f'<h1><a class="post-title-link" href="/post-{pid}-1">抽奖福利</a></h1>'
            f'<div class="content-item" id="0" data-comment-id="100"><a class="author-name" href="/space/{author}">OP</a>'
            f'<span class="date-created"><time datetime="{published}">1h ago</time></span>'
            f'<article class="post-content">{body}</article></div></div>')
