"""用两轮全量结果和差异项复测，生成可追溯的最终 JSONL。"""
import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.compare_measurement_rounds import load_round, signature


def is_inconclusive(record):
    """Whether a record lacks a usable classification, regardless of evidence noise."""
    return bool(record.get("error")) or record.get("flow_type") in (None, "unknown", "error")


def select(first, second, tiebreaker, baseline=None):
    baseline = baseline or {}
    if set(first) != set(second):
        missing = sorted(set(first) ^ set(second))
        raise ValueError(f"两轮键集合不一致: {missing[:5]}")
    chosen = {}
    decisions = []
    unresolved = []
    for key in sorted(first):
        one, two = first[key], second[key]
        sig1, sig2 = signature(one), signature(two)
        prior = baseline.get(key)
        prior_sig = signature(prior) if prior is not None else None
        if sig1 == sig2:
            third = tiebreaker.get(key)
            if sig1.get("error") is not None and third is not None \
                    and signature(third).get("error") is None:
                chosen[key] = third
                reason = "两轮均测量失败，差异复测取得有效页面证据，采用成功记录"
            elif sig1.get("error") is not None and prior_sig is not None \
                    and prior_sig.get("error") is None:
                chosen[key] = prior
                reason = "本轮三次均测量失败，保留旧 v3 的有效页面证据"
            else:
                chosen[key] = two
                reason = "两轮语义完全一致，采用时间较新的第二轮"
        else:
            third = tiebreaker.get(key)
            if third is None:
                unresolved.append(key)
                continue
            sig3 = signature(third)
            successful = [
                (record, sig, label)
                for record, sig, label in (
                    (one, sig1, "第一轮"), (two, sig2, "第二轮"),
                    (third, sig3, "差异复测"),
                )
                if sig.get("error") is None
            ]
            if not successful:
                if prior_sig is not None and prior_sig.get("error") is None:
                    chosen[key] = prior
                    reason = "本轮三次均测量失败，保留旧 v3 的有效页面证据"
                else:
                    chosen[key] = third
                    reason = "三次测量均失败，保留最新失败记录并标记人工关注"
            elif len(successful) == 1:
                chosen[key] = successful[0][0]
                reason = (
                    f"仅{successful[0][2]}取得有效页面证据；其余测量失败，"
                    "采用成功记录而不对失败次数做多数投票"
                )
            elif sig3 == sig1:
                chosen[key] = one
                reason = "差异项第三次复测与第一轮一致，按两票多数采用第一轮"
            elif sig3 == sig2:
                chosen[key] = two
                reason = "差异项第三次复测与第二轮一致，按两票多数采用第二轮"
            elif sig3.get("error") is not None:
                chosen[key] = two
                reason = "差异复测失败且前两轮均有有效证据，采用较新的第二轮并标记人工关注"
            else:
                chosen[key] = third
                reason = "三次语义均不同，采用独立复测最新证据并标记人工关注"
        if prior is not None and is_inconclusive(chosen[key]) \
                and not is_inconclusive(prior):
            chosen[key] = prior
            reason += "；本轮结论仍属 unknown/error，保留同一 v3 的最后有效证据"
        decisions.append({
            "hostname": key[0], "entry_kind": key[1], "reason": reason,
            "selected": signature(chosen[key]),
            "round1": sig1, "round2": sig2,
            "tiebreaker": signature(tiebreaker[key]) if key in tiebreaker else None,
            "baseline": prior_sig,
        })
    if unresolved:
        raise ValueError(f"有 {len(unresolved)} 个差异项未复测: {unresolved[:5]}")
    return chosen, decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round1")
    parser.add_argument("round2")
    parser.add_argument("tiebreaker")
    parser.add_argument("--baseline", help="旧正式 v3；仅在本轮全部失败时兜底")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    first = load_round(args.round1)
    second = load_round(args.round2)
    third = load_round(args.tiebreaker)
    baseline = load_round(args.baseline) if args.baseline else {}
    chosen, decisions = select(first, second, third, baseline)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for key in sorted(chosen):
            handle.write(json.dumps(chosen[key], ensure_ascii=False) + "\n")
    Path(args.report).write_text(
        json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    disagreements = sum(item["round1"] != item["round2"] for item in decisions)
    print(f"生成 {len(chosen)} 条最终记录；差异复测决策 {disagreements} 条")


if __name__ == "__main__":
    main()
