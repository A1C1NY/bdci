# JiuwenSwarm 源码贡献

当前交接版使用 `contribution_v4_with_tests.patch`；`framework.patch` 和 `contribution_with_tests.patch` 保留为历史较早版本，不要重复叠加应用。

固定上游为 `upstream_v4.json` 记录的 commit。执行 `python scripts/bootstrap.py` 自动下载、应用完整补丁，并按 `patched-files.json` 检查五个修改/新增文件（换行统一为 LF 后比较）。

- common/team_artifacts.py：产物清单和完整性检查，拒绝缺失、损坏、越界等异常。
- common/research_budget.py：跨试验次数和等待时间预算准入。API Token 计量由本项目的 token_ledger / model_client / native_research 实现，二者口径不同。
- common/research_runtime.py：加载固定版本的真实 agent-core SwarmFlow，核对论文主张所引用证据的哈希。
- tests/unit_tests/common 下两份贡献测试：覆盖产物清单、预算、证据门禁和运行时加载。

项目当前执行真实原生工作流并记录 Token；没有部署完整 JiuwenSwarm 产品服务。历史回归和交接版验证范围见 docs/VALIDATION.md。

上游 PR 尚未创建。PR_DESCRIPTION_V4.md 是待团队使用的贡献说明，本仓库的提交不等同于向 JiuwenSwarm 上游提交 PR。比赛贡献认定以主办方审核为准。
