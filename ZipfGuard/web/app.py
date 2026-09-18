"""Small offline dashboard for the ZipfGuard MVP.

Run with ``streamlit run web/app.py`` after installing the optional
``streamlit`` dependency. The analytical pipeline itself has no web or network
dependency, so the CLI remains the canonical fallback for field demos.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.data import load_count_json
from experiments.pipeline import run_pipeline


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - exercised only without optional UI dependency
        raise SystemExit("可选界面需要 streamlit；请先安装后运行 streamlit run web/app.py") from exc
    st.set_page_config(page_title="ZipfGuard DP-HTPG", layout="wide")
    st.title("ZipfGuard：动态口令策略风险实验")
    st.caption("离线合成数据与聚合频次实验；不接收真实口令，不执行认证尝试。")
    seed = st.sidebar.number_input("随机种子", min_value=0, value=42, step=1)
    bootstrap = st.sidebar.slider("Bootstrap 次数", min_value=20, max_value=300, value=60, step=20)
    uploaded = st.sidebar.file_uploader("聚合频次 JSON（可选）", type=["json"])
    if uploaded:
        payload = load_count_json(uploaded)
        st.sidebar.success(f"已加载 {payload['dataset_id']}；仅使用 rank/count")
        result = run_pipeline(payload, seed=int(seed), bootstrap_repetitions=int(bootstrap))
    else:
        result = run_pipeline(seed=int(seed), bootstrap_repetitions=int(bootstrap))
    analysis = result["analysis"]
    cols = st.columns(4)
    cols[0].metric("总样本", f"{result['dataset']['total_count']:,}")
    cols[1].metric("类别数", f"{analysis['support_size']:,}")
    cols[2].metric("选择模型", analysis["selected_model"])
    cols[3].metric("1% 风险排名", analysis["risk_threshold"]["model_rank"])
    st.subheader("模型竞争")
    st.dataframe(analysis["models"], use_container_width=True, hide_index=True)
    curves = analysis["curves"]
    if curves:
        st.line_chart({"经验 CDF": {row["rank"]: row["empirical_cdf"] for row in curves}, **{row["id"]: {} for row in []}})
    st.subheader("M3 用户响应与自适应攻击")
    strategy_rows = [{
        "策略": row["policy"]["name"],
        "初始接受率": row["initial_accept_rate"],
        "最终完成率": row["accept_rate"],
        "修改率": row["modification_rate"],
        "最坏冻结风险": row["frozen_risk"],
        "最坏自适应风险": row["adaptive_risk"],
        "适应增益": row["adaptation_gain"],
        "相对基线风险下降": row["security_gain"],
    } for row in result["policies"]]
    st.dataframe(strategy_rows, use_container_width=True, hide_index=True)
    if result.get("policy_search"):
        st.subheader("M4 Pareto 三档建议")
        m4_rows = [{
            "档位": row["tier"],
            "策略": row["policy"]["name"],
            "验证风险": row["validation"]["adaptive_risk"],
            "测试风险": row["test"]["adaptive_risk"],
            "测试风险下降": row["test"]["security_gain"],
            "测试修改率": row["test"]["response"]["modification_rate"],
        } for row in result["policy_search"]["selected_tiers"]]
        st.dataframe(m4_rows, use_container_width=True, hide_index=True)
    st.json(result["recommendations"])
    st.download_button("下载 JSON 报告", json.dumps(result, ensure_ascii=False, indent=2), "zipfguard_report.json", "application/json")


if __name__ == "__main__":
    main()
