import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from scripts.build_site_database import (
    _merge_unique_records,
    build_sites,
    create_db,
)
from scripts import merge_reviews
from scripts.finalize_measurement_data import finalize
from scripts.site_data_store import (
    measurement_record, merge_manual_reviews, upsert_manual_review,
    upsert_records,
)
import webapp.app as web_app


class SiteDataStoreTests(unittest.TestCase):
    def test_old_database_records_are_merged_idempotently(self):
        from collections import defaultdict

        groups = defaultdict(lambda: defaultdict(list))
        current = {
            "hostname": "example.com", "entry_kind": "signup",
            "version": "v4", "flow_type": "direct_password",
        }
        historic = {
            "hostname": "example.com", "entry_kind": "signup",
            "version": "v3", "flow_type": "unknown",
        }
        groups["example.com"]["signup"].append(current)

        self.assertEqual(
            _merge_unique_records(groups, [dict(current), historic]), 1)
        self.assertEqual(
            _merge_unique_records(groups, [dict(current), dict(historic)]), 0)
        self.assertEqual(len(groups["example.com"]["signup"]), 2)

    def test_legacy_measured_policy_is_exposed_as_password_policy(self):
        measured = {
            "site": "https://example.com", "hostname": "example.com",
            "entry_kind": "signup", "version": "v4",
            "flow_type": "direct_password", "method_used": "inline",
            "policy": {
                "length": [8, 16],
                "restrictive": {"r_cmb34": True},
                "permissive": {"permitted_characters": {}},
            },
            "states": [{"step": 1, "fields": ["password"]}],
        }
        site = build_sites({"example.com": {"signup": [measured]}})[0]
        self.assertEqual(site["signup"]["policy"], {})
        self.assertEqual(site["signup"]["pwd_policy"]["length"], [8, 16])
        self.assertEqual(site["signup"]["pwd_method"], "inline")

    def test_classification_policy_is_not_mistaken_for_measured_policy(self):
        classified = measurement_record(
            "example.com", "https://example.com", "v4", "signup", {
                "flow_type": "direct_password",
                "policy": {"schema_version": "1.0", "authentication": {
                    "password_status": "password_observed"
                }},
            })
        site = build_sites({"example.com": {"signup": [classified]}})[0]
        self.assertEqual(site["signup"]["policy"]["schema_version"], "1.0")
        self.assertEqual(site["signup"]["pwd_policy"], {})

    def test_explicit_password_policy_never_leaks_into_classification_policy(self):
        measured = {
            "site": "https://example.com", "hostname": "example.com",
            "entry_kind": "signup", "version": "v4",
            "flow_type": "direct_password", "pwd_method": "inline",
            "policy": {
                "length": [8, 16], "restrictive": {}, "permissive": {},
            },
            "pwd_policy": {
                "length": [10, 32], "restrictive": {}, "permissive": {},
            },
        }
        site = build_sites({"example.com": {"signup": [measured]}})[0]
        self.assertEqual(site["signup"]["policy"], {})
        self.assertEqual(site["signup"]["pwd_policy"]["length"], [10, 32])

    def test_v4_write_contract_accepts_current_version(self):
        # v4 起：网页写入模型接受 v3/v4（默认 v4），v5 及以上应拒绝
        req = web_app.AddSiteRequest(hostname="example.com", version="v4")
        self.assertEqual(req.version, "v4")
        req3 = web_app.AddSiteRequest(hostname="example.com", version="v3")
        self.assertEqual(req3.version, "v3")
        with self.assertRaises(ValidationError):
            web_app.AddSiteRequest(hostname="example.com", version="v5")

    def test_measurement_record_preserves_v4_methods(self):
        entry = {
            "flow_type": "direct_password",
            "raw_states": [{"step": 1, "fields": ["password"]}],
            "methods": [
                {"method": "password", "name_zh": "账号密码",
                 "status": "confirmed", "confidence": "high",
                 "blockers": [], "route": "第1步(弹窗)", "steps": [1]},
            ],
        }
        rec = measurement_record("example.com", "https://example.com/", "v4",
                                 "login", entry)
        self.assertEqual(len(rec["methods"]), 1)
        self.assertEqual(rec["methods"][0]["name_zh"], "账号密码")
        self.assertEqual(rec["version"], "v4")

    def test_live_classify_rejects_private_and_nonstandard_targets(self):
        for url in (
            "http://127.0.0.1", "http://169.254.169.254/latest",
            "file:///etc/passwd", "https://example.com:8443",
        ):
            with self.subTest(url=url), self.assertRaises(HTTPException) as ctx:
                web_app._validated_classify_url(url, resolve=False)
            self.assertEqual(ctx.exception.status_code, 400)

    @patch("webapp.app.socket.getaddrinfo")
    def test_live_classify_rejects_hostname_resolving_to_private_ip(self, resolve):
        resolve.return_value = [
            (2, 1, 6, "", ("10.0.0.8", 443)),
        ]
        with self.assertRaises(HTTPException) as ctx:
            web_app._validated_classify_url(
                "https://internal.example", resolve=True)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_concurrent_login_and_signup_writes_keep_both_sides_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = str(root / "sites.db")
            reports_path = root / "sites_latest.jsonl"
            create_db([], db_path)
            old_values = (
                web_app.DB_PATH, web_app.REPORTS_PATH, web_app.DATA_LOCK_PATH)
            old_token = os.environ.get("SITES_ADMIN_TOKEN")
            web_app.DB_PATH = db_path
            web_app.REPORTS_PATH = reports_path
            web_app.DATA_LOCK_PATH = root / ".data-sync.lock"
            os.environ["SITES_ADMIN_TOKEN"] = "test-token"
            errors = []

            def write(side):
                entry = {
                    "flow_type": ("direct_password" if side == "login"
                                  else "otp_only"),
                    "states": [{"step": 1, "fields": [
                        "password" if side == "login" else "phone"]}],
                }
                try:
                    web_app.add_site(web_app.AddSiteRequest(
                        hostname="race.example", version="v3",
                        admin_token="test-token", **{side: entry}))
                except Exception as exc:  # pragma: no cover - assertion below
                    errors.append(exc)

            try:
                threads = [threading.Thread(target=write, args=(side,))
                           for side in ("login", "signup")]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
            finally:
                (web_app.DB_PATH, web_app.REPORTS_PATH,
                 web_app.DATA_LOCK_PATH) = old_values
                if old_token is None:
                    os.environ.pop("SITES_ADMIN_TOKEN", None)
                else:
                    os.environ["SITES_ADMIN_TOKEN"] = old_token

            self.assertEqual(errors, [])
            rows = [json.loads(line) for line in
                    reports_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                {row["entry_kind"] for row in rows}, {"login", "signup"})
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT login_flow, signup_flow, details_json FROM sites "
                "WHERE hostname='race.example'").fetchone()
            conn.close()
            self.assertEqual(row[:2], ("direct_password", "otp_only"))
            self.assertEqual(
                set(json.loads(row[2])) & {"login_record", "signup_record"},
                {"login_record", "signup_record"})

    def test_web_add_writes_reports_and_preserves_existing_side_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sites.db")
            reports_path = Path(tmp) / "sites_latest.jsonl"
            create_db([], db_path)
            old_db, old_reports = web_app.DB_PATH, web_app.REPORTS_PATH
            old_token = os.environ.get("SITES_ADMIN_TOKEN")
            web_app.DB_PATH = db_path
            web_app.REPORTS_PATH = reports_path
            os.environ["SITES_ADMIN_TOKEN"] = "test-token"
            try:
                web_app.add_site(web_app.AddSiteRequest(
                    hostname="example.com", url="https://example.com", version="v3",
                    admin_token="test-token",
                    login={"flow_type": "direct_password", "flow_zh": "直接口令",
                           "route": "账号 → 口令",
                           "states": [{"step": 1, "fields": ["password"]}],
                           "confidence": "high", "evidence": ["password"],
                           "security_observations": {
                               "schema_version": "1.0",
                               "collection_mode": "passive",
                           }}))
                web_app.add_site(web_app.AddSiteRequest(
                    hostname="example.com", url="https://example.com", version="v3",
                    admin_token="test-token",
                    signup={"flow_type": "otp_only", "flow_zh": "仅一次性验证码",
                            "route": "手机号 → 短信验证码",
                            "states": [{"step": 1, "fields": ["phone", "code"],
                                        "blockers": ["sms_code"]}],
                            "stop_reason": "verification_required"}))
            finally:
                web_app.DB_PATH, web_app.REPORTS_PATH = old_db, old_reports
                if old_token is None:
                    os.environ.pop("SITES_ADMIN_TOKEN", None)
                else:
                    os.environ["SITES_ADMIN_TOKEN"] = old_token

            rows = [json.loads(line) for line in
                    reports_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            login_record = next(
                item for item in rows if item["entry_kind"] == "login")
            self.assertEqual(
                login_record["security_observations"]["collection_mode"],
                "passive")
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT login_flow, signup_flow, details_json FROM sites "
                "WHERE hostname='example.com'").fetchone()
            conn.close()
            self.assertEqual(row[:2], ("direct_password", "otp_only"))
            details = json.loads(row[2])
            self.assertEqual(details["login_record"]["confidence"], "high")
            self.assertEqual(
                details["login_security_observations"]["schema_version"],
                "1.0")
            self.assertEqual(
                details["signup_record"]["stop_reason"], "verification_required")

    def test_single_side_upsert_preserves_other_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sites.jsonl"
            login = measurement_record(
                "example.com", "https://example.com", "v3", "login",
                {"flow_type": "direct_password", "confidence": "high",
                 "states": [{"step": 1, "fields": ["password"]}]})
            signup = measurement_record(
                "example.com", "https://example.com", "v3", "signup",
                {"flow_type": "otp_only", "stop_reason": "verification_required",
                 "evidence": ["sms"], "states": []})
            upsert_records(path, [login, signup])

            replacement = measurement_record(
                "example.com", "https://example.com", "v3", "login",
                {"flow_type": "sso_only", "primary_method": "sso",
                 "states": []})
            result = upsert_records(path, [replacement])
            rows = [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(result, {"added": 0, "updated": 1, "total": 2})
            self.assertEqual({row["entry_kind"] for row in rows}, {"login", "signup"})
            signup_row = next(row for row in rows if row["entry_kind"] == "signup")
            self.assertEqual(signup_row["stop_reason"], "verification_required")
            self.assertEqual(signup_row["evidence"], ["sms"])

    def test_empty_record_replay_reports_existing_total_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sites.jsonl"
            record = measurement_record(
                "example.com", "https://example.com", "v3", "login",
                {"flow_type": "direct_password"})
            upsert_records(path, [record])
            before = path.stat().st_mtime_ns
            result = upsert_records(path, [])
            self.assertEqual(result, {"added": 0, "updated": 0, "total": 1})
            self.assertEqual(path.stat().st_mtime_ns, before)

    @patch("scripts.finalize_measurement_data.subprocess.run")
    def test_measurement_finalize_preserves_web_only_records(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sites.jsonl"
            staging = root / "complete.tmp"
            web_only = measurement_record(
                "web-only.example", "https://web-only.example", "v3",
                "login", {"flow_type": "sso_only"})
            old = measurement_record(
                "measured.example", "https://measured.example", "v3",
                "signup", {"flow_type": "unknown"})
            new = measurement_record(
                "measured.example", "https://measured.example", "v3",
                "signup", {"flow_type": "otp_only"})
            target.write_text(
                "".join(json.dumps(r) + "\n" for r in (web_only, old)),
                encoding="utf-8")
            staging.write_text(json.dumps(new) + "\n", encoding="utf-8")

            finalize(
                staging, target, lock_path=root / ".data-sync.lock",
                profiles_dir=root / "profiles", summary=root / "summary.md",
                database=root / "sites.db")

            saved = {
                (row["hostname"], row["entry_kind"]): row
                for row in map(
                    json.loads, target.read_text(encoding="utf-8").splitlines())
            }
            self.assertEqual(len(saved), 2)
            self.assertEqual(
                saved[("web-only.example", "login")]["flow_type"], "sso_only")
            self.assertEqual(
                saved[("measured.example", "signup")]["flow_type"], "otp_only")
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertEqual(call.kwargs["env"]["SITES_SYNC_LOCK_HELD"], "1")

    def test_manual_review_upsert_preserves_other_sites_and_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            path.write_text(json.dumps({"sites": {
                "first.example": {"manual_login": "原登录", "verified": True},
                "second.example": {"manual_login": "保留登录",
                                   "structured": {"login": {"password": True}}},
            }}), encoding="utf-8")
            upsert_manual_review(
                path, "second.example", signup="短信注册",
                structured={"signup": {"otp": True}},
                reviewed_from="web@test")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["sites"]["first.example"]["manual_login"], "原登录")
            self.assertEqual(
                saved["sites"]["second.example"]["manual_login"], "保留登录")
            self.assertTrue(
                saved["sites"]["second.example"]["structured"]["signup"]["otp"])
            self.assertTrue(
                saved["sites"]["second.example"]["structured"]["login"]["password"])

    def test_cli_review_merge_keeps_feedback_out_of_manual_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = str(root / "sites.db")
            manual_path = root / "manual.json"
            manual_path.write_text('{"sites": {}}', encoding="utf-8")
            create_db([], db_path)
            conn = sqlite3.connect(db_path)
            conn.executemany(
                "INSERT INTO reviews_pending "
                "(hostname, login, note, submitter, review_type, submitted_at, structured_json) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    ("manual.example", "口令", "", "alice", "manual",
                     "2026-08-15T00:00:00+00:00",
                     '{"login":{"password":true}}'),
                    ("feedback.example", "", "程序错了", "bob", "feedback",
                     "2026-08-15T00:01:00+00:00", "{}"),
                ])
            conn.commit()
            conn.close()
            old_lock = os.environ.get("SITES_DATA_LOCK")
            os.environ["SITES_DATA_LOCK"] = str(root / ".data-sync.lock")
            try:
                with patch("sys.argv", [
                    "merge_reviews.py", "--db", db_path,
                    "--manual", str(manual_path), "--apply"]):
                    merge_reviews.main()
            finally:
                if old_lock is None:
                    os.environ.pop("SITES_DATA_LOCK", None)
                else:
                    os.environ["SITES_DATA_LOCK"] = old_lock

            saved = json.loads(manual_path.read_text(encoding="utf-8"))
            self.assertIn("manual.example", saved["sites"])
            self.assertNotIn("feedback.example", saved["sites"])
            self.assertTrue(saved["sites"]["manual.example"]["structured"]
                            ["login"]["password"])
            conn = sqlite3.connect(db_path)
            pending = conn.execute("SELECT COUNT(*) FROM reviews_pending").fetchone()[0]
            conn.close()
            self.assertEqual(pending, 0)

    def test_full_manual_merge_is_atomic_and_incoming_sites_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            path.write_text(json.dumps({"sites": {
                "mac.example": {"manual_login": "Mac"},
                "shared.example": {"manual_login": "旧"},
            }}), encoding="utf-8")
            result = merge_manual_reviews(path, {"sites": {
                "server.example": {"manual_signup": "服务器"},
                "shared.example": {"manual_login": "服务器新值"},
            }, "updated_at": "2026-08-14T12:00:00Z"})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result, {"updated": 2, "total": 3})
            self.assertEqual(saved["sites"]["mac.example"]["manual_login"], "Mac")
            self.assertEqual(
                saved["sites"]["shared.example"]["manual_login"], "服务器新值")

    def test_manual_noop_replay_does_not_roll_back_timestamp_or_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            current = {
                "sites": {"same.example": {"manual_login": "口令"}},
                "updated_at": "2026-08-15T00:00:00+00:00",
            }
            path.write_text(json.dumps(current), encoding="utf-8")
            before = path.stat().st_mtime_ns
            result = merge_manual_reviews(path, {
                "sites": {"same.example": {"manual_login": "口令"}},
                "updated_at": "2026-08-14T00:00:00+00:00",
            })
            self.assertEqual(result, {"updated": 0, "total": 1})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), current)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_database_rebuild_preserves_pending_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sites.db")
            create_db([], db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO reviews_pending "
                "(hostname, login, signup, note, submitter, review_type, submitted_at, structured_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("example.com", "口令", "短信", "备注", "tester", "manual",
                 "2026-08-14T00:00:00+00:00", '{"signup":{"otp":true}}'))
            conn.commit()
            conn.close()

            create_db([], db_path)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT hostname, submitter, structured_json FROM reviews_pending").fetchone()
            conn.close()
            self.assertEqual(row, (
                "example.com", "tester", '{"signup":{"otp":true}}'))

    def test_failed_database_rebuild_keeps_previous_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sites.db")
            create_db([], db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO reviews_pending (hostname) VALUES (?)",
                ("safe.example",))
            conn.commit()
            conn.close()

            with self.assertRaises(KeyError):
                create_db([{"hostname": "broken.example"}], db_path)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT hostname FROM reviews_pending").fetchone()
            conn.close()
            self.assertEqual(row, ("safe.example",))

    def test_unreadable_old_database_aborts_rebuild_instead_of_losing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sites.db"
            original = b"not a sqlite database"
            db_path.write_bytes(original)
            with self.assertRaisesRegex(RuntimeError, "已取消重建"):
                create_db([], str(db_path))
            self.assertEqual(db_path.read_bytes(), original)

    def test_approved_structured_review_is_immediately_comparable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sites.db")
            reports_path = Path(tmp) / "sites_latest.jsonl"
            manual_path = Path(tmp) / "manual_review.json"
            manual_path.write_text('{"sites": {}}', encoding="utf-8")
            create_db([], db_path)
            old_values = (web_app.DB_PATH, web_app.REPORTS_PATH, web_app.MANUAL_PATH)
            old_token = os.environ.get("SITES_ADMIN_TOKEN")
            web_app.DB_PATH = db_path
            web_app.REPORTS_PATH = reports_path
            web_app.MANUAL_PATH = manual_path
            os.environ["SITES_ADMIN_TOKEN"] = "test-token"
            try:
                web_app.add_site(web_app.AddSiteRequest(
                    hostname="example.com", version="v3", admin_token="test-token",
                    signup={"flow_type": "direct_password", "flow_zh": "直接口令",
                            "route": "账号 → 口令",
                            "states": [{"step": 1, "fields": ["password"]}]}))
                web_app.submit_review(web_app.ReviewRequest(
                    hostname="example.com", signup="入口藏在弹窗里",
                    submitter="tester", structured={"signup": {"password": True}}))
                conn = sqlite3.connect(db_path)
                review_id = conn.execute("SELECT id FROM reviews_pending").fetchone()[0]
                conn.close()
                web_app.approve_review(review_id, admin_token="test-token")
                site = web_app.site_detail("example.com")
            finally:
                web_app.DB_PATH, web_app.REPORTS_PATH, web_app.MANUAL_PATH = old_values
                if old_token is None:
                    os.environ.pop("SITES_ADMIN_TOKEN", None)
                else:
                    os.environ["SITES_ADMIN_TOKEN"] = old_token

            self.assertEqual(site["signup_match"], "match")
            self.assertTrue(site["manual"]["structured"]["signup"]["password"])
            saved = json.loads(manual_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["sites"]["example.com"]["structured"]
                            ["signup"]["password"])

    def test_pending_review_details_require_admin_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sites.db")
            manual_path = Path(tmp) / "manual_review.json"
            data_lock_path = Path(tmp) / ".data-sync.lock"
            manual_path.write_text('{"sites": {}}', encoding="utf-8")
            create_db([], db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO reviews_pending "
                "(hostname, login, submitter, submitted_at) VALUES (?,?,?,?)",
                ("private.example", "敏感人工观察", "reviewer",
                 "2026-08-15T00:00:00+00:00"))
            conn.execute(
                "INSERT INTO sites (hostname, url, keywords, version, "
                "login_flow, signup_flow, details_json) VALUES (?,?,?,?,?,?,?)",
                ("private.example", "https://private.example", "[]", "v4",
                 "direct_password", "direct_password", "{}"))
            conn.commit()
            conn.close()
            old_values = (web_app.DB_PATH, web_app.MANUAL_PATH,
                          web_app.DATA_LOCK_PATH)
            old_token = os.environ.get("SITES_ADMIN_TOKEN")
            web_app.DB_PATH = db_path
            web_app.MANUAL_PATH = manual_path
            web_app.DATA_LOCK_PATH = data_lock_path
            os.environ["SITES_ADMIN_TOKEN"] = "test-token"
            try:
                # 2026-08-16 规则：待审核列表所有人可见（含完整内容）
                public = web_app.pending_reviews(hostname="private.example")
                self.assertEqual(public["total"], 1)
                self.assertIn("敏感人工观察", public["reviews"][0]["login"])
                full = web_app.pending_reviews(hostname="")
                self.assertEqual(full["total"], 1)
                # 通过仍需管理员口令
                with self.assertRaises(HTTPException) as denied:
                    web_app.approve_review(public["reviews"][0]["id"],
                                           admin_token="")
                self.assertEqual(denied.exception.status_code, 403)
                ok = web_app.approve_review(public["reviews"][0]["id"],
                                            admin_token="test-token")
                self.assertTrue(ok["ok"])
            finally:
                (web_app.DB_PATH, web_app.MANUAL_PATH,
                 web_app.DATA_LOCK_PATH) = old_values
                if old_token is None:
                    os.environ.pop("SITES_ADMIN_TOKEN", None)
                else:
                    os.environ["SITES_ADMIN_TOKEN"] = old_token

    def test_export_reads_exact_authoritative_files_not_sqlite_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = str(root / "sites.db")
            reports_path = root / "sites.jsonl"
            manual_path = root / "manual.json"
            create_db([], db_path)
            exact_record = {
                "hostname": "current.example", "entry_kind": "signup",
                "version": "v3", "flow_type": "otp_only",
                "evidence": ["exact-authority-field"],
            }
            reports_path.write_text(
                json.dumps(exact_record) + "\n", encoding="utf-8")
            manual = {"sites": {"current.example": {
                "manual_signup": "验证码", "verified": True}}}
            manual_path.write_text(json.dumps(manual), encoding="utf-8")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO site_history "
                "(hostname, entry_kind, version, flow_type) VALUES (?,?,?,?)",
                ("current.example", "signup", "v2", "direct_password"))
            conn.commit()
            conn.close()

            old_values = (web_app.DB_PATH, web_app.REPORTS_PATH,
                          web_app.MANUAL_PATH, web_app.DATA_LOCK_PATH)
            old_token = os.environ.get("SITES_ADMIN_TOKEN")
            web_app.DB_PATH = db_path
            web_app.REPORTS_PATH = reports_path
            web_app.MANUAL_PATH = manual_path
            web_app.DATA_LOCK_PATH = root / ".data-sync.lock"
            os.environ["SITES_ADMIN_TOKEN"] = "test-token"
            try:
                exported = web_app.export_data(admin_token="test-token")
            finally:
                (web_app.DB_PATH, web_app.REPORTS_PATH, web_app.MANUAL_PATH,
                 web_app.DATA_LOCK_PATH) = old_values
                if old_token is None:
                    os.environ.pop("SITES_ADMIN_TOKEN", None)
                else:
                    os.environ["SITES_ADMIN_TOKEN"] = old_token

            self.assertEqual(exported["records"], [exact_record])
            self.assertEqual(exported["manual"], manual)


if __name__ == "__main__":
    unittest.main()


class RetryUnknownStabilityTests(unittest.TestCase):
    """--retry-unknown 自动稳定逻辑：防止重写时截断清空数据（2026-08-17 bug）。"""

    def test_stabilize_rewrite_preserves_all_records(self):
        import tempfile
        from scripts import run_measurement as rm
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "round.jsonl"
            recs = [
                {"hostname": "a.com", "entry_kind": "login",
                 "flow_type": "direct_password"},
                {"hostname": "a.com", "entry_kind": "signup",
                 "flow_type": "unknown"},
                {"hostname": "b.com", "entry_kind": "login",
                 "flow_type": "human_blocked"},
            ]
            out.write_text("\n".join(
                json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                encoding="utf-8")
            class Args:
                output = str(out)
                retry_unknown = 2
                workers = 1
            args = Args()
            # 模拟稳定阶段已选出的 votes：unknown 那条升级为 otp_only
            votes = {
                ("a.com", "login"): [recs[0]],
                ("a.com", "signup"): [{"hostname": "a.com",
                                       "entry_kind": "signup",
                                       "flow_type": "otp_only"}],
                ("b.com", "login"): [recs[2]],
            }
            rm._write_stabilized(args.output, votes, set())
            lines = [json.loads(l) for l in
                     out.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 3)
            by_key = {(r["hostname"], r["entry_kind"]): r for r in lines}
            self.assertEqual(by_key[("a.com", "signup")]["flow_type"],
                             "otp_only")
            self.assertEqual(by_key[("a.com", "login")]["flow_type"],
                             "direct_password")
            self.assertEqual(by_key[("b.com", "login")]["flow_type"],
                             "human_blocked")
