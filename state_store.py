"""Small checkpoint stores. A failed or ambiguous write always aborts the caller."""
import base64
import json
import os
import re
from contextlib import contextmanager, nullcontext
from datetime import date
from pathlib import Path

import requests


def empty_state():
    return {"version": 2, "timezone": "Asia/Shanghai", "account_id": None,
            "replies": {}, "checkins": {}}


def normalize_state(value):
    if not isinstance(value, dict):
        raise ValueError("状态必须是 JSON 对象，禁止自动清空")
    if value.get("version") == 1 and value.get("entries") == []:
        # The old, unused automation-state branch has this exact empty schema.
        if set(value) - {"version", "date", "timezone", "target", "entries"}:
            raise ValueError("旧状态包含未知数据，需要人工迁移")
        return empty_state()
    if (value.get("version") != 2 or value.get("timezone") != "Asia/Shanghai"
            or not isinstance(value.get("replies"), dict)
            or not isinstance(value.get("checkins"), dict)
            or (value.get("account_id") is not None
                and not re.fullmatch(r"[1-9]\d*", str(value["account_id"])))):
        raise ValueError("状态格式不兼容，禁止自动重置每日额度")
    for post_id, record in value["replies"].items():
        if (not re.fullmatch(r"[1-9]\d*", post_id) or not isinstance(record, dict)
                or record.get("status") not in {"pending", "confirmed", "unknown", "rejected"}
                or not isinstance(record.get("quota_dates"), list)
                or not record["quota_dates"]):
            raise ValueError("评论历史损坏，需要人工检查")
        for day in record["quota_dates"]:
            date.fromisoformat(day)
    for day, outcome in value["checkins"].items():
        date.fromisoformat(day)
        if outcome not in {"confirmed", "already"}:
            raise ValueError("签到历史损坏")
    return value


class FileStateStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return empty_state()
        return normalize_state(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state):
        normalize_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    @contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(self.path) + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.close(descriptor)
            yield
        finally:
            lock_path.unlink()


class GitHubStateStore:
    """Contents API SHA is a compare-and-swap guard; never retry a conflict."""
    def __init__(self, repository, token, branch="automation-state", session=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository or "") or not token:
            raise ValueError("GitHub 状态存储需要仓库名和令牌")
        self.url = f"https://api.github.com/repos/{repository}/contents/state.json"
        self.branch = branch
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}",
                                     "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"})
        self.sha = None

    def load(self):
        response = self.session.get(self.url, params={"ref": self.branch}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"读取远程状态失败 HTTP {response.status_code}；请检查 automation-state/state.json")
        payload = response.json()
        state = normalize_state(json.loads(base64.b64decode(payload["content"])))
        self.sha = payload["sha"]
        return state

    def save(self, state):
        normalize_state(state)
        if not self.sha:
            raise RuntimeError("写入前必须成功读取现有远程状态")
        content = base64.b64encode(json.dumps(state, ensure_ascii=False, indent=2).encode()).decode()
        response = self.session.put(self.url, json={
            "message": "chore: checkpoint NodeSeek automation state",
            "branch": self.branch, "sha": self.sha, "content": content,
        }, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"保存远程状态失败 HTTP {response.status_code}；已停止后续操作")
        self.sha = response.json()["content"]["sha"]

    def lock(self):
        # Workflow concurrency serializes runs; SHA conflicts protect stale writers.
        return nullcontext()
