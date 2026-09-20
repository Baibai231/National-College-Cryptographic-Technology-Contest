"""Build the documented alternative HTPG lexicons from pinned/public sources.

Downloads dictionaries only; never receives or uploads a password corpus.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request

VADER_COMMIT = "44fc044cd877310ee8278a0eadf34bcd50d41d06"
VADER_BASE = f"https://raw.githubusercontent.com/cjhutto/vaderSentiment/{VADER_COMMIT}/"
CENSUS_MIRROR_COMMIT = "4c1ff5e3aef1816ae04af63218015066e186c147"
CENSUS_URL = f"https://raw.githubusercontent.com/fivethirtyeight/data/{CENSUS_MIRROR_COMMIT}/most-common-name/surnames.csv"


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def build_profile() -> dict:
    vader = download(VADER_BASE + "vaderSentiment/vader_lexicon.txt")
    license_text = download(VADER_BASE + "LICENSE.txt").decode("utf-8")
    census = download(CENSUS_URL)
    emotional = set()
    for line in vader.decode("utf-8").splitlines():
        fields = line.split("\t")
        term = fields[0].lower()
        if len(fields) >= 2 and len(term) >= 3 and term.isascii() and term.isalpha() and float(fields[1]) != 0:
            emotional.add(term)
    rows = csv.DictReader(io.StringIO(census.decode("utf-8-sig")))
    surnames = {row["name"].lower() for row in rows if row["rank"].isdigit() and 1 <= int(row["rank"]) <= 1000}
    if len(surnames) != 1000 or len(emotional) < 1000:
        raise ValueError("unexpected reference lexicon size")
    return {
        "schema_version": 1, "profile_id": "vader-census-alternative-v1",
        "original_author_lexicons": False,
        "word_type": {"terms": sorted(emotional), "selection": "VADER nonzero sentiment, ASCII alphabetic terms of length >=3; both signs; not VADER scoring"},
        "lastname": {"terms": sorted(surnames), "selection": "US Census 2000 surnames as published by FiveThirtyEight; rank 1..1000; lowercase; no author Chinese list"},
        "sources": [
            {"url": VADER_BASE + "vaderSentiment/vader_lexicon.txt", "sha256": hashlib.sha256(vader).hexdigest(), "license": "MIT; full notice below"},
            {"url": CENSUS_URL, "sha256": hashlib.sha256(census).hexdigest(), "license": "FiveThirtyEight data CC-BY-4.0; https://creativecommons.org/licenses/by/4.0/", "attribution": "US Census Bureau; FiveThirtyEight, Most Common Name; modified by selecting rank<=1000 and lowercasing"},
        ],
        "vader_license": license_text,
        "limitations": "Alternative dictionaries, not original HTPG authors' lists. Substring matches are lexical hints, not evidence of emotion, identity or insecurity.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = build_profile()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(profile, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"word_type_terms": len(profile["word_type"]["terms"]), "lastname_terms": len(profile["lastname"]["terms"])}))


if __name__ == "__main__":
    main()
