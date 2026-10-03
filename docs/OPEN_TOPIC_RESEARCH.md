# 开放选题自主科研（0.8.0）

给一个宽泛研究目标、可用数据资产和总预算，系统自动检索文献、提出多个课题、检查执行条件、双模型审查并冻结课题，随后进入实验、结果解释、论文写作及材料导出的闭环。正常路径没有人工逐阶段 `decide`。

“开放”指研究问题不必由人提前写定。实验仍由已安装、可验证的执行器承担。当前支持 STALE 检索审计和通用数值表格分类；没有任意学科、任意数据自动下载、任意生成代码执行、GPU 训练或实体实验的能力。超出能力的课题会记录缺口并在选题预算内另提课题；始终找不到可行课题就停止。停止或生成草稿不等于科学发现。

## 从宽泛目标到研究产物

1. 规划至多三个公开文献检索词，包含已有工作/反例检索。
2. 固定 Crossref REST 或 arXiv Atom 接口检索，留存查询、时间、原始响应及摘要/元数据层级。也可仅使用本地来源。arXiv 请求顺序执行、间隔至少三秒，不抓取链接指向的任意页面。
3. 每轮提出二至五个课题卡：问题、假说、证伪条件、与最近工作的差异、数据/计算资源、评价指标及准确摘引。
4. 确定性检查执行器、数据资产、资源、指标与摘引；只有标题的元数据不足以支持研究缺口。
5. 两个不同模型独立审查意义、已有答案、来源深度、混杂、可证伪性与实验条件。机器意见明确标注为机器审查。拒绝原因会进入下一轮规划。
6. 在通过审查的课题中，按规划者给出的相关性/信息价值优先级选择，稳定处理并列。没有正式实验分数参与选题。
7. 开发集内提出和运行方法，按预先规定的规则选择方法；双审查冻结协议后只做一次正式评价。此后不能重新选题、调方法或择优重测。
8. 输出含负结果或不确定结果的论文源文件、选题/评审审计、实验协议、用量报告及复现说明。可选已有 `pdflatex` 编译；缺失时如实记录，不自动安装。

候选课题和实验都保留淘汰记录。新建项目不会自动获得额外个人 Token 额度；付费请求仍经过现有 JiuwenSwarm 计量接口与原模型总账本。

## 零费用完整验收

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m research_lab discover init projects/open-demo-01 --config config/projects/open-topic-fixture.json
.\.venv\Scripts\python.exe -m research_lab discover run projects/open-demo-01 --fixture
.\.venv\Scripts\python.exe -m research_lab discover status projects/open-demo-01
```

使用尚不存在的项目 ID。该流程的文献、模型和数据均为合成验收；17 次脚本 worker 调用不等于真实模型调用，生成文稿不能作为比赛研究成果。可以用 `--max-steps 5` 分段运行，重复 `run` 恢复且不重复已完成请求。完成后只校验，不重新搜索。

## 真实研究配置

先按 [队友指南](TEAM_HANDOFF.md) 配置自己的模型、密钥和个人总额度。两个评审别名必须指向不同实际模型。内网地址需具备连通性；框架不会清空账本或绕过网关。

数据资产清单是本地 JSON，例如 `.local/numeric-asset.json`：

```json
{
  "id": "my_numeric_dataset",
  "domain": "tabular_classification",
  "description": "Describe the prediction task and its scientific context.",
  "provenance": "Dataset URL, version and actual preparation procedure.",
  "license": "Actual dataset license and permitted use.",
  "unit_of_analysis": "State the independent unit and how correlated rows were handled.",
  "data_exposure": "reused",
  "training": "training.json",
  "development": "development.json",
  "evaluation": "evaluation.json",
  "baseline": {"algorithm": "centroid", "standardize": false, "k": 1, "l2": 0, "epochs": 10}
}
```

每个 split 为 `[{"id":"sample_a","x":[0.1,2.5],"y":0}, ...]`，至少两行。训练集至少含两个类别；`x` 为固定宽度的有限实数数组，`y` 为 0–19 的整数类别，实际类别必须在训练集出现。当前限制每份 split 至多 10000 行、128 个特征。唯一 ID、跨 split 重复行和重新标注的同特征行都会检查。不自动证明样本独立，也不自动清洗缺失值、类别特征或切分同一主体的多行数据；资产提供者应完成预处理并记录来源。

分类器有 nearest centroid、kNN、L2 softmax；标准化和学习参数只使用训练集。模型只收到资产描述与实验汇总，不收到逐行特征、标签或正式评价数据。

STALE 资产将 domain 改为 `stale_retrieval`，省略 training；baseline 为 `{"relevance":1,"recency":0,"change":0}`，可设置 `context_bytes`。使用实际 STALE 两份 split 及来源/许可；该能力只测字面更新事实包含率。历史用过的数据必须标记 `reused`，重新切分不变成全新测试集。

可选来源清单为 JSON 数组，每项包含 `id`、`title`、`url`、`path`、`evidence_level`；层级可为 `full_text_extract` 或 `abstract`。每篇最多 20KB，合计最多 40KB。可补足检索接口缺少摘要的问题；摘录须来自实际来源，不能将模型生成摘要填成全文。

```powershell
# 数值仅为此次活动的示例额度，不代替个人/团队授权。
.\.venv\Scripts\python.exe scripts/prepare_open_research.py --brief "Explore when scaling and local voting help small classification problems" --asset .local/numeric-asset.json --output .local/open-campaign.json --deepseek-budget 2000000 --kimi-budget 4000000
.\.venv\Scripts\python.exe -m research_lab discover init projects/alice-open-01 --config .local/open-campaign.json
.\.venv\Scripts\python.exe -m research_lab discover run projects/alice-open-01 --allow-models
```

`--asset` 可重复以注册多个数据集；`--sources .local/sources.json` 加入来源。`--literature arxiv` 可用于计算机科学等预印本摘要检索，查询词为英文科学关键词。默认 Crossref 的部分条目可能只有标题，此时可改选 arXiv 或补充本地来源。`--literature local` 禁用网络检索且必须提供来源；此时检索计划只是本地阅读规划，不宣称已联网搜索。初始化快照全部输入并冻结实现和预算，模型没有权限修改这些条件。

## 预算、恢复与故障

总 Token 额度、模型调用上限和墙钟期限覆盖检索规划、选题、审查、实验设计、写作全部阶段，不会在选题或换题时重置。跨活动个人账本仍独立生效。未结算请求保留预留；Token 数是已结算加保留预留，不全部代表供应商已报告用量。

网关在请求前连接失败时状态为 `waiting_for_gateway`，没有付费 intent；连接恢复后重运行同一命令。已发出请求结果未知则为 `needs_attention`，不能自动重发冒充幂等。公开文献只读请求失败会记录错误并继续有限次查询；缺证据则停止。耗尽预算/期限、无法支持的解释、审查拒绝都有终止原因。没有无限后台重试或计划任务。

旧 `autonomous` 和 `project` 入口保持原语义，0.7 核心源码未在此升级中改写。开发过程中的 0.8 合成项目可能绑定中间版本，保留它们并为验收创建新 ID。

## 看板与交接

运行 `python -m research_lab usage-server --port 8768`。看板新增选题轮数、候选问题、执行能力、审查/缺口、冻结课题、当前阶段及各模型活动预算；仍为只读。私密账本路径、模型路由和原始请求不作为公开投影视图。

结果位于 `projects/<id>/evidence/deliverables/`：`paper_draft.md`、`paper.html`、`paper.tex`、`claims.json`、`topic_audit.json`、`review_audit.json`、`resource_report.json`、`protocol.json`、`REPRODUCE.md`。文稿是机器审查过的草稿；作为比赛稿前需核对排版、比赛材料和外部评审要求。不会自动取得 Stanford Reviewer Token、上传新稿、提交比赛或创建上游贡献 PR。

参考：[Crossref 官方 REST API 文档](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)、[arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)。元数据或摘要不保证全文覆盖、新颖性或已通过同行评审。
