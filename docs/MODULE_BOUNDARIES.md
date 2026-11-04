# MODULE_BOUNDARIES — 模块边界与依赖方向

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Updated: 2026-10-07；迁移状态统一见 [DATA_MODEL.md](DATA_MODEL.md)。

本文件只回答一件事：**哪一层可以依赖哪一层。**

世界观见 [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md)；术语见
[DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md)；当前代码的实际违规清单见
[ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md)。

---

## 一、层定义

先区分职责，不能用“frontend”同时指浏览器和服务端入站层：

| 职责 | 边界 |
|---|---|
| Frontend UI | 浏览器视图与草稿；只能经统一 API Client 访问后端，不直连 Provider/Worker |
| Backend API | HTTP 入站适配；鉴权、输入校验、命令/查询转发，不复制领域规则 |
| Backend Worker | 异步入站适配；消费任务并调用领域服务和 Runtime，不另建业务生命周期 |
| Application | 用例编排、权限与业务操作入口；导演/生产写入经对应 Command，账号/连接/资产管理经对应领域服务 |
| Domain | 领域事实和业务规则，不依赖浏览器、HTTP 或队列入口 |

Application 是职责，不是“可依赖任意层”的新层。当前 `production/application` 仍归
production；其他应用编排与领域代码混在同包的差距归 ARCHITECTURE_MAPPING，不能仅
重分类目录或改名来放行既有越界。下表是后端 import 门使用的物理归属；浏览器不在
Python 扫描范围内，其调用边界另由 API/client 检查、行为测试和 Review 验证。

| 层 | 当前包 | 职责 |
|---|---|---|
| **backend_api** | `app/api/` | HTTP 入站适配，转发至应用入口 |
| **backend_worker** | `app/workers/` | 异步任务消费和 Runtime/领域服务调用入口 |
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
backend_api / backend_worker → 后端各层及入站适配（import 可见性；业务调用须遵守上述职责）
contract   → 仅 shared
director   → creative, domain, contract, shared
creative   → domain, shared
production → creative.contracts, provider, domain, contract, shared
provider   → domain, shared
domain     → shared          ← 初始化的 domain → creative 债务见
                               ARCHITECTURE_MAPPING.md §4 问题 6
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
provider      !→ backend_api / backend_worker
contract      !→ director
contract      !→ production
contract      !→ provider
domain        !→ director
domain        !→ creative
provider adapter !→ application service
director      !→ provider adapter（见 §四.3 的受限例外）
Frontend UI   !→ Provider / Worker（浏览器不得直接调用）
director      !→ 直接调用媒体 Provider
```

两条不可让步的推论：

- **Production 不允许通过 Director 才能访问 Creative Layer。**
- **Creative Layer 不允许知道具体 Runtime 的存在。**

---

## 四、判定规则（可执行）

以下规则用于 Review 与静态检查；静态门只证明其覆盖的 import 方向，不证明调用职责。

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
  见 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) §4 问题 3。

### 4.4 Production 不得依赖 Director 业务

- `app/production/**`、`app/execution/**`、`app/runtime/**`、`app/workbench/**`
  不得 import `app.director.assistant_models`、`app.director.proposal_models`、
  `app.director.turn_service` 等 Director 业务模块。
- 允许 `production → creative.contracts`：Production 可以消费 Creative 的**契约**
  （如引用意图、参与计划），但不得消费 Director Runtime 的会话/提案状态。
- 该方向的现存越界见映射文档 §4 问题 2；具体边以 `arch_import_scan.py --violations` 为准。

### 4.5 Contract 层必须保持中立

- `app/contracts/**` 不得 import `app.production.*` 等实现包。
- 被契约引用的模型**必须定义在契约层内**，由实现层反向 import。
- `ShotReferenceIntent` 已归 `app/contracts/shot_reference.py`；生产编译器旧导入路径仅重新导出同一类型，不再由 contract 依赖 production。

### 4.6 前端只有一个入口族

- 前端不得直接访问 Provider。
- 前端不得直连随机 worker。
- 导演/生产写入最终进入对应 **Director Command** / **Production Command**；
  账号、连接和资产管理写入进入对应领域的应用服务，保留权限与事务校验。
- 前端调用必须经由 `frontend/src/lib/api.ts` 的统一客户端（含 CSRF、
  workspace header、错误解析），不得散落裸 `fetch`。
- 统一客户端只接受后端相对路径，后端 origin 由配置决定；SSE 创建与凭据也归客户端，
  组件保留订阅/卸载生命周期。现有 ESLint 门限制客户端之外的网络全局和明确的
  window/globalThis/self 网络成员；行为测试验证外部路径在请求前被拒绝。
  这不证明任意动态属性、全局对象再别名或第三方 SDK 的间接 I/O，相关新增调用仍须 Review。

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

**执行纪律：** 先锁定依赖与概念，再逐步迁移。上述是目标布局参考，不授权新增
facade / compatibility import；当前未发布策略要求直接更新调用方并删除被替换实现，
不保留过渡别名。不要一次移动大量活跃文件。

---

## 六、边界如何被强制

| 机制 | 位置 |
|---|---|
| 退役表面禁止回归（源码扫描 + FORBIDDEN_FILES） | `scripts/check_canonical_surface.py` |
| 仓库目录与敏感文件规则 | `scripts/check_directory_compliance.py` |
| generated OpenAPI 一致性 | `scripts/check-generated-api.mjs` |
| 浏览器统一传输入口 | `frontend/eslint.config.js`（由 lint 执行）、`apiTransportBoundary.test.ts` 与 SSE 行为回归；DTO 权威门不替代此检查 |
| 容器质量门 | `docker-compose.quality.yml`、[DEVELOPMENT.md](DEVELOPMENT.md) |
| 增量依赖方向门禁 | `scripts/arch_import_scan.py --check`，由 backend 完整容器门执行；定向测试不等同此门 |

### 增量依赖门禁合同

- §二/§四 的允许方向是规则；不能通过放宽规则把现状宣告合规。
- `scripts/architecture-baseline.json` 逐条登记既有越界 module edge、原因和初始源码基线。
  新增越界边、已消失却未移除的豁免、无原因/重复豁免、解析失败均使 `--check` 失败。
- `--matrix` / `--violations` 保留信息性输出；增量门通过只表示债务未增加，
  不表示所有依赖已经符合目标架构。新增豁免必须作为显式架构决策审阅，不能自动重建基线来过门。
- 检查覆盖 backend 的绝对/相对 import、package re-export 与字符串字面量动态导入；
  不证明反射/计算式导入、前端 HTTP 路径或业务调用语义合规，这些仍由专门测试和 Review 验证。
