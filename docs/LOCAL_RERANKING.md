# 本地学习式重排研究

这是无需模型网关的受监督研究入口，补充原有 BM25 检索基线。使用固定版本的 MS MARCO MiniLM-L6 量化交叉编码器，在 CPU 上对每条查询的同一组 BM25 前 32 个候选排序。网络仅用于首次下载公开模型和数据，运行阶段不调用 DeepSeek 或 Kimi。

## 安装与创建

先完成 README 的基础安装，再执行（Python 路径按平台调整）：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-reranking.lock
.venv/Scripts/python.exe scripts/fetch_assets.py reranker
.venv/Scripts/python.exe scripts/fetch_assets.py stale
.venv/Scripts/python.exe scripts/reranking_study.py init --project projects/alice-reranking-01 --dataset data/stale/T1_T2_400_FULL.json
.venv/Scripts/python.exe scripts/reranking_study.py advance --project projects/alice-reranking-01
.venv/Scripts/python.exe scripts/reranking_study.py review --project projects/alice-reranking-01 --stage brief
```

Windows 若 Python 的 TLS 连接失败，但 PowerShell 能访问同一官方地址，可在下载命令后添加 `--transport powershell`。两种传输均保留 TLS 验证，并核对同一 SHA256；已存在但校验不符的文件不会覆盖。

模型约 23MB，数据约 306MB；实验保存每条查询的实际上下文，需要额外磁盘空间。初始化会冻结数据、协议及相关实现的哈希。数据引用是本机绝对路径，原始数据文件需一直保留；迁移电脑时应重新初始化独立项目。运行过程中不要修改冻结源码或数据。项目、缓存和结果均保留在 Git 忽略目录。

## 监督节点和进度

阶段为 `brief → freeze → retrieval → analysis`。每次 `advance` 推进一个已满足依赖的阶段，阶段完成后需监督者查看 `review`，使用返回的当前 binding 作决定：

```powershell
.venv/Scripts/python.exe scripts/reranking_study.py decide --project projects/alice-reranking-01 --stage brief --action accept --actor alice --reason "填写实际审查结论" --binding "填写本次审核包的binding"
.venv/Scripts/python.exe scripts/reranking_study.py advance --project projects/alice-reranking-01
```

后续按相同方式审核 freeze、retrieval 和 analysis。保留全部失败记录；缓存只复用输入、模型及实现身份相同的评分，不会自动验收结果。标准 `research_lab project status/review` 也能识别这些适配器。

运行时每 10 个场景输出一次进度，每个场景更新 `projects/<id>/evidence/<run-id>/progress.json`，记录已完成场景、CPU 推理对数、推理和墙钟时间。这里的参考上下文 token 与 API 计费 token 分开；本地研究的网关调用数为 0。

## 固定比较与结论边界

五个方法为全候选 BM25、前 32 候选 BM25、相同候选的学习式重排，以及后两者各自的查询窗口截取版本。每个方法都使用 512、1024、2048 个参考 WordPiece token 的预算，最终上下文重新计数。窗口为查询词重合最多的句子及前后各一句；窗口排序仍沿用父段落分数。

主比较固定为 1024 token 下学习式重排相对同候选 BM25 的新事实字面包含率变化。按场景聚合三条查询，再进行 10,000 次配对 bootstrap；其余比较作为描述性分析，不按最好结果更换主指标。

这份协议明确标为复用 STALE 数据的回顾性诊断，不能当作未见测试集。模型测的是查询相关性，不能自动判断事实是否过期；256 token 的成对输入截断可能丢失信息。WordPiece 也不是 DeepSeek/Kimi 的实际 tokenizer。字面包含和连续 token 包含均不能证明语义蕴含或回答正确率。只有完成另行冻结的读者实验和证据审查，才能提出回答质量或新论文贡献的结论。
