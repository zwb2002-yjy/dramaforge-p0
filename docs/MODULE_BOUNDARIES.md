# MODULE_BOUNDARIES — 模块边界与依赖方向

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-15 / Base: dev 5ea45d6 / Alembic head: 20260910_0066

本文件只回答一件事：**哪一层可以依赖哪一层。**

世界观见 [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md)；术语见
[DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md)；当前代码的实际违规清单见
[ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md)。

---

## 一、层定义

| 层 | 当前包 | 职责 |
|---|---|---|
| **frontend** | `app/api/`、`app/workers/`、`frontend/src/` | 入站 HTTP、Worker 入口、UI。只做输入校验与命令转发 |
| **contract** | `app/contracts/` | 共享的**类型化契约**：命令、事实、事件、Director Runtime 契约。不含持久化、不含 HTTP |
| **director** | `app/director/`（不含 `creative_capabilities`） | 提案式编排：理解、推理、建议、等待、恢复、委派 |
| **creative** | `app/director/creative_capabilities/` | Style / Skill / Pack / VisualBible / ShotLanguage / Resolver / Compiler。**无生命周期** |
| **production** | `app/production/`、`app/execution/`、`app/runtime/`、`app/workbench/` | 可靠执行已确定的生产意图：Graph、NodeRun、Outbox、重试、恢复 |
| **provider** | `app/providers/` | 外部模型能力：manifest、compiler、runtime adapter、连接与凭据 |
| **domain** | `app/access/`、`app/assets/`、`app/consistency/`、`app/delivery/`、`app/editing/` | 产品实体与业务事实 |
| **shared** | `app/shared/`、`app/events/`、`app/security/`、`app/storage/` | 基础设施原语，被所有层依赖 |

---

## 二、允许的依赖方向

```text
frontend   → 任意层（只经由 typed API client / Application Command）
contract   → 仅 shared
director   → creative, domain, contract, shared
creative   → domain, shared
production → creative.contracts, provider, domain, contract, shared
provider   → domain, shared
domain     → shared          ← 注意：当前存在 1 条 domain → creative，见 §三 与
                               ARCHITECTURE_MAPPING.md 附加发现（待 Owner 决定）
shared     → 无内部层依赖     ← 注意：当前 shared/rls_scopes 与 model_registry 依赖域模型，见
                               ARCHITECTURE_MAPPING.md §4
```

**规则与现状不一致时，以 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) 记录
的差距为准**；不得为了让现状"合规"而放宽本节，也不得在未修代码的情况下声称已合规。

## 三、禁止的依赖方向

```text
creative      !→ director
creative      !→ production
creative      !→ provider
provider      !→ director
provider      !→ production
provider      !→ frontend
contract      !→ director
contract      !→ production
contract      !→ provider
domain        !→ director
domain        !→ creative
provider adapter !→ application service
director      !→ provider adapter（见 §四.3 的受限例外）
frontend      !→ provider
frontend      !→ worker（随机 worker 直连）
director      !→ 直接调用媒体 Provider
```

两条不可让步的推论：

- **Production 不允许通过 Director 才能访问 Creative Layer。**
- **Creative Layer 不允许知道具体 Runtime 的存在。**

---

## 四、判定规则（可执行）

以下规则可直接用于 Review 与静态检查（Phase 7 的依赖 Gate 即实现这些规则）。

### 4.1 Creative 必须可独立加载

- `app/director/creative_capabilities/**` 的 import 不得出现
  `app.director.runtime`、`app.director.workflows`、`app.execution`、
  `app.production`、`app.providers`、`app.workers`。
- 允许的 outbound：`app.assets.*`（domain）、`app.shared.errors`。

### 4.2 Provider 不得含创作决策

- `app/providers/**` 不得 import `app.director.*`、`app.production.*`、
  `app.workbench.*`、`app.api.*`。
- Provider 不得出现 Style / Skill / VisualBible / ShotLanguage 的选择或解释逻辑。
- Provider 只消费已经确定的请求；把创作意图翻译成请求是 Creative/Production 的职责。

### 4.3 Director 访问 Provider 的唯一合法形态

Director 需要文本 LLM 才能工作，因此存在受限例外：

- **允许**：Director 经由 `app/contracts/` 声明的端口/契约访问文本推理能力。
- **禁止**：Director 直接调用媒体 Provider；Director 逻辑内写死 Provider 参数。
- 现状 `director/text_transport.py` 直接 import `providers.registry` /
  `providers.model_profiles.*` / `providers.contracts.*`，属**待收敛例外**，
  见 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) 问题 3。

### 4.4 Production 不得依赖 Director 业务

- `app/production/**`、`app/execution/**`、`app/runtime/**`、`app/workbench/**`
  不得 import `app.director.assistant_models`、`app.director.proposal_models`、
  `app.director.turn_service` 等 Director 业务模块。
- 允许 `production → creative.contracts`：Production 可以消费 Creative 的**契约**
  （如引用意图、参与计划），但不得消费 Director Runtime 的会话/提案状态。
- 现状有 4 条越界边，见映射文档问题 2。

### 4.5 Contract 层必须保持中立

- `app/contracts/**` 不得 import `app.production.*` 等实现包。
- 被契约引用的模型**必须定义在契约层内**，由实现层反向 import。
- `ShotReferenceIntent` 已归 `app/contracts/shot_reference.py`；生产编译器旧导入路径仅重新导出同一类型，不再由 contract 依赖 production。

### 4.6 前端只有一个入口族

- 前端不得直接访问 Provider。
- 前端不得直连随机 worker。
- 前端所有写操作最终只能进入 **Director Command** 或 **Production Command**
  两类入口。
- 前端调用必须经由 `frontend/src/lib/api.ts` 的统一客户端（含 CSRF、
  workspace header、错误解析），不得散落裸 `fetch`。

---

## 五、目标物理布局（Phase 2+ 参考，本轮未执行）

```text
backend/app/

director/
  runtime/
  context/
  application/

creative/
  contracts/
  skills/
  styles/
  packs/
  visual_bible/
  shot_language/
  resolver/
  compiler/

production/
  runtime/
  graph/
  commands/

providers/
  adapters/
  capabilities/

domain/
  project/
  story/
  scene/
  shot/
  asset/
  editing/

api/
workers/
```

**执行纪律：** 先锁定依赖与概念，再逐步迁移；第一轮允许保留旧路径，通过
facade / compatibility import 过渡；**不要一次移动大量文件**。

---

## 六、边界如何被强制

| 机制 | 位置 |
|---|---|
| 退役表面禁止回归（源码扫描 + FORBIDDEN_FILES） | `scripts/check_canonical_surface.py` |
| 仓库目录与敏感文件规则 | `scripts/check_directory_compliance.py` |
| generated OpenAPI 一致性 | `scripts/check-generated-api.mjs` |
| 容器质量门 | `docker-compose.quality.yml`、[DEVELOPMENT.md](DEVELOPMENT.md) |
| 增量依赖方向门禁 | `scripts/arch_import_scan.py --check`，由 backend full/fast 容器门执行 |

### 增量依赖门禁合同

- §二/§四 的允许方向是规则；不能通过放宽规则把现状宣告合规。
- `scripts/architecture-baseline.json` 逐条登记既有越界 module edge、原因和初始源码基线。
  新增越界边、已消失却未移除的豁免、无原因/重复豁免、解析失败均使 `--check` 失败。
- `--matrix` / `--violations` 保留信息性输出；增量门通过只表示债务未增加，
  不表示所有依赖已经符合目标架构。新增豁免必须作为显式架构决策审阅，不能自动重建基线来过门。
- 检查覆盖 backend 的绝对/相对 import、package re-export 与字符串字面量动态导入；
  不证明反射/计算式导入、前端 HTTP 路径或业务调用语义合规，这些仍由专门测试和 Review 验证。
