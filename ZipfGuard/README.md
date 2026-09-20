# ZipfGuard / DP-HTPG

新增独立的 **HTPG 九类特征提取入口**：用真实带频次口令文件离线生成特征缓存、频次加权统计和可核对的运行清单。操作、数学定义及与原论文的复现边界见 [HTPG_FEATURES.md](docs/HTPG_FEATURES.md)。这一步只提取特征，尚未接入下述 M1–M4 或网页，不代表已经完成原论文的建议生成与攻击验证。

这是方案 `DP_HTPG_AI_竞赛详细方案.md` 的可运行 MVP。它把有限支持的 Zipf、CDF-Zipf 和 stretched-exponential 模型、风险预算、离线红队、可解释策略和报告导出串成一个可复现实验流水线。

默认实验只使用确定性的公开合成语法。程序先生成一批带固定
`train/validation/test` 划分的模拟用户，再从同一批用户派生频次、策略和攻击实验，避免各模块使用互不相关的数据。

如仅输入聚合频次 JSON，系统只运行分布风险分析，不会虚构需要口令字符串和用户响应信息的策略实验：

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
python run_demo.py --synthetic-size 20000 --synthetic-exponent 1.08 --seed 42
python run_demo.py --input demo_data/synthetic_counts.json --json-out reports/counts_only.json --report-out reports/counts_only.md
```

命令会生成 `reports/*.json` 和 Markdown 报告，并打印模型指标、风险阈值、M2 攻击基线、M3 用户响应与自适应攻击，以及 M4 策略搜索结果。M2 比较训练集频次、公开合成字典和字符 n-gram，报告 cracked@100/1K/10K、候选覆盖率及逐点 95% Wilson 区间。M3 保留每一名被策略拒绝的用户，模拟可预测修补与随机合成短语响应，并同时报告冻结攻击和自适应攻击。M4 枚举单规则与双规则组合，只在 validation 上计算最坏自适应风险、用户响应成本和规则复杂度，构造 Pareto 前沿后选择低摩擦、均衡、高防护三档进入最终 test 评价。当前主线不要求 GPU；PassLLM/PassGPT 属于后续可选扩展，任何攻击器都不得调用认证服务。

可选的 Streamlit 界面：

```powershell
streamlit run web/app.py
```

无需额外 Web 依赖的演示界面：

```powershell
python web/server.py --port 8765
```

打开 `http://127.0.0.1:8765/`，选择合成演示。界面也会报告 PassLLM 0.5B 的基座、LoRA 和运行依赖状态；依赖或权重不存在时明确显示本地 n-gram 回退。

验证：

```powershell
python -m unittest discover -s tests -v
```

结果中的模型曲线和合成红队命中率只描述当前有限支持的模拟实验，不是现实世界的真实密码熵或破解保证。当前进度和验收标准见 `docs/PROJECT_STATUS.md`。
