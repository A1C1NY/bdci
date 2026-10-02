# 自主科研模式 0.7.0

`research-lab autonomous` 是独立入口。初始化时给定研究问题、可信实验家族、开发/正式评价数据、文献文本和预算，随后一条 `run` 命令自动完成候选提案、设计审查、实验、搜索决策、冻结、正式评价、解释审查、写作和文稿审查。正常流程无需人工逐阶段 `decide`。原来的 `project` 工作流保留原有受监督语义。

## 当前可执行范围

- 真实研究：STALE 对话检索，自动搜索 BM25 相关性、时间顺序和变化线索的组合权重；使用固定字节预算和固定的新事实字面包含指标。
- 合成验收：阈值分类小数据，只验证编排、停止、恢复和审查路径，不提供科研效果证据。
- 模型可提出和修订受 schema 限制的方法参数，不能修改数据、评价代码、正式评价次数或执行任意 Python。新领域需要添加经测试的可信适配器。
- 研究方向及允许使用的来源由初始化配置提供。模型阅读文本快照并用逐字引文支撑提案；本版没有开放式网络选题、任意代码生成沙箱或人工可靠性认证。

这是限定领域的自主闭环，不能称为任意课题的通用自动科学家。多个模型意见一致也不证明科学结论正确。

## 零 API 费用验收

按 README 安装依赖和上游源码后：

```powershell
$env:PYTHONUTF8 = "1"
.venv/Scripts/python.exe -m research_lab autonomous init projects/alice-auto-check --config config/projects/autonomous-fixture.json
.venv/Scripts/python.exe -m research_lab autonomous run projects/alice-auto-check --fixture
.venv/Scripts/python.exe -m research_lab autonomous status projects/alice-auto-check
```

输出应为 `completed`，`fixture_only: true`，真实模型调用意图 `model_calls: 0`。`worker_calls` 是脚本化角色调用数。重复 run 校验产物并返回，不重新发起工作。合成 worker 不能用于真实 STALE 配置。

## 初始化真实研究

先按队友指南配置个人模型、既有账本和分配额度。仍可用 `RESEARCH_LAB_MODELS_CONFIG` 指向原配置；不要重建账本。准备本地 JSON 文献清单，例如 `.local/my-sources.json`：

```json
[{"id":"stale","title":"填写实际文献标题","url":"填写实际公开来源URL","path":"sources/stale.txt"}]
```

`path` 相对清单解析，文本应是已核实的文献全文或明确范围的原文摘录。每篇最多 60KB，整包最多 70KB；来源有限时论文必须明确局限。程序只能检查引文存在，不能认证来源真实性或引文是否支持结论。

以下预算只是命令示例，使用前必须在团队授权额度内分配：

```powershell
.venv/Scripts/python.exe scripts/prepare_autonomous_stale.py --dataset data/stale/T1_T2_400_FULL.json --sources .local/my-sources.json --output .local/alice-auto-01 --deepseek-budget 2000000 --kimi-budget 4000000
.venv/Scripts/python.exe -m research_lab autonomous init projects/alice-auto-01 --config .local/alice-auto-01/config.json
.venv/Scripts/python.exe -m research_lab autonomous run projects/alice-auto-01 --allow-models --wait-seconds 1800
```

准备脚本按类型与固定哈希顺序各分一半作为开发/正式评价数据，明确标记 `reused`。划分不能让此前使用过的 STALE 变成未见测试集。初始化拒绝两份数据 ID 重叠及去掉 ID 后完全相同的记录。输入和源码按哈希冻结；原始数据、配置快照、生成稿件与请求均不进入 Git。

准备脚本默认最多 3 个候选，连续 2 次未改善停止搜索，最多 2 次文稿修订、40 次角色调用，整个活动最长 6 小时。需要改变范围时，在初始化前修改配置。运行后的配置不可原地修改。`max_steps` 可用于有意分段执行，正常无人值守运行不用它。

## 自动决策如何约束

1. Director（默认 Kimi）仅根据文献和开发历史提出一个可否证候选。来源引文、参数范围和候选去重由程序检查。
2. DeepSeek 与 Kimi 分别看到同一绑定证据，独立返回批准、修订或停止。二者都批准才能执行该候选；机器审核不会伪装为人工批准。
3. 可信评价器执行开发实验，严格按已冻结的指标和改善阈值更新最佳候选。无改善和失败记录都保留。Director 可提前停止；次数、时间和预算上限仍由程序执行。
4. 冻结选择经过再次审查，只在开发结果上选方法。正式评价开始前写入持久化标记，之后没有返回搜索的路径；文稿修订也不会重跑正式评价。
5. 配对场景统计由程序计算。模型审查解释和文稿；争议不能解决时停止并保留证据，不强行产出成功论文。

本模式通过真实 JiuwenSwarm / SwarmFlow 调用已配置模型，与原工作流共用本机执行锁及模型账本。另加活动级各模型预算，所有请求先预留后结算。断线预检查不产生请求预留；请求发出后状态不明则保留预留，不盲目重发。跨机器的团队总预算仍须分配，尚无集中式配额服务。

## 运行状态与恢复

看板仍通过 `research-lab usage-server` 启动。自主项目显示当前阶段、候选次数、开发指标、机器审查、正式评价状态、额度和交付文件。看板只读，不代替控制器执行。

- `completed`：流程及文稿机器审查完成，不表示发表质量达标。
- `stopped`：科学审查或停止条件终止研究；查看 stop_reason 和全部原始证据。
- `waiting_for_gateway`：连接预检查失败，尚未产生对应模型调用。`--wait-seconds` 内会间隔等待，否则恢复网络后再次 run。
- `budget_exhausted` / `deadline_exceeded`：硬上限触发，不能通过重新 run 重置。
- `needs_attention`：未知请求、输入/证据问题或其他不能安全自动处理的错误；保留记录，不能删除请求或修改状态来补跑。

进程崩溃后，已提交完整 receipt 的操作可恢复而不重做。没有完整 receipt 的操作不会自动重复，特别是未知付费调用和正式评价。失败依然可能需要人工介入；正常科研节点不需要持续监督。

## 交付内容

`projects/<id>/evidence/deliverables/` 包含英文论文草稿、可阅读 HTML、LaTeX 源码、固定数值结果、资源报告、审查记录、协议及复现说明。完整项目还包含所有候选、原始实验上下文和模型请求的证据绑定。

`compile_pdf: true` 时使用已有 `pdflatex`，禁用 shell escape，并限制编译时间。有通过校验的官方 ICLR 样式时自动使用，否则保留普通 article 源码。编译器缺失或编译失败会如实标记，不把源文件当作已生成 PDF。框架不会安装 TeX；在 Codex 编辑独立 LaTeX 可用内置编辑器和编译器。

机器审查后的稿件仍不保证创新性、语义评价有效性、参考文献完整性或符合比赛篇幅。新 PDF 的外部 Reviewer Token、比赛上传和上游贡献 PR 是独立交付事项，本模式不会自动执行。不能复用旧稿凭证。
