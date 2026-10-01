# 队友安装和运行指南

## 1. 每人一份本地克隆

按 README 安装 Python 3.12 虚拟环境、锁定依赖及固定版本源码。`bootstrap.py` 会从官方仓库取得 JiuwenSwarm 和 agent-core，应用并核对团队补丁；重复执行会校验已有文件，不覆盖不同版本或异常修改。需要联网下载，但不需要模型 Key。Windows 已验证；Ubuntu 由 CI 检查，见验证记录。

不要复制队长的 `.env.local`、`.local/model-usage` 或正在运行的 `projects/`。不要让五个人共享一个可写目录。开发时在自己的分支操作，不在正在执行的研究过程中修改框架源码。

## 2. 模型 Key 与个人额度

`scripts/setup_member.py` 需要成员 ID、两个模型各自的预算。它只创建本地配置，不测试连接、不启动实验。已存在配置时拒绝重建，以防误清预算。随后编辑：

- `.env.local`：`DEEPSEEK_API_KEY`、`RESEARCH_KIMI_API_KEY`。
- `.local/models.json`：API 地址（通常含 `/v1`）、模型名、`chat` 或 `responses`、超时、个人 Token 上限。

API Key 可以来自环境变量，优先于本地文件。密钥不要填写进模型 JSON、项目配置、GitHub Issue 或 PR。内网服务需要队友电脑能够访问；程序不会自动建立 VPN 或转发。

默认读取 `.local/models.json`；可用环境变量 `RESEARCH_LAB_MODELS_CONFIG` 指定另一个配置文件，所有原生工作流和看板都会使用它。配置中凭证和账本路径相对于该 JSON 文件解析。同一个人换配置时仍应指向已有账本，不应借新建账本绕过额度；相同服务的模型别名保持一致。

需要确认服务时，以下命令**会消耗少量 API Token**：

```powershell
.\.venv\Scripts\python.exe -m research_lab model-check --model deepseek
.\.venv\Scripts\python.exe -m research_lab model-check --model kimi
```

账本先预留、后结算；未知请求保留预留，不能把预留当作服务端已报告消耗。Codex 等外部监督工具的用量不在此账本内。五台电脑没有统一预算服务器，团队须分配额度并汇总各人报告。

## 3. 本地无费用验收

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/verify_projects_v5.py --output projects/local-check-01
```

测试使用合成数据、替身模型和本地 HTTP 服务。示例中的 `fixture-validator` 自动验收仅针对预先已知的测试数据，不能搬到真实科研中代替监督者。

## 4. 跑通独立 STALE 研究

这是已有研究的**可复现起点**，不是新选题自动生成器。需要联网下载约 306MB 数据，创建项目还需存储配置和项目数据快照，建议预留数 GB 空间。先阅读 [STALE 数据卡](https://huggingface.co/datasets/STALEproj/STALE) 和随下载保留的 LICENSE、LongMemEval_LICENSE。

```powershell
.\.venv\Scripts\python.exe scripts/fetch_assets.py stale
.\.venv\Scripts\python.exe -m research_lab.study --id alice-stale-01 --dataset data/stale/T1_T2_400_FULL.json --readers-per-type 2 --seed alice-pilot-01
.\.venv\Scripts\python.exe -m research_lab project advance projects/alice-stale-01
.\.venv\Scripts\python.exe -m research_lab project review projects/alice-stale-01 brief
```

监督者阅读 `review` 的协议、完整产物和 binding 后作决定。下面两项替换为实际内容，不要原样粘贴：

```powershell
.\.venv\Scripts\python.exe -m research_lab project decide projects/alice-stale-01 brief --action accept --actor alice --reason "实际核对内容与理由" --binding "review返回的binding"
.\.venv\Scripts\python.exe -m research_lab project advance projects/alice-stale-01 --allow-models
.\.venv\Scripts\python.exe -m research_lab project status projects/alice-stale-01
```

依次审核 design、freeze、retrieval、readers、judges、analysis、interpretation、draft、manuscript。根据 status 中的 `awaiting_review` 选择阶段。每次验收后才能执行依赖它的阶段，不存在定时替你批准的后台服务。

项目配置在 `.local/study-configs/alice-stale-01/project.json`，项目状态在 `projects/alice-stale-01/project-state.json`。输入数据按内容哈希去重保存，执行附件按每次尝试隔离。模型原始响应和请求在 `outputs/v4-project-*/`；这里的 `v4-` 是兼容的目录前缀，不表示正在重写历史 V4。

默认每类 2 个场景，两个模型、两种自然检索上下文；无 oracle 干预。项目上限按阶段预留之和生成，个人模型总上限仍独立生效。扩大样本前核对两个上限。已有 ID 不能重复初始化；新协议使用新 ID。需要继续同一项目时直接 status/review/advance，保留失败记录，不删目录补跑。

## 5. 从结果到论文

最后阶段输出 `projects/<id>/evidence/<run-id>/paper_draft.md` 与证据 JSON。这是待编辑模型草稿，必须由监督者补齐已核实的文献、方法、结果表和局限；不能直接作为比赛论文。

通用编译器 `research_lab.manuscript.compile_document` 支持结构化文稿、证据哈希和 ICLR 样式。`python scripts/fetch_assets.py iclr` 获取带校验的官方模板；队友在命令行构建时需要自己的 `pdflatex` 环境，可设置 `RESEARCH_LAB_TEX_BINARY`。运行科研、看板和测试不需要 TeX。使用 Codex 编辑独立 LaTeX 时可使用其内置编辑器与编译预览。

最终文稿必须绑定实际代码、配置、数据和实验记录。新 PDF 需要它自己的 Agentic Reviewer Token，不能复用 V4 或其他成员凭证。框架不自动上传论文、不自动向比赛提交。

## 6. 给队长交接

通过团队私下渠道交接完整 `projects/<id>`、相应 `.local/study-configs/<id>`、项目关联 `outputs/v4-project-*`、论文源文件与 PDF、资源报告、评审结果及匹配 Token。不要附 `.env.local` 或个人模型配置中的密钥。记录运行时 Git commit，保留数据来源/哈希和需要复现的代码；通用配置不含凭证。

在候选登记中填写 `docs/candidate-template.json` 所列字段。不要把这些原始数据、模型响应或凭证提交到当前公开仓库。需要共享可公开配置时，清理后放进 `config/projects/`，通过 PR 审核。

比赛正式包还需按官方目录包含 `paper/paper.pdf`、`AgenticReviewer/PaperReview-AccessToken.txt`、`code/`、三份指定 docs、框架贡献说明及上游 PR 链接、资源报告和提交说明。不能用本仓库 ZIP 直接替代比赛包。
