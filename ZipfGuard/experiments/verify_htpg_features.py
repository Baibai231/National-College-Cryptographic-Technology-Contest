"""Verify completed feature artifacts, including every cached row, without plaintext output."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from core.htpg_features import FEATURE_NAMES
from experiments.extract_htpg_features import file_sha256, write_json


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def verify_run(directory: Path) -> dict:
    directory = Path(directory)
    require(not (directory / "INCOMPLETE").exists(), "run is incomplete")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("status") == "complete", "manifest is not complete")
    for name, meta in manifest["files"].items():
        require(Path(name).name == name, "manifest file must be a basename")
        path = directory / name
        require(path.stat().st_size == meta["bytes"], f"file size mismatch: {name}")
        require(file_sha256(path) == meta["sha256"], f"file checksum mismatch: {name}")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    audit = summary["audit"]
    require(audit["source_rows"] == audit["empty_rows"] + audit["nonempty_rows"], "source row mass mismatch")
    require(audit["source_mass"] == audit["empty_mass"] + audit["nonempty_mass"], "source count mass mismatch")
    result = {"status": "verified", "file_checksums": True, "records_checked": 0,
              "full_feature_cache_checked": False, "summary_reconciled": False,
              "source_sha256": manifest["source"]["full_file_sha256"]}
    if "features.jsonl.gz" not in manifest["files"]:
        return result
    hist = {name: (Counter(), Counter()) for name in FEATURE_NAMES}
    previous_line = rows = mass = unknown_rows = unknown_mass = 0
    with gzip.open(directory / "features.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows += 1
            require(set(row) == {"source_line", "nonempty_index", "count", "status", "features"}, "unexpected record fields")
            require(row["nonempty_index"] == rows, "record index mismatch")
            require(previous_line < row["source_line"] <= audit["source_rows"], "source line order mismatch")
            previous_line = row["source_line"]
            count, features = row["count"], row["features"]
            require(type(count) is int and count > 0, "invalid record count")
            require(set(features) == set(FEATURE_NAMES), "feature schema mismatch")
            require(row["status"] in ("decoded", "invalid_utf8"), "invalid record status")
            if row["status"] == "invalid_utf8":
                require(all(v is None for v in features.values()), "invalid UTF-8 must have unknown features")
                unknown_rows += 1
                unknown_mass += count
            else:
                require(type(features["length"]) is int and features["length"] > 0, "invalid length")
                require(isinstance(features["lsd_structure"], str), "invalid LSD structure")
                require(features["specplace"] in {"none", "head", "middle", "tail", "head+middle", "head+tail", "middle+tail", "head+middle+tail"}, "invalid symbol positions")
                for name in ("capital", "date", "keyboard", "lowercase"):
                    require(type(features[name]) is bool, "invalid boolean feature")
                for name in ("word_type", "lastname"):
                    require(features[name] is None or type(features[name]) is bool, "invalid dictionary feature")
            mass += count
            for name, value in features.items():
                key = "unknown" if value is None else "true" if value is True else "false" if value is False else str(value)
                hist[name][0][key] += 1
                hist[name][1][key] += count
    require(rows == audit["nonempty_rows"] and mass == audit["nonempty_mass"], "cached population mismatch")
    require(unknown_rows == audit["invalid_utf8_rows"] and unknown_mass == audit["invalid_utf8_mass"], "unknown population mismatch")
    for name, (row_counts, mass_counts) in hist.items():
        stats = summary["features"][name]
        require(len(row_counts) == stats["distinct_values"], "distinct feature values mismatch")
        seen = set()
        for item in stats["values"]:
            key = item["value"]
            require(key not in seen, "duplicate summary category")
            seen.add(key)
            require(row_counts[key] == item["rows"] and mass_counts[key] == item["mass"], "feature histogram mismatch")
            require(item["row_fraction"] == item["rows"] / rows and item["mass_fraction"] == item["mass"] / mass, "feature fraction mismatch")
        require(stats["other"]["rows"] == sum(v for k, v in row_counts.items() if k not in seen), "other rows mismatch")
        require(stats["other"]["mass"] == sum(v for k, v in mass_counts.items() if k not in seen), "other mass mismatch")
    result.update({"records_checked": rows, "mass_checked": mass, "full_feature_cache_checked": True,
                   "summary_reconciled": True, "invalid_utf8_rows": unknown_rows,
                   "limitation": "Integrity and histogram check, not independent proof of feature recognition accuracy."})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, help="optional new verification JSON; never overwrites")
    args = parser.parse_args()
    result = verify_run(args.directory)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
