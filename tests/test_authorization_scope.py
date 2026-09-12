import json
import tempfile
import unittest
from pathlib import Path

from utils.authorization_scope import load_authorization_scope


class AuthorizationScopeTests(unittest.TestCase):
    def test_text_manifest_matches_exact_hosts_and_idn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.txt"
            path.write_text("# owner scope\nwww.Example.com\n例子.中国\n",
                            encoding="utf-8")
            scope = load_authorization_scope(str(path))

        self.assertTrue(scope.matches("https://example.com/signup"))
        self.assertTrue(scope.matches("xn--fsqu00a.xn--fiqs8s"))
        self.assertFalse(scope.matches("other.example.com"))
        self.assertEqual(len(scope.scope_id), 16)

    def test_json_manifest_supports_narrow_wildcard_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.json"
            path.write_text(json.dumps({
                "authorized_hosts": ["example.com", "*.owned.example"],
                "expires_at": "2099-01-01T00:00:00Z",
            }), encoding="utf-8")
            scope = load_authorization_scope(str(path))

        self.assertTrue(scope.matches("example.com"))
        self.assertTrue(scope.matches("a.owned.example"))
        self.assertFalse(scope.matches("owned.example"))
        self.assertFalse(scope.matches("a.not-owned.example"))
        self.assertIsNotNone(scope.expires_at)

    def test_manifest_rejects_expired_or_broad_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            expired = Path(directory) / "expired.json"
            expired.write_text(json.dumps({
                "authorized_hosts": ["example.com"],
                "expires_at": "2000-01-01T00:00:00Z",
            }), encoding="utf-8")
            broad = Path(directory) / "broad.txt"
            broad.write_text("*.co.uk\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "expired"):
                load_authorization_scope(str(expired))
            with self.assertRaisesRegex(ValueError, "too_broad"):
                load_authorization_scope(str(broad))


if __name__ == "__main__":
    unittest.main()
