# 从复现起点开发新课题

`research_lab.study` 固定复用句子/整轮 BM25 等既有比较，是测试安装、个人模型和受监督流程的起点。仅改变随机种子、模型或论文措辞，不会自动构成新的科研贡献。

开展新课题时：

1. 创建 Issue，写清研究问题、已有工作的差别、可否证假设、主要对比、数据使用条件、预算和监督人。不得提交密钥、原始受限数据或评审凭证。
2. 在 `config/projects/` 放公开的协议模板；私有数据和运行状态放忽略目录。为新的实验函数添加可信 Python 适配器及有意义的测试。
3. `Context` 提供 `root`、`stage`、`inputs`、`dependencies`、唯一 `run_id`。从 `inputs` 读取快照，从 `dependencies` 读取已验收产物；模型仅返回结构化数据，不执行模型生成的代码。
4. 在 `project_adapters.adapters()` 显式注册适配器，配置无法随意指定任意 Python 模块。执行器返回 JSON，使用 `output_schema` 检查；需要模型的适配器标记 `paid=True`，联网的标记 `network=True`。
5. 附件写入 `context.root/evidence/<run_id>/`，结果的 `artifacts` 使用项目相对路径和 SHA256。不要硬编码全局 `research/v5` 或另一个成员目录。框架会核对附件是否被改动，并阻止依赖失效产物继续执行。
6. proposal、freeze、interpretation 必须审核。正式 holdout 需要已审核的 freeze，不能把正式评价反馈给开发提案。此前已接触的数据应如实标注，不能因新建项目改称未见测试集。
7. 在新项目中用小规模合成/开发数据验证，再冻结真实协议和运行 commit。保存零效果、负结果、错误与不确定请求，禁止挑选性删除失败重跑。

通用命令：

```text
python -m research_lab project validate config/projects/my-study.json
python -m research_lab project init projects/alice-my-study-01 --config config/projects/my-study.json
python -m research_lab project advance projects/alice-my-study-01
python -m research_lab project review projects/alice-my-study-01 <stage>
```

修改协议用 `project revise --config ... --actor ... --reason ...`；失败重试需要 `project retry <project> <stage> --actor ... --reason ...`。正式评价开始后原项目不可 revise，不能选择性重试正式阶段；改变研究方案应新建项目，保留历史暴露记录。

进程内动态注册也可使用 `Project(path, registry={**adapters(), "my_adapter": Adapter(fn)})`。CLI 和看板只能识别代码中注册的适配器，因此准备交给队友的功能应显式纳入注册表及测试。

一个本地克隆内原生模型阶段使用共享执行锁，阶段内部最多 3 个并发任务。多项目同时抢锁可能记录失败而非排队；建议一台电脑顺序调度付费阶段。不同电脑分别运行，不共享锁或账本。并发的全局网关限流和跨成员配额管理尚未实现。
