# 统一攻击适配器

所有可评价攻击器实现 `BaselineAttacker.fit_select_rank(train, validation, candidates)` 并返回 `RankingResult`。频次、合成字典与字符 n-gram 位于 `core/attackers.py`；PCFG 位于 `ai/pcfg_adapter.py`。`NgramAttacker` 只是同一个 Python 字符模型的兼容名称，不再接收 JavaScript 排序函数。

## 本地命令 JSONL 桥接

`CommandAttacker(AttackerConfig(command=[...]))` 的单次调用从标准输入传递一个 JSON 对象：

- `protocol`：`command-jsonl-v2`。
- `train`：调用方提供的训练字符串，不包含 test。
- `candidates`：当前公开候选集合。
- `max_guesses`、`seed`、`metadata`：配置的上限、种子和额外参数。

命令每行输出一个含字符串 `guess` 的 JSON 对象。适配器校验输出上限、去重并匹配公共候选，返回统一结果与生成统计；超时和错误显式抛出。此桥接仍属于封闭候选排序，不是开放生成预算协议，也不意味着某个神经模型已经通过实际集成验收。配置文件只允许当前已验收的四类攻击器；命令桥接用于程序化扩展。

## PassLLM

`runtime_status` 区分环境可用性和评估参与状态。`integrated=false`、`participated=false`，没有自动替换。未实现的空评分和延迟加载后抛错生成接口已移除；占位类若被误用于统一评价，直接说明尚未接入。当前不下载模型、不启动训练，不声称 PassLLM 已参加实验。

## 可选失败

注册层只在实际模型调用处包装失败。可选失败被流水线捕获后，从整次实验删除该模型并重跑，防止某些策略有 PCFG 而另一些策略没有。每个失败模型记录原因和排除状态。必选模型失败立即报错。
