# AI 红队适配器

`attacker_adapter.py` 为 PassLLM/PassGPT 0.5B 提供统一的离线 JSONL 接口。模型命令从标准输入读取一行策略 JSON，向标准输出写入若干行 `{\"guess\": ..., \"rank\": ..., \"logprob\": ...}`。适配器不连接认证服务，也不保存真实凭据。

没有模型时，将 `command` 留空并把现有 `src/lib/redteam.js` 的候选排序函数包装成 `NgramAttacker`，即可运行无 GPU 演示。

工作区中已发现 PassLLM 0.5B Rockyou LoRA：

- `PassLLM原版/Available artifacts for USENIX Security 2025 #772-v1/checkpoints/rockyou_100w_disQwen0.5B`
- 基座：`PolyPass/model/Qwen0.5B-Instruct`

`passllm_adapter.py` 会延迟检查 `torch`、`transformers` 和 `peft`，因此界面可以在无模型运行环境下启动，并把回退原因展示出来。完整 PassLLM 动态 beam 搜索仍通过上游 `dsgen/widthgen` 配置执行；ZipfGuard 不会自动启动长时间训练或生成任务。
