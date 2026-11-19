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
| Maintenance | backend/app/maintenance/recovery_service.py | Owner-scoped recovery of an existing failure through normal scheduling | new paid create, direct Provider calls, a third Runtime |
| Composition / bootstrap | backend/app/main.py / backend/app/install_env.py | application assembly and installation configuration respectively | business use cases or reverse dependencies from application modules |
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
| 语音模型HTTP协议（OpenAI/MiniMax/Volcengine） | `providers/speech_http.py` 构造请求并解码WAV；`providers/speech_runtime.py` 按冻结binding一次调用；`voice_runtime.py` 只选silence或voice_model | 历史冻结engine只读、缺模型不兜底、一次调用不重试、未知提交不重发 |
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

## 机构版总体架构目标（D3，未实施）

继续使用当前FastAPI、React、PostgreSQL、Redis、对象存储、内部LiteLLM和容器拓扑。
Owner N03要求保持本地现有部署方式；不新增Agent集群、消息基础设施、搜索/向量服务或第二执行Runtime。
以下为目标，不能由图推断当前源码已接线。

~~~mermaid
flowchart TD
  Browser["浏览器机构工作台"] --> API["FastAPI 鉴权与命令入口"]
  API --> Domains["项目 / 私有资料 / 研究 / 知识 / 资产领域"]
  API --> Gate["显式用户决定与原生产授权"]
  API --> Turns["Turn / Wakeup 接纳"]
  Turns --> Director["同一 Director Runtime / LangGraph / Harness"]
  Director --> Run["MasterRun 目标与计划 / BusinessFlow 步骤"]
  Director --> Ports["受限中立工具端口"]
  Ports --> Domains
  Ports --> Admission["入站装配：短事务资格与原命令受理"]
  Gate --> Admission
  Admission --> Production["唯一 Production Runtime"]
  Production --> Chain["NodeRun / ProviderOperation / Artifact"]
  Director --> Text["原 Invocation 文本调用"]
  Text --> Egress["模型身份 / 项目外发 / 来源限制"]
  Production --> Egress
  Egress --> External["既有 LiteLLM / Provider Adapter"]
  Chain --> Review["Review / Formal"]
  Review --> Editing["Editing / Save / Export"]
~~~

共享PostgreSQL里各域拥有自己的表与写入口，私有checkpoint schema继续单独角色。
知识/公共发布按同owner跨Workspace共享；源私有表仍项目RLS。图中的Domains不是新的单一超级模块，
业务所有权和具体数据分别见MODULE_BOUNDARIES与DATA_MODEL。
Dispatcher/Arq是现有异步适配；Flow定义/Skills不各自创建Worker或根checkpoint。
SSE/Redis通知可以丢失，已提交业务事实与原回执是恢复依据。队列完成不代表目标完成。

变化清单：REUSE现有生产/用户门/模型身份/部署；EXTEND项目/资料/领域服务/界面；
NEW持续目标/业务流程/研究与知识/公共发布/外发数据合同；
REFACTOR统一控制、无锁网络、原子受理与跨域引用授权；
REMOVE仅被替代当前写路径/同义DTO，旧lease按O6另评估；VERIFY全部运行、RLS、格式与真实作品。
不因本目标图自动调整整个物理目录或清理旧数据；实现前按对应合同核对全部消费者。

<a id="institution-research"></a>
## 项目资料、文化研究与知识架构（D4设计审查通过，未实施）

范围R02–R11/R24/R29/R32，遵守O7：先完成控制与外发基础，再接入真实资料；设计、合成样例可先推进。
I4-01已实施本地全格式处理器（`app/assets/source_processors/`，由`source_parser`门面调度）：
TXT/CSV/TSV（stdlib）、DOCX（正文/表格/脚注/尾注/页眉/页脚）、PDF（Poppler文本层＋扫描页本地OCR，
25页/块）、XLSX（openpyxl只读、sheet/行列/合并格、公式与缓存区分）、图片（Pillow方向与像素上限＋
Tesseract中文OCR）、音频/视频（FFmpeg探测/解码＋whisper.cpp 30秒窗口转写、视频取样帧OCR）。
每条片段记录`extraction_method`与真实`processor_ref`；PDF按块写项目私有中间回执并可续做；
`GET /projects/{p}/source-capabilities`返回实际组件可用性与`profile_revision`。当前上传上限仍是16 MiB，
字符/片段上限2,000,000/50,000，音视频当前处理档10分钟（30秒窗口，目标60分钟待块级ASR回执）；这些是当前事实。
仍属待实施目标：reparse/事件schema2受理回执、研究分析与知识（I4-02/03）、流式上传放大处理档与媒体块回执；
不用支持列表冒充已验收能力。

### 处理链与状态拥有者

原件接收/版本/去重 → 固定研究操作计划 → 本地探测/有界解析 → SourceExtraction/Fragment
→ 受控语义分析Invocation → ResearchAnalysis覆盖清单与ResultRevision/Citation
→ 用户直接修正/恢复或采纳差异 → 按权限维护项目上下文。
独立知识录入/发布是单独用户动作，不从上传或AI结果自动推断；按N05跨同用户Workspace检索已发布版本。
三类存储分开：原件对象、机器解析/调用证据、当前有效研究/公开知识，不能用一个状态标“全部成功”。

文件状态归既有Revision及其attempt；跨步骤等待/重试归BusinessFlow/Turn，不新增Research Runtime。
图步骤本地解析属于有界内部处理，不暗藏云模型；语义模型调用必须走TextInference/原Invocation，
逐调用记身份/准入/使用次数，不能在read工具内部再发一个未记录LLM。
用户修正立即有效，解析原文/机器转写不被修正覆盖；来源历史和当时模型输出继续可回溯。

### 全格式处理合同

| 格式 | 解析路径与来源位置 | 必须覆盖的失败/质量边界 |
|---|---|---|
| TXT | 复用解码；UTF-8/BOM/UTF-16，保留空行对原坐标影响；行作为paragraph定位 | 不猜GBK为UTF8；未知编码让用户选择可支持编码或明确失败；NUL/二进制拒绝 |
| DOCX | 复用有界ZIP/XML读取，扩正文段落/表格及受支持脚注/尾注/页眉页脚；part+container+段/格坐标 | 不执行宏、不解压用户路径、不跟外部relationship；内容控件/修订/嵌入对象未处理要列覆盖缺口，不能悄悄丢正文 |
| PDF | Poppler原生文本及页/块bbox优先；空白/扫描/损坏字体页面单独栅格化后本地OCR | 加密/权限限制明确拒绝，不使用owner-password绕限制；文本/扫描混合逐页判断；无法可靠定位只声明整页 |
| 图片 | Pillow验证解码与方向；本地OCR输出区域；必要的图像语义由明确授权Vision调用生成研究解释 | PNG/JPEG/WebP/TIFF为核心验证集；多页/多帧全部列覆盖；图片没有文字不等于无文化信息，不能伪造OCR |
| 音频 | FFmpeg探测/转16kHz单声道PCM；本地whisper.cpp按时间窗转写，保留原时间轴 | WAV/MP3/FLAC/OGG核心集；静音/音乐/噪声区不编对白；方言/专名标待核实，时间码不是完美逐字对齐保证 |
| 视频 | FFprobe时间基准；音轨走ASR，关键时间窗帧采样走OCR/受控Vision，组合来源而不改原视频 | MP4/MOV/MKV核心集；缺音轨可做画面分析并显示；采样不是逐帧全量理解，coverage明确实际帧/时间窗 |
| 表格 | CSV/TSV保留多行单元格；XLSX用openpyxl只读模式，记录sheet/行列/合并单元格来源 | 不计算公式/执行宏/打开外部链接；公式与缓存值区分，未知缓存不能当当前真值；异常dimension不静默漏单元格 |

上述每个格式必须有真实解析正负测试才能开启“可用”。旧DOC/XLS、损坏文件或未支持编码明确拒绝，
不因它们可保存原件就冒称分析可用。常见格式仍全部在首期验收，不以暂时禁用绕过最终交付。

### 依赖选择与核验依据

复用现有Pillow/OpenCV/FFmpeg；不更换后端Python或Bookworm基础镜像。
PDF选择容器内poppler-utils，其pdftotext支持块/行/词边界输出；编码损坏的PDF仍需OCR，
因此不会把native text作为所有PDF的唯一成功路径。[Debian命令合同](https://manpages.debian.org/bookworm/poppler-utils/pdftotext.1.en.html)

OCR选择Tesseract命令行，TSV提供位置和置信度；中文语言包随容器交付，语言选择属于解析配置，
不把OCR置信度转换为史实正确分数。[Tesseract输出合同](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
[Bookworm中文数据包](https://packages.debian.org/bookworm/tesseract-ocr-chi-sim)

本地ASR选择whisper.cpp CPU路径，中文用多语言base而不是base.en；目标固定v1.9.5，
本次只读ls-remote核验tag解引用commit为d1be6fde11ac6e0407606b4e42fe72d34add8037。
无GPU前提，不承诺方言识别率或实时速度；词级时间戳不作为精确证据保证。
[官方版本](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5)
[官方CLI](https://github.com/ggml-org/whisper.cpp/blob/master/examples/cli/README.md)

D8补齐权重身份：上游ggerganov/whisper.cpp固定提交`5359861c739e955e79d9a303bcbc70fb988958b1`的
ggml-base.bin，147951465字节，LFS SHA-256
`60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe`。
依据[上游固定提交元数据](https://huggingface.co/api/models/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1)，
仅读API元数据，未下载权重；未来构建须核对实际文件字节/hash和许可证，不把expected hash写成已测processor证据。

XLSX选择openpyxl 3.1.5及defusedxml，read_only迭代且关闭工作簿；校验实际内容范围，
不能仅信文件声明dimension。库自身不保证防XML膨胀，故保留ZIP大小/实体限制。
[只读模式](https://openpyxl.readthedocs.io/en/stable/optimized.html)
[安全说明](https://openpyxl.readthedocs.io/en/stable/)
[3.1.5发行信息](https://pypi.org/project/openpyxl/)

新增依赖和ASR权重的hash/许可证清单/目标Python3.14构建验证在D7安装合同与I4镜像验收落实，
不声称已安装或已支持。本次没有下载权重、修改Dockerfile/lock、启动服务或发真实模型请求。
这些是容器内库/CLI适配器，不引入常驻ASR/OCR服务或新的基础设施Runtime；缺组件明确processor_unavailable，
不自动切云。D5统一Vision/可选云解析的实际模型能力和外发门。

### 有界资源、分批与原件保护

上传目标采用服务端流式接收、计算hash并写任务私有spool，不把512MiB视频读入一个Python bytes。
初始可调处理档：文档/表格64MiB，图片32MiB且解码不超过40MP，音视频512MiB/60分钟；
PDF最多500页，每轮最多处理25页；音频窗口30秒，边界重叠只用于对齐，合并时保留原时间偏移并去重。
单次输出最多2,000,000字符/50,000片段，ZIP总解压/单part/文件数/压缩比分别限额，
不能只检查上传压缩字节。数值是设计默认，目标机压测后按配置冻结，不是已证吞吐SLA。

每个本地处理块有超时/内存/输出大小/子进程数限制，默认重处理并发1；多文件公平轮转。
达到上限保存原件和明确未覆盖范围，分批续做或显示具体不支持原因，不截断后报完整。
上限由API能力查询返回并与网关/服务端一致，不能只改前端accept或MAX_SOURCE_BYTES。
存储接口需支持流式输入/读取；原件hash/对象键/已引用对象保护保持。网络重发相同请求不新增原件修订。

命令只用固定可执行文件和参数数组、服务器生成的临时文件名、净化环境；不执行文档内命令/URL，
FFmpeg仅允许本地file/pipe输入。解析器无数据库/Provider凭据，不读取任意本地路径。
所有XML拒绝外部实体，ZIP禁止路径穿越/重复part歧义/加密包；图片解压炸弹与媒体异常时长先探测。
阻断与超时只影响当前文件/块；退出清理仅本任务未被引用的临时资源，不删除原件或其他会话文件。

大文件块产物写项目私有中间对象，原Flow Attempt回执绑定hash/范围；不在半成品上创建“完整Extraction”。
全部要求块完成并校验attempt/源版本后，同事务建立不可变Extraction/Fragments及当前指针。
重启优先读取已有块回执；已丢失的纯本地中间结果可以同输入重算，外部Invocation未知提交不得重发。
未引用中间对象回收遵循DEVELOPMENT，不能把所有content-addressed对象当本次孤儿立刻删掉。

### 定位版本与引用保真

新SourceExtraction.schema_version=2，locator使用0-based、半开区间；旧native-text-v1的1-based值
显式转换后保存原locator与转换版本说明，旧历史原件/原报告不原地改写。
TXT line N→[N-1,N)；CSV/TSV row/column N→N-1并保留原line_start/end说明；
DOCX part/表格/单元格/段落分别转换，不将表格内段号误当正文段号。
UI显示为人类习惯的1-based页/行/格，但API标index_base=0，不能二次减一。

PDF bbox以固定页面坐标原点/旋转矩阵归一化；图片EXIF方向与视频旋转同样保存转换信息。
显示定位必须用同一变换后的预览，必要时可反算原始像素；不能声称模型猜出的区域是OCR定位。
机器转写标ASR来源、模型hash和时间窗，不把它称为原件内原生文字；Vision解释写ResearchResult，
SourceFragment只保存可定位输入/机器转写，不把创造性描述伪装逐字引文。
模型引用仅可选本次给出的fragment IDs和合法子范围；不存在/越界/别项目引用失败即待核实或拒绝整项。
缺可靠定位显示“整页/整图/该时间窗”，不得伪造精确行/秒。


### 六类语义分析、差异与恢复

每个模型请求冻结file revision、extraction、fragment集合、处理目的、模型/连接版本、
输出schema/hash、policy/source-use版本及上限。提示把资料作为不可信引用数据，不将其中“忽略规则/调用工具”
当成系统命令。模型只返回六类typed研究候选及本次允许的fragment IDs；服务端核对全部引用、kind、
日期精度、项目归属和范围后才能落库。未知人物同名不自动合并，无证据时间保持unknown。

每个类别必须明确findings/none/incomplete。没有人物、时间线或文化线索时允许none，
不能生成空壳人物通过验收；未完成页/时间窗必须incomplete。分析清单记录实际Invocation及输出修订，
不会把一次文本回答当全文件完成。图像Vision结果标interpretation/待核实，不把推测地点/年代写成确证事实。
OCR/ASR置信度只用于提醒复核，不能直接把ResearchResult.verification设为已核实。

研究结果的当前指针与分析清单分开：首次结果可生效；再分析只提供候选、明确关联旧result_id/base_revision，
新增发现先在候选列表。用户保存/accept/restore按D2 CAS追加不可变revision；响应丢失重放原受理版本，
之后current已经变化也不能伪装旧响应。并发409显示两份差异并保留用户输入；不用最后写覆盖用户修正。
用户修正可以说明引用不再支持某结论，旧引用保留历史，新有效修订只携带用户实际选定依据。
自动上下文更新只是可读依据变化，绝不改Story、Script、角色版本、Formal或时间线。

### 独立文化知识的发布、检索和撤回

用户可不建影视Project而录入KnowledgeEntry；直接录入标用户提供，不编造来源。
从项目研究发布时必须选定具体revision与内容，预览公开字段、用途与安全来源说明并显式确认。
内容快照、私有SourceLink、Entry指针/发布状态和事件原子提交；由当前owner跨全部Workspace访问已发布内容。
私人引用/原文下载仍需原project权限；公共来源说明不含私有ID/object_key/签名URL。
编辑公开条目创建新revision并明确发布；撤回不删历史、不自动修改已采用作品，阻断新引用并提示已有使用。

检索分两个明确入口：当前项目有效研究与同用户已发布知识。都先权限/状态/当前revision过滤，
再检索/排序/分页；不得先全库搜片段再靠浏览器隐藏越权结果。查询2–200字符，参数化并转义通配符；
精确名称/别名优先，随后正文包含/相似结果，稳定ID作为分页次序。单字使用受限名称匹配和筛选，
不能让无三元组的宽泛查询无限扫描。返回片段、匹配字段、确定revision、安全来源及限制，
不返回私有SourceLink内容；没有匹配明确为空，不由LLM补造“查到的知识”。

索引采用现有PostgreSQL内pg_trgm，知识/研究修订派生search_text，配合当前指针/RLS过滤；
不新建向量库或外部检索服务。短模式无法提取足够trigram时仍需要有界查询与实际计划验证。
[PostgreSQL 15索引合同](https://www.postgresql.org/docs/15/pgtrgm.html)
search_text是本行内容的确定性生成列而非第二可编辑正文，函数必须immutable且不查询别表。
[生成列约束](https://www.postgresql.org/docs/15/ddl-generated-columns.html)

索引内容随不可变revision新增，Entry指针切换即时决定可见版本；撤回同事务改变状态，
旧索引即使还存在也不能被新检索/上下文消费。默认不全量Embedding；只有检索失败/规模证据表明需要时
再评估，不能为了RAG把所有私有资料自动发云端。

### 项目上下文组装与失效

ContextBuilder仍属于Director，按任务组合：用户当前目标/本次消息→正式项目/剧本/角色约束→
当前计划与回执→明确选择的有效研究/知识→按需片段。保留来源类别和版本，不用研究覆盖正式设定。
查询只读，不在“获取上下文”时触发解析、调用模型、Apply或新生产。

每个上下文引用记录{kind,id,revision,content_hash,scope,availability,source_policy_version}，
实际发送快照保存在原Invocation中；安全日志只保留ID/hash/字节/省略数量，不复制私有全文。
用户研究更新、知识撤回、资料解除关联、公共资产限制/版本变化、正式内容版本变化都会使相关上下文失效；
实际工具写入/模型发送前重验，不因SSE或缓存没收到事件而继续用旧许可。
可重建context缓存以project/owner/目标/引用版本/hash为键；不存另一套业务current状态。

文本预算保留现有Agent完整tool-call/result组策略；必须保留系统规则、当前请求、工具合同和当前调用结果，
超限拒绝或请求更具体范围，不能截断安全规则。较老历史只能按完整组省略并说明。
资料按需取片段，不把整库塞入提示词。Vision按独立受控媒体字节/像素配额计量，不把base64偷偷排除所有预算；
其新消息结构由D5冻结，旧chat_tools_v1不能假装已支持多模态。

提示注入不改变tool allowlist、数据scope、模型绑定、批准范围或下一跳目的地。
Model生成的工具参数仍经过可信Scope+typed schema+版本+权限；其source引用只能选已授权提供集合。
被拒绝时按D3立即停止后续工具调用，不能让模型改拼写再绕过拒绝。
独立知识虽然可共享，仍是内容而非系统指令，不可提升为Skill/工具授权。

### 领域事件与调用影响

既有Files上传/修订/重试/解除关联入口复用；新增读取Extraction/Fragments、ResearchResult当前/历史、
保存/采纳差异/恢复、Analysis覆盖、Knowledge录入/发布/撤回/检索与ProjectKnowledgeReference端口。
HTTP/消息完整字段在API权威D7冻结；领域不会直接import Provider或Director ORM。
用户模型分析操作经固定research_import_v1授权，LocalParser只做本地处理，语义Invocation经D3受限文本端口。

事件最小payload仅project或owner scope、对象ID、revision、kind、cause_id；不发正文、对象键或秘密。
ExtractionPublished、ResearchAnalysisPublished、ResearchResultChanged、SourceDetached、
KnowledgePublished/Withdrawn、SourceUseChanged、ProjectKnowledgeReferenceChanged用于失效/唤醒。
变更与Outbox同事务，重复/丢失通知由事实扫描恢复，不用事件副本作为研究current权威。
知识事件不能广播到其他owner；跨Workspace共享只向同owner通知，源私有事件不跟公共频道传播原文。

实际事件模型当前没有owner作用域，旧NULL project策略不能承载新知识事件。按DATA_MODEL的D4回填
扩展scope_kind/owner_user_id、窄发现函数及SSE的显式OwnerEventScope；遗留无法归属事件不广播。
不能以workspace_id=None订阅所有用户，不能伪造Project来绕过独立知识业务。

### D4验证矩阵

| Case | 验证要求 |
|---|---|
| SRC01 | TXT多编码/空行、CSV多行格/空列、DOCX多part/表格；旧1-based→新0-based及UI反显准确 |
| SRC02 | 原生/扫描/混合PDF逐页定位，乱码字体转OCR；加密/权限/损坏/缺页不伪成功 |
| SRC03 | 中文简繁/英文图片OCR、方向/大像素/多帧；Vision描述与OCR引文分层，猜测标待核实 |
| SRC04 | 真实可解码音频、静音/噪音/专名、分块边界与时间码；无文本不幻造对白，缺模型明确不可用 |
| SRC05 | 视频音轨+采样帧、旋转/时间基准/无音轨，coverage如实反映采样；不以采样声称逐帧审阅 |
| SRC06 | XLSX多sheet/日期/公式缓存/错误dimension/合并格；不计算宏/外链，不漏单元格 |
| SRC07 | ZIP炸弹/XXE/路径穿越/魔数伪装/超限/子进程超时，单文件失败不饿死队列，无网络URL读取 |
| SRC08 | 六类findings/none/incomplete，非法引用/越界/cross-project/不可信模型输出拒绝，无空壳事实 |
| SRC09 | 用户保存/恢复/再分析/新文件并发、response lost、重启和迟到结果不丢用户修正 |
| SRC10 | 公开字段预览/发布/撤回、同owner两Workspace检索成功、异owner/私有原件访问拒绝 |
| SRC11 | 引用来源/知识/资产许可撤销导致上下文与新发送失效；已在途结果只记证据不自动采用 |
| SRC12 | 完整tool组预算、恶意资料指令、缺省上下文/检索为空/超限；无正式内容或模型身份被自动改写 |
| SRC13 | 27表对应的解析/研究/知识事务与RLS真实PG、capability UI不宣称未安装处理器、目标机资源与格式样本 |

所有用例仍待实施，真实资料/付费Vision与LLM不因本设计获得外发或费用授权。
本地样例和固定模型模拟证明机制，实际格式/模型质量与最终三作品仍需独立证据。

### D4审查结论

设计审查通过：七类格式的原生/本地推理/必要Vision路径、来源位置与覆盖、六类结果/零发现、
用户修改与再分析、知识发布/检索/撤回、上下文权限/预算/失效及SRC01–13均有合同落点。
复用真实Parser/Pillow/OpenCV/FFmpeg并核对官方依赖资料，没有启动解析器或安装依赖。
交叉检查修正旧定位1-based与新0-based差异、空图片输入不等于无文化信息、无人物不编造结果、
旧Outbox NULL project通配不能用于新owner知识事件；相应处理证据/索引/事件归属已回填DATA_MODEL。

D5继续冻结Vision消息/模型能力、实际出口和全部来源限制发送检查；D6完成用户界面，D7冻结安装/配置/精确API与测试文件。
这不是格式或模型质量已通过：Python3.14依赖、CLI/权重、真实格式、PG/事件隔离、资源容量和实际模型仍须I阶段实测。
运行权限/真实费用/机构资料外发边界未改变；发现后续字段或流程不足回填本权威后再审，不降低最终完成条件。
