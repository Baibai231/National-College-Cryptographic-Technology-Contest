import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_site_database import create_db
from scripts.site_data_store import (
    measurement_record, merge_manual_reviews, upsert_manual_review,
    upsert_records,
)
import webapp.app as web_app


class SiteDataStoreTests(unittest.TestCase):
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
                           "confidence": "high", "evidence": ["password"]}))
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

            rows = [json.loads(line) for line in reports_path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT login_flow, signup_flow, details_json FROM sites "
                "WHERE hostname='example.com'").fetchone()
            conn.close()
            self.assertEqual(row[:2], ("direct_password", "otp_only"))
            details = json.loads(row[2])
            self.assertEqual(details["login_record"]["confidence"], "high")
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
            rows = [json.loads(line) for line in path.read_text().splitlines()]

            self.assertEqual(result, {"added": 0, "updated": 1, "total": 2})
            self.assertEqual({row["entry_kind"] for row in rows}, {"login", "signup"})
            signup_row = next(row for row in rows if row["entry_kind"] == "signup")
            self.assertEqual(signup_row["stop_reason"], "verification_required")
            self.assertEqual(signup_row["evidence"], ["sms"])

    def test_manual_review_upsert_preserves_other_sites_and_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            path.write_text(json.dumps({"sites": {
                "first.example": {"manual_login": "原登录", "verified": True},
                "second.example": {"manual_login": "保留登录"},
            }}), encoding="utf-8")
            upsert_manual_review(
                path, "second.example", signup="短信注册",
                structured={"signup": {"otp": True}},
                reviewed_from="web@test")
            saved = json.loads(path.read_text())
            self.assertEqual(
                saved["sites"]["first.example"]["manual_login"], "原登录")
            self.assertEqual(
                saved["sites"]["second.example"]["manual_login"], "保留登录")
            self.assertTrue(
                saved["sites"]["second.example"]["structured"]["signup"]["otp"])

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
            saved = json.loads(path.read_text())
            self.assertEqual(result, {"updated": 2, "total": 3})
            self.assertEqual(saved["sites"]["mac.example"]["manual_login"], "Mac")
            self.assertEqual(
                saved["sites"]["shared.example"]["manual_login"], "服务器新值")

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
            saved = json.loads(manual_path.read_text())
            self.assertTrue(saved["sites"]["example.com"]["structured"]
                            ["signup"]["password"])


if __name__ == "__main__":
    unittest.main()
