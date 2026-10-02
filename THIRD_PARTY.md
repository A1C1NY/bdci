# 第三方来源与贡献边界

- JiuwenSwarm：<https://github.com/openJiuwen-ai/jiuwenswarm>，固定 `ce8af2051fd7c5dff85a09f8185fce64d32893a6`，上游 Apache-2.0。下载时保留上游 LICENSE；团队修改及测试以 patch 保存，补丁沿用对应上游许可。见 `integrations/jiuwenswarm/upstream_v4.json`。
- openJiuwen agent-core：<https://github.com/openJiuwen-ai/agent-core>，固定 `9e3390195a9ea15235b2b5f7412cb2aa440622cc`；下载保留上游许可。本项目加载真实 SwarmFlow 引擎，没有在此复制实现或启动完整产品服务。
- STALE：<https://huggingface.co/datasets/STALEproj/STALE>，固定 `617c51dc200b5ab09970834144c7e51c77959af0`；下载 README、LICENSE、LongMemEval_LICENSE 和数据并核对哈希。使用前自行阅读这些条款，不能把原始数据随公共代码一起发布。
- ICLR 模板：<https://github.com/ICLR/Master-Template>，仅用于论文格式，不代表 ICLR 投稿或录用。模板文件从上游下载并按归档 SHA256 检查；上游 URL 如发生变化则拒绝不匹配内容，需要维护者核对后更新清单。保留下载文件中的原作者和许可说明。

本仓库未替团队原创代码另行选择开源许可证；公开可见不等于统一授予 Apache-2.0 或其他许可。团队若决定正式开源，应确认原创代码授权，并保留各第三方的原有许可和署名。

- 可选本地重排模型：[cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)，固定 `233902d25c440f23af6f7d6e94d2946bac0bee0a`，模型卡标注 Apache-2.0。下载保留模型卡，按 SHA256 核对 ONNX 权重与 tokenizer；模型文件不进入 Git。
