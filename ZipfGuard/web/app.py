"""Streamlit controls for the shared Python experiment and HTML presentation."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from core.data import load_count_json
from experiments.config import load_config
from web.server import execute_request
from web.presentation import report_html


def main():
    import streamlit as st
    import streamlit.components.v1 as components
    st.set_page_config(page_title="ZipfGuard 实验台", layout="wide")
    st.title("ZipfGuard：离线策略风险实验")
    st.caption("统一 Python 实验核心；PassLLM 尚未接入主评估，当前实验未使用。")
    preset = st.sidebar.selectbox("预设", ["quick", "full"], format_func=lambda v: "快速演示 · 1,000 用户" if v == "quick" else "完整实验 · 20,000 用户 + 可选 PCFG")
    cfg = load_config(preset=preset)
    source = st.sidebar.selectbox("数据来源", ["synthetic", "upload", "rockyou"], format_func=lambda v: {"synthetic":"合成用户", "upload":"聚合 JSON 上传（仅分布分析）", "rockyou":"RockYou 聚合（仅分布分析）"}[v])
    with st.sidebar.form("experiment_" + preset):
        cfg["seed"] = st.number_input("随机种子", min_value=0, max_value=2**32-1, value=cfg["seed"])
        cfg["synthetic"]["size"] = st.number_input("样本规模", min_value=100, max_value=1_000_000, value=cfg["synthetic"]["size"])
        cfg["synthetic"]["exponent"] = st.number_input("Zipf 指数", min_value=0.01, max_value=5.0, value=cfg["synthetic"]["exponent"])
        budgets = st.text_input("攻击预算（逗号分隔）", ",".join(map(str,cfg["budgets"])))
        cfg["bootstrap_repetitions"] = st.number_input("Bootstrap 次数", min_value=20,max_value=1000,value=cfg["bootstrap_repetitions"])
        cfg["q"] = st.number_input("风险阈值 q",min_value=0.001,max_value=0.999,value=cfg["q"],format="%.3f")
        selected = {}
        for aid in ("frequency","synthetic-dictionary","character-ngram","pcfg"):
            options = ["off","required","optional"]
            mode = st.selectbox("攻击器：" + aid, options, index=options.index(cfg["attackers"].get(aid,"off")), format_func=lambda v:{"off":"不参与","required":"必选","optional":"可选"}[v])
            if mode != "off": selected[aid] = mode
        cfg["attackers"] = selected
        cfg["pcfg"]["generation_limit"] = st.number_input("PCFG 候选上限", min_value=1,max_value=1_000_000,value=cfg["pcfg"]["generation_limit"])
        cfg["pcfg"]["timeout_seconds"] = st.number_input("PCFG 超时秒数",min_value=1,max_value=3600,value=cfg["pcfg"]["timeout_seconds"])
        response = st.selectbox("用户响应模型",["修补优先","短语优先"])
        cfg["response"]["order"] = ["append-symbol","append-symbol-digit","random-phrase"] if response == "修补优先" else ["random-phrase","append-symbol","append-symbol-digit"]
        weight = st.slider("响应成本权重（其余为规则成本）", 0.0,1.0,cfg["search"]["response_cost_weight"],0.05)
        cfg["search"].update(response_cost_weight=weight,rule_cost_weight=1-weight)
        cfg["search"]["risk_budget"] = st.number_input("策略选择预算",min_value=1,max_value=1_000_000,value=cfg["search"]["risk_budget"])
        policies = st.text_area("待比较策略 JSON（保留 baseline）",json.dumps(cfg["comparison_policies"],ensure_ascii=False,indent=2))
        advanced = st.text_area("完整配置覆盖 JSON（可选；优先于上面控件）", "")
        uploaded = st.file_uploader("聚合频次 JSON",type=["json"])
        semantics = st.selectbox("RockYou 来源类型",["unknown","frequency","unique_dictionary"])
        max_lines = st.number_input("读取行数",min_value=20,max_value=10_000_000,value=1_000_000)
        top_k = st.number_input("保留 top-k",min_value=2,max_value=100_000,value=2000)
        submitted = st.form_submit_button("运行实验")
    if submitted:
        st.session_state.pop("result",None)
        try:
            cfg["budgets"] = [int(v.strip()) for v in budgets.split(",")]
            cfg["comparison_policies"] = json.loads(policies)
            if advanced.strip(): cfg = json.loads(advanced)
            if source == "upload" and uploaded is None: raise ValueError("请先选择聚合频次 JSON")
            payload = load_count_json(uploaded) if source == "upload" else None
            with st.spinner("正在计算实验…"):
                st.session_state["result"] = execute_request({"config":cfg,"source":source,"payload":payload,
                    "source_semantics":semantics,"max_lines":max_lines,"top_k":top_k})
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            st.error("实验未完成：" + str(exc))
    result = st.session_state.get("result")
    if result:
        components.html(report_html(result),height=1400,scrolling=True)
        content = (json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False) + "\n").encode("utf-8")
        st.download_button("下载 JSON 报告",content,"zipfguard_report.json","application/json")
        st.download_button("下载 SHA-256 校验",hashlib.sha256(content).hexdigest()+"  zipfguard_report.json\n","zipfguard_report.json.sha256")
        st.download_button("下载本次完整配置",json.dumps(result["reproducibility"]["config"],ensure_ascii=False,indent=2),"experiment.json","application/json")
    else:
        st.info("选择预设或调整参数，然后点击运行实验。聚合数据只展示分布分析。")

if __name__ == "__main__": main()
