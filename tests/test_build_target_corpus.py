import io
import unittest
import zipfile

from scripts.build_target_corpus import (
    build_entries,
    normalize_domain,
    parse_tranco_csv,
    read_tranco_zip,
)


class TargetCorpusTest(unittest.TestCase):
    def test_normalizes_urls_idn_and_www(self):
        self.assertEqual(normalize_domain("https://www.Example.COM/a"), "example.com")
        self.assertEqual(normalize_domain("例子.中国"), "xn--fsqu00a.xn--fiqs8s")
        self.assertIsNone(normalize_domain("127.0.0.1"))
        self.assertIsNone(normalize_domain("localhost"))

    def test_parses_ranked_csv_and_deduplicates(self):
        rows = ["1,example.com\n", "2,www.example.com\n", "3,test.cn\n"]
        self.assertEqual(
            parse_tranco_csv(rows, 2),
            [(1, "example.com"), (3, "test.cn")],
        )

    def test_reads_csv_from_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("top-1m.csv", "1,one.com\n2,two.cn\n")
        self.assertEqual(read_tranco_zip(buffer.getvalue(), 2), [
            (1, "one.com"), (2, "two.cn")])

    def test_supplements_are_labeled_and_do_not_replace_ranked(self):
        entries = build_entries(
            [(1, "one.com"), (2, "two.com")],
            [("two.com", "cn.txt"), ("extra.cn", "cn.txt")],
        )
        self.assertEqual([item["domain"] for item in entries], [
            "one.com", "two.com", "extra.cn"])
        self.assertEqual(entries[-1]["source"], "supplement")


if __name__ == "__main__":
    unittest.main()
