import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from state_store import FileStateStore, GitHubStateStore, normalize_state


class StateTests(unittest.TestCase):
    def test_only_empty_legacy_state_can_be_migrated_without_losing_history(self):
        state = normalize_state({"version": 1, "date": "2026-08-09", "entries": []})
        self.assertEqual(state["replies"], {})
        with self.assertRaises(ValueError):
            normalize_state({"version": 1, "entries": [{"id": 42}]})

    def test_corrupt_or_incompatible_state_never_silently_resets_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_text('{"version":2,"replies":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                FileStateStore(path).load()

    def test_local_lock_rejects_a_second_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FileStateStore(Path(folder) / "state.json")
            with store.lock():
                with self.assertRaises(FileExistsError):
                    with store.lock():
                        self.fail("two writers")
            self.assertFalse(Path(str(store.path) + ".lock").exists())

    def test_github_write_uses_loaded_sha_and_conflict_stops_without_retry(self):
        session = Mock()
        read = Mock(status_code=200)
        read.json.return_value = {"sha": "old-sha", "content": base64.b64encode(
            json.dumps({"version": 1, "entries": []}).encode()).decode()}
        session.get.return_value = read
        session.put.return_value = Mock(status_code=409)
        store = GitHubStateStore("owner/repo", "token", session=session)
        state = store.load()
        with self.assertRaises(RuntimeError):
            store.save(state)
        self.assertEqual(session.put.call_args.kwargs["json"]["sha"], "old-sha")
        self.assertEqual(session.put.call_count, 1)

    def test_missing_remote_state_is_an_error_not_an_empty_quota(self):
        session = Mock()
        session.get.return_value = Mock(status_code=404)
        with self.assertRaises(RuntimeError):
            GitHubStateStore("owner/repo", "token", session=session).load()


if __name__ == "__main__":
    unittest.main()
