import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.site_data_store import upsert_records
from scripts.snapshot_data_changes import git_text, manual_delta, record_delta


def line(hostname, kind, flow):
    return json.dumps({
        "hostname": hostname, "entry_kind": kind, "flow_type": flow,
    }) + "\n"


class SnapshotDataChangesTests(unittest.TestCase):
    def test_only_changed_and_new_records_are_snapshotted(self):
        base = (
            line("same.example", "login", "direct_password")
            + line("changed.example", "signup", "unknown")
            + line("remote-only.example", "login", "otp_only")
        )
        current = (
            line("same.example", "login", "direct_password")
            + line("changed.example", "signup", "human_blocked")
            + line("new.example", "signup", "sso_only")
        )
        delta = record_delta(current, base)
        self.assertEqual(
            {(r["hostname"], r["entry_kind"]) for r in delta},
            {("changed.example", "signup"), ("new.example", "signup")})
        self.assertNotIn("same.example", {r["hostname"] for r in delta})

    def test_manual_snapshot_contains_only_changed_sites(self):
        base = {"sites": {
            "same.example": {"manual_login": "口令"},
            "changed.example": {"manual_signup": "旧"},
        }}
        current = {"sites": {
            "same.example": {"manual_login": "口令"},
            "changed.example": {"manual_signup": "新"},
            "new.example": {"manual_login": "扫码"},
        }, "updated_at": "now"}
        delta = manual_delta(current, base)
        self.assertEqual(set(delta["sites"]), {"changed.example", "new.example"})
        self.assertEqual(delta["updated_at"], "now")

    def test_empty_manual_delta_omits_stale_timestamp(self):
        current = {"sites": {"same.example": {"manual_login": "口令"}},
                   "updated_at": "old-server-time"}
        self.assertEqual(manual_delta(current, current), {"sites": {}})

    @patch("scripts.snapshot_data_changes.subprocess.run")
    def test_git_baseline_read_failure_aborts_instead_of_becoming_empty(self, run):
        run.return_value = Mock(returncode=128, stdout="", stderr="bad ref")
        with self.assertRaisesRegex(RuntimeError, "为避免全量误回放已中止"):
            git_text(Path("/tmp/project"), "HEAD", "tracked.jsonl")

    def test_replay_delta_does_not_overwrite_unmodified_remote_updates(self):
        base = (
            line("mac-updated.example", "login", "unknown")
            + line("web-updated.example", "signup", "unknown")
        )
        server_worktree = (
            line("mac-updated.example", "login", "unknown")
            + line("web-updated.example", "signup", "human_blocked")
        )
        pulled_remote = [
            json.loads(line("mac-updated.example", "login", "direct_password")),
            json.loads(line("web-updated.example", "signup", "unknown")),
        ]
        delta = record_delta(server_worktree, base)
        self.assertEqual(len(delta), 1)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sites.jsonl"
            target.write_text(
                "".join(json.dumps(r) + "\n" for r in pulled_remote),
                encoding="utf-8")
            upsert_records(target, delta)
            merged = {
                (r["hostname"], r["entry_kind"]): r
                for r in map(
                    json.loads, target.read_text(encoding="utf-8").splitlines())
            }
        self.assertEqual(
            merged[("mac-updated.example", "login")]["flow_type"],
            "direct_password")
        self.assertEqual(
            merged[("web-updated.example", "signup")]["flow_type"],
            "human_blocked")


if __name__ == "__main__":
    unittest.main()
