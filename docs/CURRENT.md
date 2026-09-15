# CURRENT — DramaForge 唯一文档入口

本文件是仓库的当前状态入口。新开发者、Codex、Claude 或任何 Agent 从这里开始；
不要从历史设计稿、Task Contract、Review 或执行记录开始。

## 当前产品是什么

DramaForge 是面向专业个人创作者的开源 AI 短剧 / 漫剧导演工作台。
首要目标是完成真实生产闭环：

> 故事 / 剧本 → 资产 → Scene / Shot → 关键帧 → 视频生成 → Review / Repair
> → 剪辑 → Final Film（MP4 + SRT）

首版聚焦一部 15–30 秒、真人写实风格、角色对白驱动的多镜头短剧：生成前确认
创作与拍摄方案，用代表镜头试拍降低盲抽成本，失败后提供有证据和成本范围的
局部修复，并保留完整产物血缘。

## 当前核心架构（概念）

```text
用户
  ↓
Director Runtime（提案式导演编排，不拥有媒体）
  ↓
Proposal / User Decision（Apply / Save / Formal / Export 显式用户门）
  ↓
WorkbenchExecutionPlan → Production Runtime（统一生产执行）
  ↓
Provider（ModelManifest 冻结身份，无静默回退）
  ↓
Artifact（不可变产物与血缘）
  ↓
Review / Repair → Editing → Final Film
```

本文件不重新设计这些模块；概念细节见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 当前权威文档

| 领域 | 文档 |
|---|---|
| 产品 | [PRODUCT.md](PRODUCT.md) |
| 架构与代码归属 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 创作主链 | [CREATION_FLOW.md](CREATION_FLOW.md) |
| Director Runtime | [DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md) |
| Production Runtime | [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md) |
| 模型与 Provider | [MODEL_PROVIDER.md](MODEL_PROVIDER.md) |
| 数据模型 | [DATA_MODEL.md](DATA_MODEL.md) |
| API 表面 | [API.md](API.md) |
| 前端工作台 | [FRONTEND_WORKBENCH.md](FRONTEND_WORKBENCH.md) |
| V1 当前状态 | [V1_STATUS.md](V1_STATUS.md) |
| 开发与测试 | [DEVELOPMENT.md](DEVELOPMENT.md) |
| 部署 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| 发布与分支保护 | [RELEASE.md](RELEASE.md) |
| 历史技术决策 | [adr/](adr/)（ADR，仅记录已做出的决策） |

代码、迁移、测试和运行证据说明"现在实际是什么"；以上文档与之冲突时以代码为
准，并同步更新文档。

## 历史文档规则

任何已删除或只存在于 Git 历史中的旧设计、历史 Task Contract、Review、
Execution Record、旧检查点和旧 Release Board，不得作为当前实现依据；
它们只能通过 `git log` / `git show` 追溯。当前实现依据只有：本目录权威文档、
代码、迁移、测试和运行证据。

## 仓库布局

```text
backend/    FastAPI、领域服务、Arq workers、Alembic 迁移（见 backend/README.md）
frontend/   React 18 + TS + Vite 工作台（骨架约定见 frontend/design/README.md）
infra/      LiteLLM、Nginx、Prometheus、Grafana 配置
scripts/    CI/部署/验收仍在使用的脚本
fixtures/   测试与证明脚本引用的固定输入
deploy/     AIOS 交接描述
.github/    CI / Release / Security 工作流
```
