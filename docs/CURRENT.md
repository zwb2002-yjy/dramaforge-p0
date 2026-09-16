# CURRENT — DramaForge 唯一文档入口

本文件是仓库当前文档入口。代码、迁移、测试和运行结果是“现在实际是什么”的最终事实；
文档用于说明产品边界、架构约束和操作方式。历史方案、阶段审计、Task Contract、Review、
Golden/验收流水和一次性执行记录不留在当前树中，只通过 Git 历史追溯。

## 当前产品

DramaForge 是面向专业个人创作者的 AI 短剧 / 漫剧导演工作台。首版主链为：

```text
故事 / 剧本 → 资产 → Scene / Shot → 关键帧 → 视频生成
→ Review / Repair → Editing → Final Film（MP4 + SRT）
```

Director Runtime 负责提案和编排；Production Runtime 负责真实生产执行。
用户通过显式 Apply / Save / Formal / Export 门决定哪些内容进入正式生产事实。

## 当前权威文档

| 领域 | 文档 |
|---|---|
| 架构宪法 | [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) |
| 当前架构 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 当前代码到目标架构映射 | [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) |
| 术语 | [DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md) |
| 模块边界 | [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) |
| 产品 | [PRODUCT.md](PRODUCT.md) |
| 创作主链 | [CREATION_FLOW.md](CREATION_FLOW.md) |
| Production Graph | [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md) |
| Director Runtime | [DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md) |
| Production Runtime | [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md) |
| 模型与 Provider | [MODEL_PROVIDER.md](MODEL_PROVIDER.md) |
| 数据模型 | [DATA_MODEL.md](DATA_MODEL.md) |
| API | [API.md](API.md) |
| 前端工作台 | [FRONTEND_WORKBENCH.md](FRONTEND_WORKBENCH.md) |
| 当前 V1 / 发布状态 | [V1_STATUS.md](V1_STATUS.md) |
| 开发与测试 | [DEVELOPMENT.md](DEVELOPMENT.md) |
| 部署 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| 发布 | [RELEASE.md](RELEASE.md) |
| 已做出的技术决策 | [adr/](adr/) |

文档发生冲突时，以代码、迁移、自动化测试和实际运行结果为当前事实；
目标架构冲突记录在 `ARCHITECTURE_MAPPING.md`，不要重新引入第二套方案文档。

## 历史资料规则

以下内容不属于当前树的长期文档：

- 已完成或已被替代的开发/发布方案；
- 某个 SHA 的能力矩阵、闭环审计和阶段 Review；
- 真实 Provider / 付费测试的逐次调用说明、临时预算说明和 Golden 流水；
- DEV/REL 的一次性执行记录、截图清单、临时 evidence 清单；
- 已完成的 Task Contract 和旧 Release Board。

需要追溯时使用 `git log` / `git show`。正式可重复验证逻辑保留在测试、CI 和
`scripts/` 中；临时运行证据写入被忽略的 `tmp/`，不提交仓库。

## 仓库布局

```text
backend/    FastAPI、领域服务、Workers、Alembic、测试
frontend/   React/TypeScript 工作台与前端测试
infra/      LiteLLM、Nginx 等运行配置
scripts/    CI、发布、可重复验收与维护脚本
fixtures/   自动化测试和验收固定输入
deploy/     部署交接描述
.github/    CI / Release / Security
```

编码 Agent 先读根目录 [AGENTS.md](../AGENTS.md)（从仓库根打开时为 `AGENTS.md`），
再从本文件定位对应领域文档。
