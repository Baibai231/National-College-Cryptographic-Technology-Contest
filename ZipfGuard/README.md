# ZipfGuard / DP-HTPG

这是方案 `DP_HTPG_AI_竞赛详细方案.md` 的可运行 MVP。它把有限支持的 Zipf、CDF-Zipf 和 stretched-exponential 模型、风险预算、离线红队、可解释策略和报告导出串成一个可复现实验流水线。

默认实验只使用确定性的合成数据。输入真实数据时请使用聚合频次 JSON，不要上传明文口令：

```json
{
  "dataset_id": "synthetic_demo_v1",
  "total_count": 100000,
  "items": [{"rank": 1, "count": 4312}, {"rank": 2, "count": 2978}],
  "metadata": {"synthetic": true, "source": "public grammar"}
}
```

在 `ZipfGuard` 目录中运行（使用系统 Python 或环境提供的 Python）：

```powershell
python run_demo.py --bootstrap 120
python run_demo.py --input demo_data/synthetic_counts.json --json-out reports/result.json --report-out reports/result.md
python run_demo.py --rockyou ..\lab_basic_50_dicts\Rockyou.txt --max-lines 1000000 --top-k 2000
```

命令会生成 `reports/*.json` 和 Markdown 报告，并打印模型指标、风险阈值、策略成本与离线 `cracked@K` 对比。无 GPU 时使用本地合成频次/结构基线；配置 PassLLM/PassGPT 时，`ai/attacker_adapter.py` 通过 JSONL 子进程接口接入，仍然不调用认证服务。

可选的 Streamlit 界面：

```powershell
streamlit run web/app.py
```

无需额外 Web 依赖的演示界面：

```powershell
python web/server.py --port 8765
```

打开 `http://127.0.0.1:8765/`，然后选择合成演示或 Rockyou 聚合。界面会报告 PassLLM 0.5B 的基座、LoRA 和运行依赖状态；若 Torch/Transformers/PEFT 不可用，会明确显示本地 n-gram 回退。

验证：

```powershell
python -m unittest discover -s tests -v
```

结果中的 surprisal、模型曲线和合成红队命中率只描述当前有限支持实验，不是现实世界的真实密码熵或破解保证。
