import gzip
import json
from pathlib import Path
import random
import tempfile
import unittest

from core.counted_corpus import parse_counted_line
from core.htpg_features import (FEATURE_NAMES, HTPGFeatureExtractor, LexiconMatcher,
                                contains_date, contains_keyboard_walk, lsd_structure)
from experiments.extract_htpg_features import run_extraction
from experiments.verify_htpg_features import verify_run


class FeatureTests(unittest.TestCase):
    def setUp(self):
        # Synthetic fixtures, not copied corpus samples.
        self.extractor = HTPGFeatureExtractor(["joy", "happy", "sad"], ["smith", "li"])

    def test_paper_structure_example(self):
        self.assertEqual(lsd_structure("123456!AA"), "D6S1L2")

    def test_structure_preserves_order(self):
        self.assertNotEqual(lsd_structure("ab12!"), lsd_structure("a1b2!"))
        self.assertEqual(lsd_structure("a1b2!"), "L1D1L1D1S1")

    def test_nine_features(self):
        self.assertEqual(tuple(self.extractor.extract("Fixture123!").to_dict()), FEATURE_NAMES)

    def test_length_and_capital(self):
        vector = self.extractor.extract("Xy5!")
        self.assertEqual(vector.length, 4)
        self.assertIs(vector.capital, True)
        self.assertFalse(self.extractor.extract("xy5!").capital)

    def test_unicode_not_normalized(self):
        self.assertEqual(self.extractor.extract("é").length, 1)
        self.assertEqual(self.extractor.extract("e\u0301").length, 2)
        self.assertEqual(lsd_structure("中文٣🙂 "), "L2D1S2")
        self.assertEqual(lsd_structure("²"), "S1")

    def test_special_places(self):
        for value, expected in [("abc", "none"), ("!abc", "head"), ("abc!", "tail"),
                                ("ab!cd", "middle"), ("!ab!cd!", "head+middle+tail"),
                                ("!", "head+tail"), (" a ", "head+tail")]:
            with self.subTest(value=value):
                self.assertEqual(self.extractor.extract(value).specplace, expected)

    def test_isolated_lowercase_not_any_lowercase(self):
        for value in ["a123", "123a", "aB", "Aa", "a"]:
            self.assertTrue(self.extractor.extract(value).lowercase)
        for value in ["abcd", "ab12cd", "ABCD", "1a2", "1"]:
            self.assertFalse(self.extractor.extract(value).lowercase)

    def test_valid_dates_and_embedded_year(self):
        for value in ["x2024!", "x2024@7", "1900", "2099", "20240229", "29022024",
                      "02292024", "2024-2-29", "29/2/2024", "2.29.2024"]:
            with self.subTest(value=value):
                self.assertTrue(contains_date(value))

    def test_invalid_dates(self):
        for value in ["1899", "2100", "20230229", "2023-02-29", "2024-13-30",
                      "2024-01/01", "120240", "010101", "20249999", "123456"]:
            with self.subTest(value=value):
                self.assertFalse(contains_date(value))

    def test_keyboard(self):
        for value in ["QWER", "asdf", "rewq", "!@#$", "1234", "zxcv"]:
            self.assertTrue(contains_keyboard_walk(value))
        for value in ["aaa", "aaaa", "asasas", "qwe", "qwe🙂r", "x7p2"]:
            self.assertFalse(contains_keyboard_walk(value))

    def test_lexical_substrings_not_identity(self):
        vector = self.extractor.extract("JoyLi42")
        self.assertTrue(vector.word_type)
        self.assertTrue(vector.lastname)
        self.assertTrue(self.extractor.extract("climb").lastname)
        self.assertFalse(self.extractor.extract("XYZ").word_type)

    def test_missing_lexicons_unknown(self):
        vector = HTPGFeatureExtractor().extract("anything")
        self.assertIsNone(vector.word_type)
        self.assertIsNone(vector.lastname)
        self.assertIsNone(HTPGFeatureExtractor(["joy"]).extract("joy").lastname)

    def test_bad_lexicons_fail(self):
        for terms in [[], [""], [3], "abc"]:
            with self.assertRaises(ValueError):
                HTPGFeatureExtractor(terms)

    def test_empty_not_extractable(self):
        with self.assertRaises(ValueError):
            self.extractor.extract("")

    def test_matcher_against_naive(self):
        words, names = ["he", "hers", "she", "joy"], ["his", "her", "li"]
        matcher = LexiconMatcher(words, names)
        rng = random.Random(73)
        values = ["ushers", "HERS", "joyli"] + ["".join(rng.choices("hersjoyli", k=30)) for _ in range(500)]
        for value in values:
            expected = int(any(w in value.lower() for w in words)) | (int(any(w in value.lower() for w in names)) << 1)
            self.assertEqual(matcher.match(value), expected)

    def test_packaged_profile(self):
        path = Path(__file__).resolve().parents[1] / "resources/htpg_reference_v1.json"
        extractor = HTPGFeatureExtractor.from_profile(path)
        self.assertTrue(extractor.extract("HAPPYSMITH42").word_type)
        self.assertTrue(extractor.extract("HAPPYSMITH42").lastname)
        self.assertEqual(extractor.lexicon_metadata["lastname_terms"], 1000)


class CountedInputTests(unittest.TestCase):
    def test_preserve_whitespace(self):
        self.assertEqual(parse_counted_line(b"  12  a \n", 1), (12, b" a "))
        self.assertEqual(parse_counted_line(b"4\t\ta\r\n", 1), (4, b"\ta\r"))

    def test_last_line_without_lf(self):
        self.assertEqual(parse_counted_line(b"4 xyz", 1), (4, b"xyz"))

    def test_empty_password(self):
        self.assertEqual(parse_counted_line(b"340 \n", 1), (340, b""))

    def test_bad_input_does_not_leak(self):
        for raw in [b"0 SECRET", b"-1 SECRET", b"oops SECRET", b"3", b"\n"]:
            with self.assertRaisesRegex(ValueError, "line 19") as ctx:
                parse_counted_line(raw, 19)
            self.assertNotIn("SECRET", str(ctx.exception))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "input.txt"
        self.source.write_bytes(b"5 SecretFixture2024!\n3 \n2  a \n1 \xff\n1 x\t\n")
        self.extractor = HTPGFeatureExtractor(["fixture"], ["smith"])

    def tearDown(self):
        self.temp.cleanup()

    def run_it(self, name="result", **kwargs):
        return run_extraction(self.source, self.root / name, self.extractor, progress_every=0, **kwargs)

    def test_mass_unknown_privacy_and_records(self):
        summary = self.run_it(write_records=True)
        audit = summary["audit"]
        self.assertEqual(audit["source_mass"], 12)
        self.assertEqual(audit["nonempty_rows"], 4)
        self.assertEqual(audit["nonempty_mass"], 9)
        self.assertEqual(audit["invalid_utf8_mass"], 1)
        self.assertEqual(audit["boundary_whitespace_rows"], 2)
        self.assertEqual(audit["control_byte_rows"], 1)
        for stats in summary["features"].values():
            self.assertEqual(sum(x["mass"] for x in stats["values"]) + stats["other"]["mass"], 9)
            self.assertEqual(sum(x["rows"] for x in stats["values"]) + stats["other"]["rows"], 4)
        with gzip.open(self.root / "result/features.jsonl.gz", "rt") as reader:
            text = reader.read()
        self.assertNotIn("SecretFixture", text)
        rows = [json.loads(x) for x in text.splitlines()]
        self.assertEqual(rows[2]["features"], dict.fromkeys(FEATURE_NAMES))
        self.assertEqual([r["source_line"] for r in rows], [1, 3, 4, 5])
        for name in ("summary.json", "report.md", "manifest.json"):
            self.assertNotIn("SecretFixture", (self.root / "result" / name).read_text())
        self.assertFalse((self.root / "result/INCOMPLETE").exists())

    def test_determinism(self):
        one = self.run_it("one", write_records=True)
        two = self.run_it("two", write_records=True)
        self.assertEqual(one, two)
        self.assertEqual((self.root / "one/features.jsonl.gz").read_bytes(), (self.root / "two/features.jsonl.gz").read_bytes())

    def test_limit_is_not_full_file(self):
        self.run_it(max_lines=1)
        manifest = json.loads((self.root / "result/manifest.json").read_text())
        self.assertIsNone(manifest["source"]["full_file_sha256"])

    def test_limit_at_eof_is_full(self):
        self.assertTrue(self.run_it(max_lines=5)["audit"]["complete_file"])

    def test_refuses_overwrite(self):
        self.run_it()
        with self.assertRaises(FileExistsError):
            self.run_it()

    def test_bad_run_keeps_incomplete_marker(self):
        self.source.write_bytes(b"oops secret\n")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertTrue((self.root / "result/INCOMPLETE").exists())
        self.assertFalse((self.root / "result/manifest.json").exists())

    def test_all_empty_not_evaluable(self):
        self.source.write_bytes(b"3 \n")
        with self.assertRaisesRegex(ValueError, "no nonempty"):
            self.run_it()

    def test_missing_lexicons_summary(self):
        summary = run_extraction(self.source, self.root / "result", HTPGFeatureExtractor(), progress_every=0)
        self.assertEqual(summary["features"]["word_type"]["values"][0]["value"], "unknown")
        self.assertEqual(summary["features"]["word_type"]["values"][0]["mass"], 9)

    def test_unsorted_input_reported(self):
        self.source.write_bytes(b"1 x\n5 y\n")
        self.assertFalse(self.run_it()["audit"]["counts_nonincreasing"])

    def test_verifier_reconciles_cache(self):
        self.run_it(write_records=True)
        result = verify_run(self.root / "result")
        self.assertTrue(result["summary_reconciled"])
        self.assertEqual(result["records_checked"], 4)

    def test_verifier_rejects_tampering(self):
        self.run_it(write_records=True)
        with (self.root / "result/features.jsonl.gz").open("ab") as handle:
            handle.write(b"bad")
        with self.assertRaisesRegex(ValueError, "file size mismatch"):
            verify_run(self.root / "result")

    def test_verifier_summary_only_does_not_claim_cache_checked(self):
        self.run_it()
        self.assertFalse(verify_run(self.root / "result")["full_feature_cache_checked"])


if __name__ == "__main__":
    unittest.main()
