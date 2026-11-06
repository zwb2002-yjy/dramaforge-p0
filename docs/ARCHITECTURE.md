# ARCHITECTURE — 架构与代码归属权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Updated: 2026-10-07；迁移状态统一见 [DATA_MODEL.md](DATA_MODEL.md)。

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
| `worker-director` | Arq `dramaforge:director`：有界导演轮次、事件 intake、唤醒重放；禁止媒体 Provider 执行，文本推理遵循 MODULE_BOUNDARIES §4.3 |
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
| References | backend/app/contracts/shot_reference.py, production/reference_intents.py and api/v1/references.py | shared intent, explicit binding, compilation, model capability gaps | name/prompt fallback |
| Workbench | backend/app/workbench and backend/app/production/workbench_execution.py | workspace state, frozen execution plan and NodeRun creation | direct Provider HTTP, budget gate |
| Production graph | backend/app/production | graph versions, branches, formal selection, repair plans, Final Film and timeline rendering | HTTP/API concerns, silent rerun |
| Runtime | backend/app/execution (module responsibilities in PRODUCTION_RUNTIME.md) | Worker execution, lineage, artifact persistence, shot locks | HTTP/API concerns, old branches |
| Director Assistant | backend/app/director/assistant_models.py, suggestion.py, proposal_* | suggestions, threads, typed proposal/apply boundary | media, budgets, workflow ownership |
| Director runtime | backend/app/director/runtime and backend/app/workers/director.py | turn/invocation identity, engine routing, checkpoints, wakeups, resume fencing | Canonical media writes or bypassing Apply/Save/Formal gates |
| Providers | backend/app/providers | file-backed catalog, manifests/input contracts, compilers, runtime adapters, connection/credential revisions, availability and model profiles | product stages or UI state |
| Review/Repair | backend/app/delivery and backend/app/production/repair_service.py | annotations, decisions, explicit repair plans | silent rerun or fallback |
| Editing | backend/app/editing, api/v1/editing.py, api/v1/opencut.py | EditSession timeline, suggestions and export | rewriting production truth |
| Events | backend/app/events and backend/app/workers/dispatcher.py | event log, outbox delivery, dead letters, SSE | product decisions |
| Security | backend/app/security | encrypted BYOK credentials and rotation audits | credential readback |
| Contracts | backend/app/contracts | shared typed runtime/production command and fact contracts | persistence or HTTP surface |
| Workers | backend/app/workers | Arq default/director/heavy entry points and recovery ticks | domain rules owned by other packages |
| Frontend | frontend/src/routes and frontend/src/features | views and explicit user commands | duplicated server truth |

## 入站调用职责

Frontend UI → 统一 API Client（DTO 来自 OpenAPI）→ Backend API → Application → Domain / Runtime。
该关系表示职责分工，不是源码 import 矩阵或每个请求都必须穿过的全部层；模块依赖只由
MODULE_BOUNDARIES 定义，不能据此为每个操作增加 Command、接口或转发包装。
Backend API 负责 HTTP 鉴权、输入校验与命令/查询转发；Backend Worker 负责异步消费并调用
相应应用服务和 Runtime。Application 承载用例编排、业务操作权限及事务入口；Domain
维护领域事实和规则。Application 是职责，不是新的 Runtime，也不是允许跨层绕过的理由。
现有 Python 扫描分别标记 `backend_api` / `backend_worker`；浏览器 UI 不属于这两个标签。
`production/application` 仍遵守 production 依赖方向；混合包中的应用服务不能靠改名免除债务。
媒体 Provider adapter 由生产 Worker 执行；文本推理、连接管理与只读查询按各自合同
触达对应适配器。生成探测没有独立当前授权合同则不可用，不能由“探测边界”推导付费许可。
验证按改动影响执行，发布候选必须通过完整容器质量门；API 变更同时检查 generated
OpenAPI。`dev` 快速开发与 `main` 的强制门边界见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 核心框架与基础设施的职责

这些组件按真实生命周期与消费者保留；名称相近或体积大不是替换依据。

| 组件 | 当前消费者和独立职责 | 替换/合并必须证明 |
|---|---|---|
| LangGraph | `director/runtime/langgraph_adapter.py` 的 StateGraph、中断、恢复；执行器只构造该引擎 | 中断、恢复与执行身份合同；替换须 Owner 架构决策，不得引入第二 Agent Runtime |
| SQLAlchemy/asyncpg 与 psycopg checkpoint | 应用事务/RLS 与 `director/runtime/checkpoint.py` 的 AsyncPostgresSaver 分别消费 | ORM 与 checkpoint 协议、schema 权限及恢复同时兼容，不能按“两套PG驱动”删一套 |
| Arq/Redis/Outbox | `runtime/scheduler.py` commit 后投递，Workers 执行；Redis Streams 传递事件 | 队列隔离、幂等、延迟恢复、SSE 与事务投递，不能把投递器当第三业务 Runtime |
| LiteLLM Proxy、HTTP client、policy/network guard | `providers/litellm_gateway/client.py`、`infra/litellm/` 分别控制调用、请求策略与出网；独立 DB 保存代理部署状态 | 精确部署身份、重试/重定向、未知提交与网络隔离；Proxy DB 不是第二份 ProductionGraph |
| MinIO/ObjectStore | `storage/minio_store.py` 的对象、Range、presign、流读取 | 持久化、租户隔离、授权引用、备份恢复与多进程一致性；内存实现只作测试/显式模式 |
| FFmpeg/ffprobe | `execution/composite_media.py` 复合镜头；`production/timeline_renderer.py` 消费时间线 | 输入语义、取消、临时资源与媒体等价性；不同产品职责不强行合并 |
| Pillow/OpenCV/NumPy | 图像解析；`consistency/video_drift.py` 采样和评估；OpenCV 依赖 NumPy | 解码、采样、评分与资源行为等价；没有直接 NumPy import 不等于可删除运行依赖 |
| edge-tts/espeak-ng/silence | `voice_runtime.py` 根据冻结 engine/version 显式选择 | 历史计划身份和恢复、无对白语义；不能静默 fallback |
| React/TanStack Query/Router/Ant Design | 视图、服务端缓存、导航和组件分别有活跃消费者 | 草稿、缓存失效、导航、表单行为；不为依赖精简重写工作台 |
| TypeScript/native TypeScript | native 用于 typecheck；当前 ESLint/codegen 工具链仍消费 TS 5.9 | peer 范围与工具链 API 兼容后再移除；并列工具职责不等于两套产品实现 |

ProviderRuntime 是 I/O 协议适配，不拥有生产生命周期；ModelRegistry、BindingResolver、
ExecutionModelResolver、RuntimeResolver 分别做目录索引、逻辑选择、身份冻结和执行构造，
不得仅按 Resolver/Adapter 名称合并。Director Inbox/Wakeup 接收业务事件，Runtime checkpoint
记录引擎位置；实际重复与恢复正确性须由行为/PG 测试证明，静态审计不构成全面无重复证明。

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
