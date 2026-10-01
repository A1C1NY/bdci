# 受监督框架契约（交接版 0.6.0）

统一入口为 `python -m research_lab project`。项目 schema_version 仍为 5；软件版本与项目数据格式版本不同。

## 阶段与审查

项目字段为 id、question、model_token_limit、stages。阶段按依赖拓扑排序，包含 id、adapter、needs、role、review、config、inputs、output_schema、max_attempts、token_limit、split。

`inputs` 只能引用配置文件所在目录内的文件。初始化时按哈希保存项目内快照，重复数据只保存一次。执行签名绑定输入、阶段定义、直接依赖结果、适配器源码与项目引擎源码。阶段结果及声明的附件若被修改，会失效并阻塞下游。科研算法还由 STALE 配置中的 source_hashes 在执行时校验；实验开始后仍应固定整个 Git commit。

阶段成功进入 awaiting_review；成功执行不等于研究结论正确。proposal、freeze、interpretation 不允许关闭审核。监督者运行 review，阅读协议、产物与 binding，再用 decide 指定 action、actor、reason、binding。reject、request_changes、terminate 同样保留记录。

普通 advance 只执行本地阶段，付费执行须 --allow-models，联网检索须 --allow-network。阶段锁、项目状态和审核记录持久化。status 和看板只读，不自动修改或审核项目。

## 适配器

内置 artifact、literature_search、literature_cards、native_tasks、proposal、tabular_experiment、comparison、evidence_report；交接版额外注册项目隔离的 STALE retrieval/readers/judges/analysis 和 manuscript_draft。

literature_search 查询 Crossref 元数据，不代表已读取全文。literature_cards 校验本地逐字引文，不能自动证明语义支持。tabular_experiment 的阈值/线性示例用于编排验收，不代表通用科研能力。native_tasks 使用实际修改的 JiuwenSwarm 辅助模块加载真实 SwarmFlow，引擎接收可信 Python，模型输出结构化数据。

## 预算与失败

项目按阶段 token_limit 预留，本地个人模型账本按请求预留并结算。reported_tokens 与未知消耗预留必须区分。外部 Codex 监督消耗未自动计量，多台电脑的预算未集中管理。

同一克隆的原生模型阶段共用执行锁；一个阶段内部最多三个并发任务。跨进程竞争失败不会后台无限重试。失败、格式错误和进程中断留下记录，恢复需要明确审核；不确定请求不能视作未发生。

## 修订与留出集

revise 保留历史并使变动阶段及后继失效；需要重新冻结的协议必须再次审核。holdout 必须直接依赖已审核的 freeze。正式评价开始后该项目不能 revise，正式阶段不允许选择性重试。新的方案应新建项目并披露历史数据暴露。

## 交付边界

模型草稿与最终定稿分开保存。附件哈希证明完整性，不证明科学有效性。框架没有通用模型代码沙箱、开放式自主课题规划器、自动创新性认证、跨机器账本或自动比赛提交。使用者仍须监督选题、文献、实验设计、解释、论文定稿与发布。
