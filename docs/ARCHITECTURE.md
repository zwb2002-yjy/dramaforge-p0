# ARCHITECTURE — 架构与代码归属权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-14 / Base: dev 070faa3 / Alembic head: 20260910_0066

本文件描述**当前项目实际怎么组成**。它受架构宪法
[CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) 约束：宪法定义目标世界观，
本文件描述当前实现结构。两者不一致之处即
[ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) 中记录的差距，不得在本文档内
自行放宽。模块依赖的允许/禁止以 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) 为准。

## 系统拓扑

同仓库、同后端镜像、不同启动角色；Compose 服务：

| 服务 | 角色 |
|---|---|
| `api` | FastAPI 入站鉴权、业务命令与读取；不在 HTTP 请求中等待长推理 |
| `dispatcher` | 常驻事务性 Outbox 分发（区分导演工作唤醒与生产任务分发） |
| `worker-default` | Arq `dramaforge:default`：媒体、review、continuity 作业 |
| `worker-director` | Arq `dramaforge:director`：有界导演轮次、事件 intake、唤醒重放；禁用 Provider 调用 |
| `worker-heavy` | Arq `dramaforge:heavy`：重媒体作业 |
| `frontend` | Nginx 网关，唯一对外应用入口（宿主端口 8080） |
| `postgres` / `redis` / `minio` / `litellm` / `litellm-db` | 内部基础设施，不发布宿主端口（dev override 除外） |
| `migrate` / `database-bootstrap` | 迁移与角色初始化 |

两个 runtime：
- **Director Runtime**（编排，提案式，不拥有媒体）→ [DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)
- **Production Runtime**（统一媒体执行）→ [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)

只有这两个 Runtime；Graph / Node / NodeRun 的精确定义见
[PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)，术语唯一解见
[DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md)。

## 代码归属矩阵

| Domain | Source of truth | May own | Must not own |
|---|---|---|---|
| Access | backend/app/access | users, workspaces, projects, workspace state and creative profile | media execution or provider selection |
| Story/Assets | backend/app/assets | ScriptDocument, Episode, Scene, Shot, Asset, AssetVersion, version references, tags | provider calls |
| References | backend/app/production/reference_intents.py and api/v1/references.py | explicit binding, compilation, model capability gaps | name/prompt fallback |
| Workbench | backend/app/workbench and backend/app/production/workbench_execution.py | workspace state, frozen execution plan and NodeRun creation | direct Provider HTTP, budget gate |
| Production graph | backend/app/production | graph versions, branches, formal selection, repair plans, Final Film and timeline rendering | HTTP/API concerns, silent rerun |
| Runtime | backend/app/execution/product_path.py and voice_path.py | Worker execution, lineage, artifact persistence, shot locks | HTTP/API concerns, old branches |
| Director Assistant | backend/app/director/assistant_models.py, suggestion.py, proposal_* | suggestions, threads, typed proposal/apply boundary | media, budgets, workflow ownership |
| Director runtime | backend/app/director/runtime and backend/app/workers/director.py | turn/invocation identity, engine routing, checkpoints, wakeups, resume fencing | Canonical media writes or bypassing Apply/Save/Formal gates |
| Providers | backend/app/providers | manifests, compilers, runtime adapters, connection/credential revisions, model profiles | product stages or UI state |
| Review/Repair | backend/app/delivery and backend/app/production/repair_service.py | annotations, decisions, explicit repair plans | silent rerun or fallback |
| Editing | backend/app/editing, api/v1/editing.py, api/v1/opencut.py | EditSession timeline, suggestions and export | rewriting production truth |
| Events | backend/app/events and backend/app/workers/dispatcher.py | event log, outbox delivery, dead letters, SSE | product decisions |
| Security | backend/app/security | encrypted BYOK credentials and rotation audits | credential readback |
| Contracts | backend/app/contracts | shared typed runtime/production command and fact contracts | persistence or HTTP surface |
| Workers | backend/app/workers | Arq default/director/heavy entry points and recovery ticks | domain rules owned by other packages |
| Frontend | frontend/src/routes and frontend/src/features | views and explicit user commands | duplicated server truth |

## 依赖方向

UI → typed API client（OpenAPI 生成）→ domain service → canonical models/runtime。
Provider adapter 只能被 Workbench Worker 执行或其显式配置/探测边界触达。
所有源码提交必须通过容器质量门（[DEVELOPMENT.md](DEVELOPMENT.md)）和
generated OpenAPI 检查。

## 退役表面边界（已硬删除，禁止回归）

以下区域已从可执行产品中删除，由 `scripts/check_canonical_surface.py`
在质量门中强制（源码扫描 + FORBIDDEN_FILES 清单）：

- Quick 路由 / 模式 / mock / 导航及其测试；
- Creation Brief/Plan/Authorization/Materialize 包（backend/app/creation 已删除）；
- 固定十镜头 P0 路径与 fixture、旧假首帧管线；
- 受控导演 workflow（workflow、budget、approval、trial、batch、repair 旧服务/路由）；
- 直接 Shot action API（start/rerun/approve/reject/lock/manual-media）；
- Character/CharacterReference 兼容层——AssetVersionReference 是唯一身份引用源；
- runtime 分裂与迁移开关 flag（keyframe/video 恒走 unified-v1）；
- 迁移 20260902_0051 一次性完成上述表/列/枚举硬删除，不可逆。

canonical-surface 扫描、model-registry 测试、generated OpenAPI 检查、
PostgreSQL 迁移检查和容器质量门共同强制该边界。

## 运行时端口契约

对外唯一应用入口是 8080（非特权 Nginx 网关）；API 8000 端口只在 Compose
网络内部使用。发布拓扑没有 `build` 字段：普通用户消费版本化镜像，不在安装机
编译。
