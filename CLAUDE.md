# DramaForge 开发入口

本文件只为编码 Agent 导航；产品、技术、模型供应和阶段顺序由 Owner 指定的七方案决定。

开始任何改动前依次读取：

1. [`AGENTS.md`](AGENTS.md)；
2. [`DramaForge总开发文档.md`](DramaForge总开发文档.md)；
3. [`docs/plans/professional-program-v2/README.md`](docs/plans/professional-program-v2/README.md)；
4. 当前 Task Contract 与其规定的七方案原文；
5. 当前代码、迁移、测试、运行时和可验证证据。

## 不可破坏的实现边界

- Scene / Shot / Canvas / Asset / Experiment 是创作事实；Agent 只能产生 typed proposal，不能直接修改正式事实或直接调用 Provider；
- ProductionGraph / NodeRun / ProviderOperation / Artifact 是执行事实；不得新建平行 Generation、AIJob、Runtime 或成本真相；
- ModelManifest 是模型能力事实；ProductionModelProfile 只表达偏好；Professional 真实媒体执行必须消费冻结的 `ExecutionModelResolution`；
- 选择 X 不得静默运行 Y；不支持或未声明的 input slot 必须 fail-closed，且不得产生 Provider 请求；
- Connection、Credential、Catalog、Binding、Manifest、mode 和 references 的执行身份必须可追溯、可恢复且不会被后续配置改写；
- 不伪造 Provider、质量、成本、用户或发布证据；未经 Owner 单次明确授权，禁止付费 Provider 调用。

旧总纲、旧 `docs/current/`、旧 P0 规划与历史 Gate Board 只保留在 Git 历史或历史材料中，不能作为开发依据。
