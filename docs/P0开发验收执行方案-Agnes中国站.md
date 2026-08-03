# DramaForge P0 开发验收执行方案（Agnes 中国站）

**状态：DEVELOPMENT VERIFICATION COMPLETE / FINAL ACCEPTANCE BLOCKED**

**制定日期：2026-08-03**

**适用范围：P0 Graph 正确性、Agnes 中国站图片/视频链、人物一致性、个人创作主流程、交付与正式证据**

**上游事实源：[`../Agnes-first通用Provider适配规划.md`](../Agnes-first通用Provider适配规划.md)**

## 1. 文档目的

本文把当前 P0 剩余工作拆成可以直接开发、测试、复测和人工验收的任务。它回答以下问题：

1. 当前已有基础是什么，不能重复做什么。
2. 每个任务具体修改哪些职责、接口和数据。
3. Agnes 请求中的每个厂商参数来自哪里。
4. 自动化验收和人工验收分别怎样才算成功。
5. 失败后如何保存证据、定位首个根因、选择最小复测范围。
6. 哪些参数尚未得到官方合同或真实账户证据，不能凭经验硬编码。

本文不取代根目录 `01` 至 `06` 的冻结合同。若实现发现本文与冻结合同冲突，先停止冲突部分并更新 ADR/冻结合同，不通过临时代码绕开。

## 2. 已确认决策与当前工作方式

### 2.1 已确认决策

| 决策 | 当前结论 |
| --- | --- |
| 首个正式 Agnes Host | 中国站 `https://api.agnes-ai.cn` |
| 首个协议 Profile | `agnes_cn_v1` |
| 图片模型 | `agnes-image-2.1-flash` |
| 视频模型 | `agnes-video-v2.0` |
| 当前阶段 | 开发验收阶段，不实现额外的“开发/上线双模式” |
| 当前调用原则 | 在保证血缘、质量 Gate 和失败真实性的前提下，以断点续查、局部复测和有限人工重提节省时间 |
| 人脸阈值 | `0.60`，策略 ID `P0-S0A-2026-07-25` |
| P0 正式人物链 fallback | `none`，不能退化为纯文字关键帧 |
| 产品方向 | 个人创作、选片、精剪与交付；团队协作不在当前路线 |
| Agnes 费用 | 用户 2026-08-04 明确 Agnes 免费、不考虑费用；官方存在“免费 / 默认用户”，但仍受 RPM/订阅配额约束 |

本机 API Key 只能保存在 Git 忽略的 `.env` 或 Workspace 加密凭据中。文档、测试夹具、普通日志、错误消息、截图和证据 JSON 均不得包含明文 Key。由于 Key 已经通过会话传递，完成开发验收后应轮换一次。

### 2.2 开发验收阶段的省时原则

当前不新增运行模式或 feature flag。省时通过开发流程实现：

- 先跑无网络 Contract Test，再发真实请求，避免用付费调用发现字段错误。
- 先完成单 Canonical、单 Keyframe、单 Video 的垂直链，再扩大到 10 Shot。
- 视频创建成功后保存 `video_id` 和 `task_id`，超时后续查同一任务，不重新创建。
- 已有 Project 可用 `--resume-project-id` 续跑，不重复创建已经成功的媒体。
- 修复某节点后只重跑该节点及真实下游，不整剧重跑。
- 每次新创建请求形成新的 `ProviderOperation attempt`，不覆盖前一次失败或可能费用。
- 允许开发者人工确认后重新提交失败的创建请求，但禁止在网络结果不确定时由隐藏循环连续 POST。
- 任何省时手段都不能降低 `0.60` 人脸阈值、绕过 Video Drift/Continuity Review、伪造 Artifact 或跳过审核。

正式上线时的自动重试、限流和费用策略在上线前另行冻结，不在本轮增加一套并行运行模式。

## 3. 参数来源标识

本文使用以下来源标识，防止把内部字段伪装成厂商参数：

| 标识 | 含义 | 能否直接作为 Agnes Wire 参数 |
| --- | --- | --- |
| `AGNES-OFFICIAL` | 已在 Agnes 规划中根据官方文档核验 | 可以，必须按原层级和类型发送 |
| `DRAMAFORGE` | DramaForge 内部领域、API、审计或安全合同 | 不可以，由 Adapter 翻译或仅内部保存 |
| `PROBE-REQUIRED` | 官方规划未给出最终值，需当前账户真实 Probe | 不可以硬编码为“官方值” |
| `USER-DECISION` | 本轮用户明确确认的项目决策 | 仅用于决定配置或范围 |

以下内容不得直接发送给 Agnes：`character_identity`、`purpose`、Artifact ID、Workspace ID、Project ID、`quality_gated`、人脸阈值、内部错误码和完整审计对象。

## 4. 当前基线

### 4.1 已实现且可复用

- Windows 11 + Docker Compose 正式拓扑已运行。
- PostgreSQL 15、Redis 7、MinIO、API、Outbox dispatcher、default/heavy Arq Worker 已存在。
- 数据库迁移当前为 `20260803_0014`；本机 PostgreSQL `alembic current/heads` 均为该版本。
- 个人账号拥有私有 Workspace，Project、Worker 和对象访问有 RLS/所有权隔离。
- Brief/Plan、PlanningAuthorization、AgentRun、ProviderOperation、预算和成本基座存在。
- `GraphService` 已统一校验和物化 GraphNode/GraphEdge；正式 `shot-p0-v1` 为 9 Node/8 Edge，10 Shot PostgreSQL 路径为 90 Node/80 Edge。
- WorkerRuntime、Arq Worker 和恢复路径已从数据库依赖关系 fail-closed，稳定区分上游等待、缺 Run、终态失败和缺 Artifact。
- Snapshot 已返回 node key、attempt、起止时间、错误、成本、Artifact 和直接上游依赖。
- Agnes 中国站 `agnes_cn_v1` 已实现 Image I2I JSON、Video I2V first-frame、`video_id/task_id` 持久化、原任务续查和实际 Provider/model/Profile 审计。
- ProviderConnection、CapabilityEvidence、ModelBinding、ProjectBinding 已有迁移、RLS、API 和 UI；Key 只写不读，轮换清除账户/质量证据。
- Reference Delivery 已实现图片 Data URI、单 Artifact 短时 token、HEAD/GET 和 Provider 结果安全下载入库。
- Canonical Artifact、显式两源 Face 血缘和 InsightFace 512 维运行时存在；生产路径不再依赖“最近 Keyframe”回退。
- `APPROVED_FACE_THRESHOLD = 0.60` 已进入运行代码。
- Video Drift 已实现确定性起始/中段/结束/镜头变化抽帧和脱敏 score evidence；策略仍保持 `PROBE_REQUIRED`，不会用未批准阈值自动放行。
- Provider 配置和 9 节点运行时 UI 已实现；Mock Playwright 已覆盖 10 Shot Brief/Plan、审核、字幕局部返工和导出。
- MP4、SRT、素材包和 `timeline_json` 导出已实现。

### 4.2 尚未闭环

| 缺口 | 当前事实 | 影响 |
| --- | --- | --- |
| 候选源一致性 | 候选源提交 `cee5306`，叠加 `9191b6a`、`82c320f`、`a18655c` 及后续验收记录提交（`84cce3c`/`afe73c9`/`c6d85fb`/当前），工作树干净 | 可构建 Compose 并核对 `source_commit`；真实证据仍需执行 |
| Agnes 账户证据 | 本机存在 Key 配置；2026-08-04 真实 Probe 的 `GET /v1/models`、`image_t2i`、`image_i2i` 均返回 401（“无效的令牌”） | 当前 Key 不属于可调用账户；不能把 `documented/contract_tested` 冒充为 `account_verified` |
| 公网 Reference origin | `REFERENCE_PUBLIC_BASE_URL` 未配置 | Agnes 无法从公网 HTTPS HEAD/GET first-frame，真实 I2V 前置条件不成立 |
| 中国站响应 Fixture | 当前无本账户脱敏 I2I/I2V 响应 Fixture | 宽解析仍只能作为迁移兼容，不能冻结为已接受合同 |
| Video Drift 策略 | 抽帧和 evidence 已实现，阈值/approval ID 尚未通过固定样本校准 | Drift 只能保持阻断或人工复核，不能进入正式自动交付 |
| Canonical 审计父级 | `9191b6a` 已引入 canonical graph + NodeRun 审计父 Run + ProviderOperation（`node_run_id` 挂载，XOR 满足） | 真实 Canonical 生成审计链可写；仍需真实 Provider 执行 |
| 正式人物链 | 没有当前候选 commit 的 Canonical -> I2I -> Face >= 0.60 -> I2V -> Drift 真实证据 | 阶段 4 不能通过 |
| 正式 10 Shot 与运维 | 历史 evidence 绑定其他 commit；本轮未执行真实 10 Shot、备份/轮换/死信/取消/SSE/冷存储演练 | 阶段 6 和人工签字不能通过 |
| 全历史迁移 Ruff | `82c320f` 已清零：`ruff check app tests alembic` 通过（67 修复 + 91 E501 冻结豁免） | 无剩余 Ruff 债务 |

### 4.3 初始脏工作映射

用户要求先识别的 Graph/运行时脏改动不是额外旁支，主要占据本文 §§10.1-10.3 和阶段 1：

| 初始工作树能力 | 对应条款 | 本轮确认结果 |
| --- | --- | --- |
| GraphEdge 持久化、Graph definition 校验、幂等关系物化和发布一致性 | §10.1 `P0-GRAPH-01` | 单元测试覆盖环、悬空端点、重复 node/input、hash/发布关系不一致；PG 证明每版本 9/8 |
| `shot-p0-v1` 固定 9 Node/8 Edge | §10.1、阶段 1 | 10 Shot PG 路径证明 90 Node/80 Edge |
| required Edge 依赖解析和三类稳定错误码 | §10.2 `P0-GRAPH-02` | `UPSTREAM_RUN_MISSING`、`UPSTREAM_TERMINAL_FAILURE`、`UPSTREAM_ARTIFACT_MISSING` 均 fail-closed |
| WorkerRuntime/Arq claim gate、取消后完成采纳、恢复时数据库重建 | §10.2、阶段 1 | unit/PG integration 通过；下游不会靠进程内状态放行 |
| Snapshot node key、attempt、时间、错误、成本、Artifact、dependencies | §10.3 `P0-GRAPH-03` | API 类型和生产 UI 均已消费并由 E2E 验证 |

同一批脏工作中已有的 Agnes、Connection、Reference、Face lineage 和 Video Drift 改动分别对应 §§8-12 和阶段 2-4；本轮补齐了安全测试、RLS、worker 恢复测试、Provider UI、运行时错误 UI 和 Mock E2E。所有既有改动均保留并在原有方向上完成，没有回退用户工作。

## 5. 目标执行链

```text
登录用户选择私有 Workspace
  -> 配置 Agnes 中国站 Connection（Key 只写不读）
  -> 绑定 agnes-image-2.1-flash 到项目 keyframe 用途
  -> 绑定 agnes-video-v2.0 到项目 video 用途
  -> 锁定具体 Canonical Character Artifact 版本
  -> 发布 shot-p0-v1 GraphNode + GraphEdge
  -> Agnes Image I2I（extra_body.image[] Data URI）
  -> Keyframe Artifact 入库
  -> Face Review 读取显式上游 Keyframe + 固定 Canonical
  -> InsightFace score >= 0.60
  -> Approved Keyframe 生成短时签名 HTTPS URL
  -> Agnes Video I2V（顶层 image）
  -> 保存 video_id + task_id 并轮询同一远端任务
  -> Video Artifact 立即下载、校验、入 MinIO
  -> Video Drift Review 抽样检查
  -> Voice + Subtitle
  -> Composite
  -> Continuity Review
  -> 个人审核与锁定
  -> MP4 + SRT + 素材包 + timeline_json
```

任一必需上游缺失、失败、取消、预算阻断、质量阻断或 Artifact 不可用时，下游必须停止并给出稳定错误码，不能继续生成“看似成功”的结果。

## 6. Agnes 中国站外部合同

### 6.1 Host、认证和 Content-Type

| 参数 | 值 | 来源 | 验证 |
| --- | --- | --- | --- |
| Host | `https://api.agnes-ai.cn` | `USER-DECISION` + `AGNES-OFFICIAL` | Connection 显示 Host 与 Profile |
| Profile | `agnes_cn_v1` | `DRAMAFORGE` | ProviderOperation 必须记录 |
| 认证 | `Authorization: Bearer <API_KEY>` | `AGNES-OFFICIAL` | Key 不出现在响应/日志 |
| 图片 Content-Type | `application/json` | `AGNES-OFFICIAL` | Contract Test 断言 |
| 视频 Content-Type | `application/json` | `AGNES-OFFICIAL` | Contract Test 断言 |

内部实现应把 `base_url` 规范化为 Host 根地址，不把 `/v1` 永久混进 Connection Host。每个 Profile 自己拥有路径，才能同时支持 `/v1/...` 和根路径下的 `/agnesapi`。

迁移期间需要区分两个配置语义：当前旧 `AgnesHubClient` 仍以 `AGNES_BASE_URL=https://api.agnes-ai.cn/v1` 拼接 `/images/generations` 和 `/videos`，因此本机 `.env`、Compose 兼容默认值暂时保留 `/v1`；完成 `agnes_cn_v1` Profile 后，`ProviderConnection.base_url` 只保存 `https://api.agnes-ai.cn`，所有 `/v1/...` 与 `/agnesapi` 路径由 Profile 生成。不得把迁移期 Settings 值直接复制成新 Connection Host。

### 6.2 Agnes Image 2.1 文生图

```http
POST https://api.agnes-ai.cn/v1/images/generations
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

最小请求：

```json
{
  "model": "agnes-image-2.1-flash",
  "prompt": "<creative prompt>",
  "size": "1024x768",
  "extra_body": {
    "response_format": "url"
  }
}
```

字段约束：

| 字段 | 类型 | 必需 | 规则 | 来源 |
| --- | --- | --- | --- | --- |
| `model` | string | 是 | 首期为 `agnes-image-2.1-flash` | `AGNES-OFFICIAL` |
| `prompt` | string | 是 | 非空；完整内容不写普通日志 | `AGNES-OFFICIAL` |
| `size` | string | 是 | `1024x768` 仅作为官方示例 Contract Probe；正式 9:16 值必须按模型 Probe 固化 | `AGNES-OFFICIAL` + `PROBE-REQUIRED` |
| `extra_body.response_format` | string | 是 | 首期为 `url`，不得放顶层 | `AGNES-OFFICIAL` |

没有出现在上游规划官方合同中的 `n`、`tags` 或任意扩展字段，不进入 `agnes_cn_v1` 首期请求。

### 6.3 Agnes Image 2.1 图生图/人物条件化

端点、认证和 Content-Type 与 6.2 相同。Canonical 放在 `extra_body.image[]`：

```json
{
  "model": "agnes-image-2.1-flash",
  "prompt": "Make the image cinematic while preserving the character appearance and composition",
  "size": "1024x768",
  "extra_body": {
    "image": [
      "data:image/png;base64,..."
    ],
    "response_format": "url"
  }
}
```

| 字段 | 类型 | 必需 | 规则 | 来源 |
| --- | --- | --- | --- | --- |
| `extra_body.image` | string[] | 人物 I2I 必需 | 支持公网 URL 或 Data URI；P0 Canonical 固定使用 Data URI | `AGNES-OFFICIAL` + `DRAMAFORGE` |
| Data URI MIME | string | 是 | 来自受控 Artifact 的真实 MIME，不信任扩展名 | `DRAMAFORGE` |
| 图片数组数量 | integer | 首期固定 1 | 单主角 P0 只发送一个 canonical；多人物延期 | `DRAMAFORGE` |

禁止：

- `POST /v1/images/edits`。
- `multipart/form-data` canonical 请求。
- 顶层 `image` 作为 Agnes Image 2.1 I2I 字段。
- `tags: ["img2img"]`。
- 将本地 Windows 路径或 MinIO 内网地址发给 Agnes。
- 在日志、ProviderOperation 或证据中保存完整 Base64。

### 6.4 Agnes Video V2.0 图生视频

```http
POST https://api.agnes-ai.cn/v1/videos
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

请求：

```json
{
  "model": "agnes-video-v2.0",
  "prompt": "The character turns toward camera, stable facial appearance",
  "image": "https://<short-lived-public-host>/<opaque-token>",
  "num_frames": 121,
  "frame_rate": 24
}
```

| 字段 | 类型 | 必需 | 规则 | 来源 |
| --- | --- | --- | --- | --- |
| `model` | string | 是 | 首期为 `agnes-video-v2.0` | `AGNES-OFFICIAL` |
| `prompt` | string | 是 | 非空动作/镜头意图 | `AGNES-OFFICIAL` |
| `image` | string URL | I2V 必需 | 公网 HTTPS；指向已通过 Face Gate 的 Keyframe | `AGNES-OFFICIAL` + `DRAMAFORGE` |
| `num_frames` | integer | 是 | `<= 441` 且满足 `8n + 1`；`121` 是已核验示例 | `AGNES-OFFICIAL` |
| `frame_rate` | integer | 是 | `1..60`；首期示例为 `24` | `AGNES-OFFICIAL` |

P0 主链使用 I2V 顶层 `image`。如果以后使用关键帧动画，必须改为：

```json
{
  "model": "agnes-video-v2.0",
  "prompt": "A controlled transition between the supplied keyframes",
  "extra_body": {
    "image": [
      "https://<short-lived-public-host>/first-token",
      "https://<short-lived-public-host>/last-token"
    ],
    "mode": "keyframes"
  },
  "num_frames": 121,
  "frame_rate": 24
}
```

首帧 I2V 与关键帧动画是两种明确映射，不能同时发送顶层 `image` 和 `extra_body.mode=keyframes`。

### 6.5 视频创建响应和查询

创建响应可能同时包含 `video_id` 和 `task_id`。两者均作为不透明字符串保存：

```text
remote_task_id      = video_id（存在时优先）
remote_secondary_id = task_id（存在时保存）
```

查询优先级：

```text
1. GET https://api.agnes-ai.cn/agnesapi?video_id=<VIDEO_ID>
2. GET https://api.agnes-ai.cn/v1/videos/<TASK_ID>
```

规则：

- 有 `video_id` 时先走第 1 种。
- 只有 `task_id` 时走第 2 种。
- 不把 ID 解析成数字，不根据前缀猜 ID 类型。
- 是否在某类响应下允许查询路径 fallback，必须由账户 Probe 固化，不因一次 404 无限切换。
- Poll 网络错误只记录 `poll_error` 并继续同一远端任务，不把远端任务立即标为失败。

### 6.6 厂商响应解析

Profile 必须用 Contract Fixture 锁定以下事实：

- 图片成功响应中结果 URL 的准确字段路径。
- 视频创建响应中的 `video_id`、`task_id` 和初始 `status`。
- 视频查询响应中的终态、进度、产物 URL和错误字段。

当前实现兼容多个猜测字段的逻辑只能作为迁移输入，不能作为 `agnes_cn_v1` 已验证合同。首次中国站 Probe 后，应把脱敏响应形状保存到 `fixtures/providers/`，再收紧解析器。Fixture 不保存完整临时 URL，只保存字段结构和脱敏占位值。

## 7. DramaForge 内部类型化接口

以下是内部合同，不是 Agnes 参数。

### 7.1 `ImageGenerationIntent`

```text
purpose: canonical_image | shot_keyframe | auxiliary_image
prompt: string
output_spec:
  size: string
  response_format: url
reference_assets[]:
  id: UUID
  use: character_identity | composition | style
```

首期人物 keyframe 校验：

- `purpose=shot_keyframe`。
- `reference_assets` 恰好包含一个 `use=character_identity`。
- Artifact 必须属于当前 Project/Workspace 且未删除。
- Artifact 必须是已锁定 Canonical 版本。
- Adapter 从对象存储读取字节并生成 Data URI，API/前端不能直接提交任意 Base64 或远程 URL。

### 7.2 `VideoGenerationIntent`

```text
purpose: shot_video
prompt: string
output_spec:
  num_frames: integer
  frame_rate: integer
reference_assets[]:
  id: UUID
  role: first_frame | last_frame | keyframe | reference_image
```

P0 主链校验：

- 恰好一个 `role=first_frame`。
- 引用 Artifact 必须来自同 Shot 最新通过 Face Gate 的 Keyframe NodeRun。
- `num_frames <= 441` 且 `(num_frames - 1) % 8 == 0`。
- `1 <= frame_rate <= 60`。
- `last_frame/keyframe/reference_image` 不进入首期 I2V 请求。

### 7.3 Adapter 规范化返回值

```text
actual_provider: "agnes"
actual_model: string
protocol_profile: "agnes_cn_v1"
remote_task_id: string | null
remote_secondary_id: string | null
status: created | submitted | running | succeeded | failed | unknown_submission
artifact_result: normalized result | null
request_fingerprint: sha256
reference_fingerprints[]: sha256[]
```

执行层不得再通过 Adapter 类名、`flux` 槽位或 `kling` 槽位猜实际 Provider/model。

### 7.4 `ProviderOperation` 请求摘要

允许保存：

```json
{
  "protocol_profile": "agnes_cn_v1",
  "host": "api.agnes-ai.cn",
  "operation": "image.i2i",
  "model": "agnes-image-2.1-flash",
  "size": "<verified-size>",
  "reference_count": 1,
  "reference_artifact_ids": ["<uuid>"],
  "reference_fingerprints": ["<sha256>"],
  "reference_transport": "data_uri",
  "request_schema_fingerprint": "<sha256>"
}
```

禁止保存：API Key、Authorization header、完整 prompt、完整 Data URI、完整签名 URL、Cookie、下载授权 token 和 embedding 数组。

## 8. Connection、模型和项目绑定 API

本节 DramaForge API 已在迁移 `20260803_0014`、服务、路由和 UI 中实现。P0 首期只注册 `agnes_cn_v1`，普通用户只能选择官方中国站 Host，不提供任意代理 Host 输入框。数据模型允许以后增加其他 Profile，但本轮不实现 legacy Hub 或其他 Provider。

### 8.1 Provider Connection

#### 创建

```http
POST /api/v1/workspaces/{workspace_id}/provider-connections
```

```json
{
  "provider_type": "agnes",
  "display_name": "Agnes 中国站",
  "protocol_profile": "agnes_cn_v1",
  "api_key": "<write-only-secret>",
  "enabled": true
}
```

服务端固定/派生字段：

| 字段 | 规则 |
| --- | --- |
| `base_url` | Profile 固定为 `https://api.agnes-ai.cn`，不接受客户端覆盖 |
| `credential_id` | Key 加密存储后生成 |
| `verification_status` | 初始为 `unverified` |
| `verified_at` | 初始为 `null` |
| `created_by/updated_by` | 当前登录用户 |

响应永不返回 `api_key`：

```json
{
  "id": "<uuid>",
  "workspace_id": "<uuid>",
  "provider_type": "agnes",
  "display_name": "Agnes 中国站",
  "base_url": "https://api.agnes-ai.cn",
  "protocol_profile": "agnes_cn_v1",
  "enabled": true,
  "credential_configured": true,
  "verification_status": "unverified",
  "verified_at": null
}
```

#### 查询与更新

```text
GET   /api/v1/workspaces/{workspace_id}/provider-connections
GET   /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}
PATCH /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}
PUT   /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/credential
```

更新 Key、Profile 或 Host 后必须清空原有 `account_verified` 和 `quality_gated` 证据。P0 不提供明文 Key 读取接口。

### 8.2 Connection Probe

```http
POST /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/probes
```

```json
{
  "capability": "auth_models | image_t2i | image_i2i | video_i2v | video_poll_download"
}
```

每次只验证一个 capability，避免一个端点成功就推断全部能力。响应：

```json
{
  "probe_id": "<uuid>",
  "capability": "image_i2i",
  "status": "passed | failed | unknown_submission",
  "evidence_level": "account_verified",
  "http_status": 200,
  "provider_request_id": "<opaque-id-or-null>",
  "tested_at": "<rfc3339>",
  "error_code": null
}
```

Probe 是可能产生费用的 Command，必须受 CSRF、Workspace 所有权、频率限制、预算记录和审计约束。

### 8.3 Model Binding

```http
POST /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings
```

图片示例：

```json
{
  "media_type": "image",
  "model_id": "agnes-image-2.1-flash",
  "purpose": "keyframe",
  "enabled": true
}
```

视频示例：

```json
{
  "media_type": "video",
  "model_id": "agnes-video-v2.0",
  "purpose": "video",
  "enabled": true
}
```

状态必须分层显示：

```text
documented
contract_tested
account_verified
quality_gated
```

正式主角链只有四层全部成立时才可绑定。

### 8.4 Project Provider Binding

```http
PUT /api/v1/projects/{project_id}/provider-bindings/{purpose}
```

```json
{
  "model_binding_id": "<uuid>",
  "fallback_policy": "none"
}
```

`purpose` 首期只允许 `keyframe` 和 `video`。绑定必须属于 Project 所在 Workspace，跨 Workspace ID 返回 404/拒绝，不泄露对象存在性。

## 9. Reference Artifact Delivery

### 9.1 图片 Data URI

执行步骤：

1. 按 Artifact ID 查询并验证 Workspace/Project 归属。
2. 要求 `storage_state=available`。
3. 从 MinIO 读取字节并核对 `content_hash`。
4. 解析真实 MIME、像素和图片完整性。
5. 生成 `data:<mime>;base64,<bytes>`，仅存在于请求内存中。
6. 请求摘要只保存 Artifact ID、SHA-256、MIME、大小和 `transport=data_uri`。
7. 请求完成后释放编码内容，不写数据库或普通日志。

图片最大字节数、像素上下限和正式 9:16 `size` 组合在上游规划中没有最终官方值，标记为 `PROBE-REQUIRED`。实现时先建立可配置 allowlist，完成中国站 Probe 后将证据和最终值写入 Profile Fixture，不把经验值写成 Agnes 官方限制。

### 9.2 视频短时 HTTPS URL

视频首帧 URL 必须：

- HTTPS 公网可达。
- token 不含 Artifact object key、Workspace ID 或可枚举序号。
- 只授权读取一个已批准 Keyframe Artifact。
- 支持 `HEAD` 和 `GET`，因为 Provider 可能先预检再下载。
- 默认 TTL 候选为 60 分钟，但该值属于 `PROBE-REQUIRED`，需要覆盖排队与拉取延迟后固定。
- 返回正确 `Content-Type`、`Content-Length`，拒绝 Range/大小策略外请求时给出确定状态。
- 过期、撤销或篡改 token 返回 403/404，不能回退到公开对象地址。
- 普通日志和 ProviderOperation 只保存 URL token 指纹，不保存完整 URL。

需要新增的外部读取路由应使用不透明 token，不使用登录 Cookie：

```http
HEAD /api/v1/provider-references/{opaque_token}
GET  /api/v1/provider-references/{opaque_token}
```

该路由只读取事先授权的单一对象，不接受客户端传 object key、远程 URL或重定向目标。

### 9.3 Provider 结果入库

图片/视频成功响应中的临时 URL不能成为最终 Artifact：

1. 限制协议为 HTTPS。
2. 校验 Host/重定向，阻断私网、环回、链路本地、云元数据和 DNS rebinding。
3. 以流式方式下载，限制响应大小和超时。
4. 校验 HTTP 状态、Content-Type、实际媒体格式和非空字节。
5. 计算 SHA-256并写入 MinIO。
6. 创建不可变 Artifact，`produced_by_run_id` 指向当前 NodeRun。
7. Provider 临时 URL只保存脱敏指纹。

## 10. Graph 与 Worker 正确性任务

### 10.1 `P0-GRAPH-01` 统一物化 GraphEdge

实施：

- 将 Node/Edge 物化集中到 `GraphService`，调用方不分别拼 GraphEdge。
- `create_graph/update_draft_definition/publish` 校验节点 key 唯一、边端点存在、无自环、无环、必需端口不重复。
- `shot-p0-v1` 发布时数据库恰好有 9 个 GraphNode 和 8 个 GraphEdge。
- GraphVersion JSON 与关系表计算出的定义 hash 一致。
- 发布后 Node、Edge 和 definition 均不可变。
- 对开发数据库的旧 draft/test Graph 可重建；不要在没有源定义一致性检查时静默回填已发布生产数据。

自动验收：

- SQLite 单元测试覆盖结构校验和不可变性。
- PostgreSQL 集成测试验证 10 Shot 共 90 Node、80 Edge，且每个版本 9/8。
- 重复发布/重复物化不生成重复边。
- 删除/缺失节点、悬空边和环形定义均在发布前失败。

完成标准：新创建正式 Project 后，不再出现 `graph_versions > 0` 但对应 `graph_edges=0`。

### 10.2 `P0-GRAPH-02` Worker 从数据库执行依赖

Worker 每次 claim 前读取当前 GraphVersion 的 required GraphEdge，并按同 Shot、同 GraphVersion、最新 attempt 解析直接上游：

| 上游状态 | 下游动作 |
| --- | --- |
| `queued/running/cancel_requested` | defer 同一 Job，不 claim Provider |
| `completed/cached` | 校验 Artifact/Review 后继续 |
| `completed_after_cancel` | 只有显式采纳后继续，否则阻断 |
| `failed/blocked_budget/cancelled` | 下游终止，`UPSTREAM_TERMINAL_FAILURE` |
| 没有上游 Run | 下游终止，`UPSTREAM_RUN_MISSING` |
| 成功但必需 Artifact 缺失 | 下游终止，`UPSTREAM_ARTIFACT_MISSING` |
| Review 为 `blocked/needs_human` | 不进入自动下游；等待解决或终止 |

`prompt/face_review/video_drift_review/continuity_review` 等非媒体节点也必须有明确结果 Artifact 或正式只读输出合同，不能靠“状态 completed”掩盖缺失证据。

自动验收：

- 10 Shot 并发启动，任何 `face_review.started_at` 都不得早于同 Shot Keyframe 成功结束。
- 任何 Video ProviderOperation 都不得早于同 Shot Face Review 通过。
- 上游失败后下游不得产生 ProviderOperation 或费用。
- 不同 Shot 的成功上游不能满足当前 Shot。
- 重启 Worker 后依赖判断可从数据库恢复，不依赖进程内字典。

### 10.3 `P0-GRAPH-03` Snapshot 可观察性

扩展 `GET /api/v1/projects/{project_id}/snapshot` 的 NodeRun 读取模型：

```text
started_at
finished_at
error_code
error_summary（脱敏）
node_key
upstream_dependencies[]:
  node_key
  run_id
  status
  result_artifact_id
```

人工验收者必须能仅通过 UI/API 确认节点顺序和阻断原因，不要求直接连 PostgreSQL 才能判断。

## 11. Agnes Adapter 实施任务

### 11.1 `P0-AGNES-01` 建立 `agnes_cn_v1` Profile

实施：

- Profile 固定 Host 和 6.2 至 6.5 的路径/字段。
- Base URL 与 path 分离。
- Image/Video Adapter 的 `provider` 均改为 `agnes`。
- Adapter 返回 `actual_model` 和 `protocol_profile`。
- 当前 `flux/kling` 入口只作迁移兼容，执行层不再用它们表示真实 Provider 身份。
- 删除 canonical `/images/edits` multipart 分支。
- 视频 Create 接收类型化 Intent，实际发送 `image/num_frames/frame_rate`。
- 同时保存 `video_id/task_id`。

Contract Test 必须断言：

1. I2I 只访问 `/v1/images/generations`。
2. 请求是 JSON。
3. Canonical 只在 `extra_body.image[]`。
4. `response_format` 只在 `extra_body`。
5. I2V 首帧只在顶层 `image`。
6. Keyframes 模式使用 `extra_body.image[] + mode=keyframes`。
7. 非法 `num_frames/frame_rate/reference role` 在发网络请求前失败。
8. 请求摘要不含 Key、Base64 和签名 URL。

### 11.2 `P0-AGNES-02` 创建、轮询和下载的时间策略

当前为开发验收阶段，固定以下实现原则，不新增模式开关：

- 图片/视频 POST 每次提交形成一个 ProviderOperation。
- 400、401、403不自动重试。
- 429遵循 `Retry-After`；若重新 POST，创建新 attempt 并记录可能费用。
- 5xx 可由开发者确认后快速重提，新请求仍是新 attempt。
- Timeout/连接中断且没有远端 ID时标为 `unknown_submission`，不得在同一隐藏循环连续 POST。
- 已获得 `video_id/task_id` 后，网络/Worker 超时只续查原任务。
- Poll 间隔首期使用现有正式证据值 5 秒；长视频总等待上限沿用 1620 秒，超时后状态保持可恢复而不是抹掉远端 ID。
- 结果下载可重试，因为它不创建新媒体；每次下载失败记录状态、Host、HTTP 状态和 MIME 摘要。

现有“最多 8 次图片/视频创建 POST”必须移除。省时间依靠一键重提、断点续查和局部复测，不依靠不可审计的重复提交。

### 11.3 `P0-AGNES-03` 能力证据状态机

每个 `connection + profile + model + capability` 单独记录：

```text
documented
contract_tested
account_verified
quality_gated
```

主角正式链必须全部满足。`GET /models` 成功只证明鉴权/模型可见性，不能自动把 I2I/I2V 标为已验证。

## 12. 人物一致性实施任务

### 12.1 `P0-FACE-01` 显式两源血缘

实施：

- Keyframe NodeRun snapshot 固定 `canonical_artifact_id/object_key/content_hash`。
- Face Review snapshot 固定 `probe_artifact_id/object_key/content_hash` 和 canonical 版本。
- 删除“找当前 Project/Shot 最近一张 Keyframe”的生产回退。
- 两张图片字节相同必须阻断为错误证据，不把 self-match 当通过。
- ProviderOperation 记录实际 Reference fingerprint。

自动验收：

- Shot A 的 Face Review 不能读取 Shot B Keyframe。
- attempt 2 Face Review 只能读取明确绑定的 attempt 2 Keyframe。
- 缺 probe/canonical、hash 不一致和 Artifact 不可用全部 fail-closed。

### 12.2 `P0-FACE-02` `0.60` Gate 与有限返工

固定策略：

```text
policy_id      P0-S0A-2026-07-25
policy_version s0a-far-frr-v1
threshold      0.60
max reworks    3（当前 formal proof 开发验收值）
```

处理：

- `score >= 0.60`：`passed`，允许进入 Video。
- `score < 0.60`：`blocked`，创建新的 Keyframe attempt，最多 3 次。
- 无人脸/embedding 缺失：`needs_human`，不得直接 approve 或进入 Video。
- 3 次仍未通过：停止自动返工，要求人工检查 Canonical、Prompt、模型能力或更换输入，不降低阈值。
- 每次返工保留旧 Artifact、score、ProviderOperation 和费用。

### 12.3 `P0-VIDEO-01` Video Drift Review

实施：

- 从已入库 Video Artifact 抽取起始、中段、结束和镜头变化采样帧。
- 每帧与固定 Canonical 做两源人脸比较。
- 保存采样时间、检测状态、score 和规则版本，不保存 embedding 数组。
- 确定违反阻断；边缘/缺脸可进入个人人工复核，但未解决前不能自动交付。

视频漂移的最终阈值和镜头变化采样算法在 Agnes 规划中没有给出已批准数值，属于 `PROBE-REQUIRED`。开发顺序必须是：先形成固定视频样本和离线分数分布，再批准策略；不得直接复用 Keyframe `0.60` 或写一个方便通过的值。

## 13. 个人创作 UI 与 E2E 任务

### 13.1 `P0-UI-01` Provider 配置

用户应能：

1. 在 Workspace 设置中创建“Agnes 中国站”连接。
2. 填 Key，保存后只能看到“已配置”和 Key 版本，不能读回明文。
3. 逐项运行鉴权、I2I、I2V Probe。
4. 查看 `documented/contract_tested/account_verified/quality_gated`，不能只显示模糊“支持”。
5. 为 Project 选择 Keyframe 和 Video 模型绑定。

### 13.2 `P0-UI-02` 生产与错误呈现

每个 Shot 显示固定 9 节点、当前 attempt、依赖、状态、开始/结束时间、费用、Artifact 和错误建议。必须区分：

- 等待上游。
- 等待 Provider。
- Provider 创建结果未知。
- Provider 失败。
- Face 低分。
- 缺人脸/需人工。
- Video Drift 阻断。
- 预算不足。
- Worker/队列不可用。
- 可局部重跑的节点和预计影响下游。

### 13.3 `P0-E2E-01` 修复主业务 Playwright

- 删除旧 `api-status` 假设，按当前首页 DOM/可访问名称定位。
- Global setup 使用唯一端口并确保 teardown，无遗留 Vite 进程。
- 登录、Workspace、建项、快速模式、专业模式、Brief/Plan、10 Shot、审核和导出形成业务流。
- Mock E2E 用于稳定 UI 行为；真实 Provider E2E 单独运行并绑定证据，不能把 mock 当正式媒体证明。
- CI 至少运行不付费的 P0 主业务 Mock E2E，不再只有 shell smoke。

## 14. 分阶段任务与完成 Gate

### 阶段 0：清理开发基线（0.5 至 1 天）

| Task | 内容 | 自动 Gate |
| --- | --- | --- |
| `P0-BASE-01` | 登记 Agnes 规划/执行文档，清理目录合规失败 | 全部目录测试通过 |
| `P0-BASE-02` | 固定中国站 Profile 决策，Key 仅本机/密文 | `git grep` 不发现 Key |
| `P0-BASE-03` | 保存当前 Gate、数据库残留任务和版本基线 | 基线报告可复核 |

完成条件：工作树中的已知失败都已分类，后续失败可判断是新增回归还是历史缺口。

### 阶段 1：Graph 正确性（2 至 4 天）

顺序：`P0-GRAPH-01 -> P0-GRAPH-02 -> P0-GRAPH-03`。

完成条件：

- 新建 10 Shot 有 90 Node、80 Edge。
- 全部依赖按数据库关系执行。
- 上游失败不产生下游 ProviderOperation/费用。
- Snapshot 可证明执行时间和依赖。
- PostgreSQL 并发测试通过。

### 阶段 2：Agnes 中国站 Contract（2 至 3 天）

顺序：类型化 Intent -> `agnes_cn_v1` -> 请求 Fixture -> 响应 Fixture -> 身份/审计。

完成条件：

- 无网络 Contract Test 全绿。
- 代码中正式 canonical 路径不再出现 `/images/edits`。
- Video 必须有已批准 first-frame Reference。
- ProviderOperation 显示 `agnes`、真实模型和 Profile。

只有阶段 2 通过后才使用真实 Key 发图片/视频请求。

### 阶段 3：Connection 与 Reference Delivery（3 至 5 天）

顺序：迁移/RLS -> Connection API -> 模型/项目绑定 -> Data URI -> HTTPS token -> 安全测试。

完成条件：

- Key 只写不读。
- 跨 Workspace Connection/Binding/Artifact 均拒绝。
- Agnes 能 `HEAD/GET` 指定 Keyframe URL。
- 过期 URL、篡改 token、其他 Artifact 均不可读取。
- 数据库和日志无 Base64/Key/完整签名 URL。

### 阶段 4：单 Shot 真实人物链（2 至 4 天，取决于 Provider）

Probe 顺序不可跳：

1. 鉴权和模型可见性。
2. Image T2I。
3. 固定 Canonical Image I2I。
4. Keyframe Face `>= 0.60`。
5. Approved Keyframe Video I2V。
6. `video_id/task_id` 查询和结果下载。
7. Video Drift Review。

完成条件：单 Shot 从 Canonical 到 Video 的三段 SHA-256、Run、ProviderOperation、Artifact 和质量证据全部相连。

### 阶段 5：个人 UI 与恢复（3 至 5 天）

完成条件：普通用户不改 `.env`、不连数据库、不手工补队列状态，就能配置 Connection、运行 Shot、理解失败、局部重跑、审核和导出。

### 阶段 6：10 Shot 正式证据（2 至 4 天，取决于 Provider）

完成条件：

- 干净候选 commit 和 Compose source 一致。
- 3 至 5 场、至少 10 Shot、至少 1 名主角。
- 10 Shot x 9 节点及 Artifact/血缘满足 Gate。
- 所有主角 Face Review 有真实 score 且 `>= 0.60`。
- Video Drift/Continuity Review 全部解决，无未处理阻断。
- 10 Shot 经个人审核后导出 MP4、SRT、素材包、timeline JSON。
- §3.1 为全 PASS、0 FAIL、0 BLOCKED。
- 完成备份恢复、Key 轮换、Outbox/死信、取消、SSE 和冷存储演练。

## 15. 自动化测试矩阵

| 层级 | 必测内容 | 失败含义 |
| --- | --- | --- |
| Contract unit | Agnes 路径、JSON 层级、字段校验、响应解析、脱敏 | Adapter 合同错误，禁止真实 Probe |
| Domain unit | Graph 校验、依赖状态、Face Gate、有限返工、局部失效 | 领域规则错误 |
| PostgreSQL integration | RLS、Connection、GraphEdge、并发 claim、依赖传播、血缘 | 正式数据库语义错误 |
| Object integration | Data URI、签名 URL、HEAD/GET、TTL、MIME、下载入库 | Reference/产物输送错误 |
| Frontend unit | 配置、状态、错误建议、局部重跑影响 | UI 读取/交互错误 |
| Playwright mock | 个人完整业务流 | 产品流程回归 |
| Real provider probe | 当前 Connection 的真实 I2I/I2V | 账户/服务/质量问题 |
| Formal proof | 真实 10 Shot 和交付 | P0 阶段未完成 |

每个实现 PR 最低执行：

```powershell
cd D:\dramaforge\backend
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest tests\unit -q
.\.venv\Scripts\python.exe -m pytest tests\integration -q -rs --fail-on-skip

cd D:\dramaforge\frontend
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e -- tests/e2e/smoke.spec.ts
npm.cmd run test:e2e -- tests/e2e/p0_bootstrap.spec.ts

cd D:\dramaforge
git diff --check
.\backend\.venv\Scripts\python.exe scripts\check_directory_compliance.py
```

## 16. 失败分类与处理矩阵

| 失败类 | 证据/错误码 | 当前动作 | 重新分析与复测 |
| --- | --- | --- | --- |
| 配置缺失 | `PROVIDER_NOT_CONFIGURED` | 调用前停止 | 检查 Connection、Key 配置状态；只重测配置/鉴权 |
| 模型未验证 | `MODEL_BINDING_NOT_VERIFIED` | 调用前停止 | 逐项 Probe，不用 models 列表代替能力 |
| Canonical 缺失 | `CANONICAL_REFERENCE_REQUIRED` | 调用前停止 | 注册并锁定 Canonical；从 Keyframe 重跑 |
| Graph 上游缺失 | `UPSTREAM_RUN_MISSING` | 下游停止 | 检查 GraphEdge/Shot/attempt；从首个缺失节点重跑 |
| Graph 上游失败 | `UPSTREAM_TERMINAL_FAILURE` | 下游停止 | 先分析上游首因；禁止直接重跑下游 |
| 上游 Artifact 缺失 | `UPSTREAM_ARTIFACT_MISSING` | 下游停止 | 查 Run/Artifact/ObjectStore 一致性 |
| 参数校验失败 | `PROVIDER_REQUEST_INVALID` | 不发网络请求 | 修 Intent/Profile Contract，只跑 Contract Test |
| HTTP 400 | `PROVIDER_BAD_REQUEST` | 不自动重试 | 对照脱敏请求结构和官方 Fixture；修合同后单 Probe |
| HTTP 401 | `PROVIDER_AUTH_FAILED` | 不重试 | 更新 Key并重新鉴权 Probe |
| HTTP 403 | `PROVIDER_FORBIDDEN` | 不重试 | 查账户权限/模型授权，不改请求绕过 |
| HTTP 429 | `PROVIDER_RATE_LIMITED` | 遵循 Retry-After | 保存 attempt；窗口后重提最小节点 |
| HTTP 5xx | `PROVIDER_UNAVAILABLE` | 当前 attempt 失败 | 查服务状态；开发者确认后新 attempt，不覆盖旧费用 |
| 创建网络不确定 | `PROVIDER_SUBMISSION_UNKNOWN` | 不隐藏重复 POST | 有远端 ID则续查；无 ID则人工确认后新 attempt |
| Poll 暂时失败 | `PROVIDER_POLL_TRANSIENT` | 保留远端 ID并继续 | 只复测 Poll，不重新创建媒体 |
| 远端任务失败 | `PROVIDER_TASK_FAILED` | 当前 NodeRun 失败 | 查脱敏 Provider error；按内容/服务/参数分类 |
| 下载失败 | `PROVIDER_MEDIA_DOWNLOAD_FAILED` | 不创建 Artifact | 续下同一结果 URL或任务，不重新生成 |
| MIME/媒体无效 | `PROVIDER_MEDIA_INVALID` | 隔离结果 | 保存 hash/头摘要；修下载解析或重提当前节点 |
| Face 无法检测 | `FACE_PROBE_UNAVAILABLE` | `needs_human`，阻断视频 | 检查生成构图/清晰度；从 Keyframe 返工 |
| Face 低分 | `FACE_BELOW_THRESHOLD` | 阻断，最多 3 次返工 | 对照 Canonical/Prompt/Reference fingerprint，不降 0.60 |
| Video Drift | `VIDEO_DRIFT_BLOCKED` | 阻断 Composite | 查具体采样帧和分数；从 Video 重跑 |
| 队列不可用 | `QUEUE_UNAVAILABLE` | 已提交 Run 保留 | 恢复 Redis/Worker 后重新 enqueue，不重建业务对象 |
| 预算不足 | `blocked_budget` | 不调 Provider | 增加/调整预算后重试原节点 |
| Export Gate | `APPROVE_GATE/EXPORT_GATE` | 禁止导出 | 解决缺失节点/审核，再只重跑导出 |

## 17. 失败后的重新分析流程

每次失败按以下顺序处理，不以“再跑一次看看”代替分析。

### 17.1 保存最小证据

记录：

```text
source_commit / dirty
project_id / shot_id
graph_version_id / node_key / node_run_id / attempt_no
provider_operation_id
protocol_profile / model / capability
request schema fingerprint / reference fingerprints
remote video_id / task_id（不透明 ID，可脱敏展示）
HTTP status / stable error code / timestamps
result Artifact ID / SHA-256（如果存在）
face/video review policy version and score（如果适用）
```

不记录 Key、完整 prompt、Data URI、签名 URL、下载 token 和 embedding。

### 17.2 找到 DAG 中第一个因果失败

1. 按 GraphEdge 从上游到下游检查。
2. 找到第一个 `failed/blocked/missing/unknown_submission` 节点。
3. 下游连带失败只标为影响，不当成多个独立根因。
4. 核对该节点绑定的 Shot、attempt、Canonical/Probe hash。
5. 核对是否在 Provider 调用前已经可失败；可前置校验的问题不得继续消耗真实调用。

### 17.3 归类

只能归入一个首要类别：

```text
CODE_CONTRACT
DATA_LINEAGE
ENVIRONMENT_NETWORK
ACCOUNT_PERMISSION
PROVIDER_SERVICE
CONTENT_POLICY
QUALITY_GATE
QUEUE_RECOVERY
DELIVERY
```

如果证据不足，状态写 `UNKNOWN_NEEDS_EVIDENCE`，不能猜成 Provider 故障。

### 17.4 写可证伪假设

例：

```text
假设：I2I 失败是因为 response_format 被放到顶层。
支持证据：脱敏请求结构与 agnes_cn_v1 Fixture 不一致，HTTP 400。
反证方法：Contract Test 断言 extra_body.response_format 后只跑 1 次 I2I Probe。
通过条件：HTTP 成功、Artifact 入库、ProviderOperation schema fingerprint 更新。
```

### 17.5 选择最小复测范围

| 修复内容 | 最小复测 |
| --- | --- |
| 请求 JSON/解析 | Contract Test + 单 capability Probe |
| Key/账户 | auth/models Probe + 失败 capability Probe |
| Reference URL | HEAD/GET 安全测试 + 单 I2V Create |
| Poll | 用原 `video_id/task_id` 续查 |
| Face 血缘 | 当前 Shot Face Review，不重生 Video |
| Keyframe Prompt/Reference | 当前 Shot 从 Keyframe 及下游重跑 |
| Video Drift | 当前 Shot 从 Video 及下游重跑 |
| Subtitle | Subtitle + Composite + Continuity |
| Graph/Worker | PG 并发测试 + 1 Shot；通过后再 10 Shot |
| Export | 已审核 Artifact 上只重跑 Export |

### 17.6 关闭失败的条件

不能因为一次偶然成功就关闭。至少满足：

- 失败有稳定错误码和根因分类。
- 针对性自动回归已加入且通过。
- 最小真实 Probe 通过。
- 没有降低质量阈值或绕过审核。
- 新证据与当前 commit/source 一致。
- 旧失败 evidence 保留，新的 attempt 单独存在。

## 18. 人工验收手册

### 18.1 验收前提

人工验收开始前，开发者必须提供：

- 一个干净候选 commit SHA。
- `git status --short` 为空。
- Compose `/health.source_commit` 与 SHA 一致。
- 自动质量、PG integration、Playwright 主流程全部通过。
- Agnes 中国站 Connection 已配置，但界面/API不显示 Key。
- 当前费用预算和预计图片/视频调用次数。
- 冻结的 3 至 5 场、10 Shot、单主角样本。
- 固定 Canonical 图片及其 SHA-256。

如果任一前提不满足，人工验收状态为 `BLOCKED`，不是“带问题通过”。

### 18.2 验收 A：Connection 与安全

操作：

1. 登录个人账号并选择 Workspace。
2. 新建“Agnes 中国站”Connection。
3. 输入 Key并保存。
4. 刷新页面、退出再登录。
5. 运行鉴权和模型可见性 Probe。
6. 打开浏览器 Network、应用日志和 Connection API 响应。

成功标准：

- Host 显示 `https://api.agnes-ai.cn`，Profile 为 `agnes_cn_v1`。
- 只显示 `credential_configured=true`/Key 版本，不显示明文或可逆片段。
- 鉴权 Probe 成功，但 I2I/I2V 状态不会被自动冒充为成功。
- 另一个 Workspace 无法读取该 Connection、Binding 或 Key 状态。
- 日志/响应/证据搜索不到明文 Key、Authorization 和完整签名 URL。

### 18.3 验收 B：单主角图片链

操作：

1. 新建 Project并绑定 Agnes Image 2.1。
2. 上传/锁定固定 Canonical。
3. 创建一个需要主角身份的 Shot。
4. 发起 Keyframe。
5. 查看 NodeRun、ProviderOperation、Artifact 和 Face Review。

成功标准：

- 实际请求是 `POST /v1/images/generations` JSON。
- 请求摘要显示 1 个 `character_identity` Reference、`transport=data_uri`。
- 不出现 `/images/edits`、multipart 或纯文字 fallback。
- Keyframe Artifact 可打开，hash/字节数/尺寸存在。
- Face Review 明确绑定该 Keyframe 和固定 Canonical。
- `face_score >= 0.60` 才显示通过。
- score、策略版本、两个 Artifact hash 可核对。

负向验收：移除 Canonical 后再发起同类 Shot，必须在 Provider 调用前失败，且不会新增付费 ProviderOperation。

### 18.4 验收 C：单主角视频链

操作：

1. 使用验收 B 已通过的 Keyframe。
2. 发起 Video。
3. 查看 Reference URL 的 HEAD/GET 访问和远端任务状态。
4. 在视频生成期间重启 heavy Worker一次。
5. 等待同一远端任务恢复、下载和入库。

成功标准：

- Video 请求顶层 `image` 指向短时 HTTPS URL。
- `num_frames` 满足 `<=441` 和 `8n+1`，`frame_rate` 在 `1..60`。
- ProviderOperation 保存 `video_id/task_id`，不因 Worker 重启创建第二个视频任务。
- Agnes 能对同一 token 执行 HEAD/GET。
- token 过期或篡改后不能访问，不能枚举其他 Artifact。
- 最终 Video 已下载到 MinIO，Artifact 不引用厂商临时 URL。
- Video Drift Review 有实际采样记录；阻断结果不能进入 Composite。

### 18.5 验收 D：失败与恢复

至少人工观察以下场景：

1. 错误 Key：401/403，不自动重试。
2. 缺 Canonical：调用前失败。
3. Face 低分：不能进入 Video，有限返工后仍失败则停止。
4. Worker 重启：远端 ID保留，恢复 Poll。
5. Redis 短暂不可用：已提交 Run 不丢失，恢复后可 enqueue。
6. Subtitle 修改：只重跑 Subtitle、Composite、Continuity，不重跑 Keyframe/Video/Voice。
7. 预算不足：ProviderOperation 不创建。
8. 未审核 Shot：Export 被拒绝。

成功标准：每个场景都能看到稳定错误码、建议动作、影响范围和新的 attempt；不存在无提示卡死、重复收费不可解释或跳过 Gate。

### 18.6 验收 E：10 Shot 完整个人创作流

操作：

1. 从创意/剧本创建正式 Project。
2. 完成 Brief/Plan 两级确认并物化 10 Shot。
3. 在快速模式与专业工作台之间切换，确认仍是同一 Project。
4. 运行 10 Shot。
5. 处理所有失败、Face/Video Drift/Continuity Review。
6. 逐 Shot 个人审核并锁定。
7. 修改一个 Shot 的字幕并执行局部返工。
8. 导出并下载 MP4、SRT、素材包和 timeline JSON。

成功标准：

- 每个 Shot 恰有 `shot-p0-v1` 的 9 类最终节点结果。
- 每个 GraphVersion 恰有 9 Node/8 Edge。
- Snapshot 时间证明依赖顺序正确。
- 10 Shot 的 Artifact 独立、可打开且回链 Run/Provider/成本。
- 所有主角 Shot 有真实 Face score 且最终 `>=0.60`。
- 所有未决 `needs_human/blocked/failed` 已解决，不能带病 approve。
- 字幕返工没有改变 Keyframe、Video 和 Voice Artifact ID/hash。
- 导出四项均可下载，现场 SHA-256 与 manifest 相同。
- 刷新页面或重启服务后状态可重建，不要求开发者修库。

### 18.7 最终签字条件

只有以下项目全部满足，人工验收才写 `ACCEPTED`：

```text
[ ] 候选 commit 干净且 source 一致
[ ] 自动质量和主业务 E2E 全绿
[ ] Agnes 中国站 I2I/I2V account_verified
[ ] 单主角质量链 quality_gated
[ ] Graph 顺序、失败传播和恢复已证明
[ ] 10 Shot 全节点、审核和局部返工完成
[ ] MP4/SRT/素材包/timeline JSON 可下载且 hash 一致
[ ] §3.1 Gate 全 PASS，0 FAIL，0 BLOCKED
[ ] 备份恢复、Key 轮换、Outbox/死信、取消、SSE、冷存储演练完成
[ ] 证据无 Key、Base64、完整签名 URL、下载 token 或 embedding
[ ] 验收人、日期、费用摘要和已知限制已记录
```

只满足单 Shot、页面可打开、历史证据成功、单元测试通过或 Provider 偶然返回成功，均不能签 P0 完成。

## 19. 正式证据命令

先构建与启动绑定候选 commit 的 Compose：

```powershell
cd D:\dramaforge
docker compose build api dispatcher worker-default worker-heavy migrate
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8000/health
```

单 Provider smoke 只能证明 Probe，不是 P0 完成：

```powershell
cd D:\dramaforge\backend
.\.venv\Scripts\python.exe ..\scripts\run_agnes_e2e_real.py `
  --idea "冻结验收创意"
```

正式 10 Shot proof：

```powershell
cd D:\dramaforge\backend
.\.venv\Scripts\python.exe ..\scripts\prove_p0_mvp_formal.py `
  --base http://127.0.0.1:8000 `
  --timeout-seconds 900 `
  --poll-interval-seconds 5 `
  --max-face-reworks 3 `
  --idea "<冻结创意>" `
  --lead-name "<主角名>" `
  --lead-prompt "<冻结 Canonical 描述>"
```

如外部 Provider 超时但已有 Project/远端任务，优先续跑，避免重复媒体：

```powershell
.\.venv\Scripts\python.exe ..\scripts\prove_p0_mvp_formal.py `
  --base http://127.0.0.1:8000 `
  --resume-project-id "<project-id>" `
  --resume-email "<owner-email>" `
  --idea "<同一冻结创意>" `
  --lead-name "<同一主角名>" `
  --lead-prompt "<同一 Canonical 描述>"
```

最后运行 Gate：

```powershell
.\.venv\Scripts\python.exe ..\scripts\run_p0_section31_gate.py `
  --base http://127.0.0.1:8000 `
  --script-fixture ..\fixtures\scripts\p0_10_shots.md `
  --evidence ..\tmp\p0-evidence\<commit>\formal\multi_shot_chain.json
```

## 20. 当前仍需在开发中用 Probe 固化的参数

以下参数不能在实现时声称是 Agnes 官方确定值：

| 参数 | 当前处理 | 固化条件 |
| --- | --- | --- |
| Image 2.1 正式 9:16 `size` | Contract Probe allowlist | 中国站账户请求成功并保存 Fixture |
| 图片输入最大字节/像素 | 先用内部安全上限，标注内部值 | 官方资料或真实边界 Probe |
| Reference URL 最终 TTL | 候选 60 分钟 | 覆盖真实排队/HEAD/GET 时延 |
| 视频结果响应准确字段路径 | 宽解析仅用于迁移 | 中国站脱敏响应 Fixture |
| 视频漂移阈值 | 不硬编码通过值 | 固定样本校准、批准策略版本 |
| 镜头变化抽帧算法 | 已实现确定性起始/中段/结束和镜头变化抽样 | 固定真实视频样本分布复核并与阈值策略一起批准 |
| 真实费用单价 | 从 ProviderOperation/账单记录 | 当前账户真实账单证据 |

任何 `PROBE-REQUIRED` 项失败都应缩小为对应 capability 的阻断，不推翻已经证明的 Graph、RLS 或其他能力，也不允许用假值把完整 Gate 变绿。

## 21. 完成后的交付物

- 已接受的 `agnes_cn_v1` Contract Fixture。
- GraphEdge 持久化、依赖执行和失败传播实现及测试。
- ProviderConnection、ModelBinding、ProjectBinding 迁移/API/UI。
- Data URI 和短时 Reference URL 安全实现。
- 单 Shot Canonical -> Keyframe -> Face -> Video -> Drift 的真实证据。
- 修复后的个人创作 Playwright 主流程。
- 当前干净 commit 的 10 Shot formal/gate/ops 报告。
- 人工验收记录，包含验收人、时间、commit、Provider 配置摘要、费用、失败清单和最终结论。

## 22. 2026-08-03 开发验收记录

### 22.1 结论

```text
IMPLEMENTED SCOPE: PASS（Graph、Agnes Adapter、Connection/Reference、Face 血缘、UI、Mock E2E）
OPEN DEVELOPMENT ITEMS: 部分解除（Canonical 审计父级、全历史 Ruff 已修复；Video Drift 策略批准仍 BLOCKED）
AUTOMATED VERIFICATION: PASS（含全历史 migration Ruff）
REAL AGNES PROVIDER PROOF: 部分 PASS（鉴权、T2I、Canonical I2I 已 `account_verified`；I2V 与 Face 评分证据仍 BLOCKED）
CURRENT COMMIT FORMAL PROOF: BLOCKED（候选 commit cee5306 已形成，栈已绑定 339569c，待 Face/Video 证据）
MANUAL ACCEPTANCE: BLOCKED
FINAL VERDICT: BLOCKED / NOT ACCEPTED
```

2026-08-04 更新：候选 commit `cee5306` 形成（63 条脏工作树已提交），`9191b6a` 修复 Canonical 审计父级缺口（ProviderOperation XOR 合同满足），`82c320f` 清零全历史 Ruff（`ruff check app tests alembic` 通过），`a18655c`、`84cce3c`、`afe73c9`、`c6d85fb` 更新并校准验收记录。用户明确 Agnes 免费、不考虑费用，费用授权不再作为阻断；但真实 Image Probe 返回 401（“无效的令牌”），因此账户合同与 I2I/I2V 证据仍 `BLOCKED`。剩余阻断为公网 Reference origin、有效 Agnes Key、Video Drift 策略批准、真实 I2I/I2V Probe、10 Shot 正式证据与人工/运维签字。

最终状态不是 `ACCEPTED`。阻断来自正式证据前提，不反向否定已通过的 Graph、RLS、Adapter Contract、安全、UI 和 Mock E2E 自动化证据。

### 22.2 自动化命令记录

| 验证 | 结果 | 状态 |
| --- | --- | --- |
| PostgreSQL `alembic current` / `heads` | 均为 `20260803_0014 (head)` | `PASS` |
| Backend unit | `265 passed` | `PASS` |
| Backend PostgreSQL integration | `12 passed`，使用 `--fail-on-skip`，无 skip | `PASS` |
| Backend mypy | `Success: no issues found in 105 source files` | `PASS` |
| Ruff 本轮范围 | `app tests` 加迁移 `0013/0014`：`All checks passed` | `PASS` |
| Ruff 全历史迁移 | `82c320f` 后 `ruff check app tests alembic`：`All checks passed`（67 自动修复 + 91 E501 冻结豁免） | `PASS` |
| Frontend lint / typecheck | 均通过 | `PASS` |
| Frontend unit | 5 files、`15 passed` | `PASS` |
| Frontend production build | Vite build 通过 | `PASS` |
| Playwright smoke | `1 passed` | `PASS` |
| Playwright P0 mock | `1 passed`；10 Shot Brief/Plan、Connection、四层证据、九节点错误、审核、字幕返工、导出 | `PASS` |
| Agnes 真实鉴权 Probe | 2026-08-04（有效 Key）：`auth_models` → `passed / account_verified`，HTTP 200，Connection `verified` | `PASS` |
| Agnes 真实 T2I Probe | 2026-08-04：`image_t2i` → `passed / account_verified`，真实图片生成成功（remote task 有值） | `PASS` |
| §3.1 Gate（绑定候选 339569c） | `20 PASS / 0 FAIL / 4 BLOCKED`：Agent brief/plan 真实文本、10 Shot 物化、Canonical 真实 I2I 生成（`3.1.9` 不再是 fail-closed）；`3.1.10/3.1.11/3.1.18` BLOCKED 因 gate 不跑完整媒体管线 | `PASS`（栈验证） |
| 真实 10 Shot 图片链（proof，绑定 26fa8d6） | 10 keyframe + 10 face_review + prompt/subtitle/voice 全部真实 completed；真实 Face 双源评分：多个 shot `passed >= 0.60`（0.6556/0.6680/0.6865/0.7011），blocked 正确 fail-closed（0.5569/0.5928/0.0243）；`probe_content_hash` 显式绑定；face rework 机制真实重生成 keyframe | `PASS`（图片链）/ `BLOCKED`（video） |
| 真实 10 Shot 全链（冻结样本，绑定 a2977cc） | `run_frozen_sample_proof.py` 驱动：**4 个完整垂直链**（canonical->keyframe->face>=0.60->video->drift review）真实跑通，face passed 0.636/0.668/0.69/0.758；429 重试（Retry-After + ProviderOperation 幂等）生效；剩余 3 keyframe 内容过滤 400 + 3 face blocked（正确 fail-closed） | `PASS`（垂直链）/ `BLOCKED`（10 全量） |
| 真实 Video I2V | **已解除公网 origin 依赖**：2026-08-04 实测 Agnes `/v1/videos` 接受 base64 Data URI 首帧（真实视频任务 `queued->in_progress->completed` 端到端成功），计划 §6.4/§9.2 假设的公网 HTTPS 前置不成立。代码已改 I2V 走 `image_bytes` Data URI（`agnes.py`/`product_path.py`）。冻结样本驱动跑通垂直链：canonical->keyframe->face>=0.60->video(Data URI)->drift review（1 shot 完整，3 个 face passed 0.6144/0.8978/0.9049）；其余 9 shot 因 429 免费层限流 + keyframe 400 内容过滤 + face blocked 级联失败 | `PASS`（机制）/ `BLOCKED`（10 视频全量） |
| Agnes 真实 Image Probe（旧 Key） | 2026-08-04 早前：`/v1/models`、`image_t2i`、`image_i2i` 均 `401 / PROVIDER_AUTH_FAILED`（Connection 与 `.env` 存的是旧 Key）；已更新为有效 Key | 已解除 |
| Directory compliance | `Directory compliance OK` | `PASS` |
| `git diff --check` | 通过；仅已有 CRLF 转 LF warning | `PASS` |
| tracked 文本 Key-like scan | 命中文件数 `0` | `PASS` |

Playwright 使用 DOM、可访问名称、网络失败、console、page error 和 layout assertions；没有把 Mock 媒体当成真实 Agnes 证据。`tmp/p0-evidence/` 现有截图只检查文件存在、字节数和 SHA-256，未加载原始像素；这些历史证据均绑定其他 commit，不能用于当前工作树签字。

### 22.3 P0 Task 状态

| Task | 实现 | 自动化证据 | 真实/人工证据 | 当前状态 |
| --- | --- | --- | --- | --- |
| `P0-BASE-01` | 文档、ADR、目录登记已存在 | 目录合规通过 | 不需要 Provider | `PASS` |
| `P0-BASE-02` | Host/Profile 固定；Key 密文且只写不读 | tracked Key-like scan 为 0；Connection unit/E2E 通过 | 本机 Key 仍应在验收后轮换 | `PASS` |
| `P0-BASE-03` | 基线、命令和阻断项已写入本节 | 结果可复核 | 候选提交已形成；正式 Provider 证据待执行 | `PASS` |
| `P0-GRAPH-01` | GraphService 统一校验、幂等物化、发布一致性 | cycle/dangling/duplicate/hash 单测；PG 每版本 9/8、10 Shot 90/80 | 不需要 Provider | `PASS` |
| `P0-GRAPH-02` | DB required Edge、WorkerRuntime/Arq fail-closed | 依赖状态、上游失败、Artifact 缺失、取消后完成和 PG 产品路径通过 | 不需要 Provider | `PASS` |
| `P0-GRAPH-03` | Snapshot 输出 node/attempt/time/error/cost/Artifact/dependencies | API、前端类型和 P0 E2E 九节点表通过 | 人工现场尚未签字 | `PASS` |
| `P0-AGNES-01` | `agnes_cn_v1` I2I/I2V、身份和请求摘要已实现 | Contract/unit 通过，无 `/images/edits` 正式分支 | 本账户脱敏响应 Fixture 未生成 | `PASS`（实现）/ `BLOCKED`（账户合同） |
| `P0-AGNES-02` | 单 POST、未知提交、remote ID 持久化、恢复续查已实现 | worker restart 测试证明同一 ProviderOperation、不二次 create | 未做付费真实重启演练 | `PASS`（实现）/ `BLOCKED`（真实演练） |
| `P0-AGNES-03` | 四层 capability/model 状态机和 UI 已实现 | Connection unit + P0 E2E 独立状态断言通过 | I2I/I2V 尚未 `account_verified/quality_gated` | `PASS`（实现）/ `BLOCKED`（真实证据） |
| `P0-FACE-01` | Canonical/probe 显式 Artifact/hash/attempt 血缘 | 两源、跨 Shot、hash/availability fail-closed 测试通过 | 当前候选真实 I2I Artifact 未生成 | `PASS`（实现）/ `BLOCKED`（真实链） |
| `P0-FACE-02` | 固定 0.60、`needs_human`、有限返工 | Face policy、返工和审核 Gate 测试通过 | 当前候选没有真实 `score >= 0.60` | `PASS`（实现）/ `BLOCKED`（真实链） |
| `P0-VIDEO-01` | MP4 确定性抽帧、scene change、脱敏 evidence 已实现；离线校准 harness（`scripts/calibrate_video_drift.py`）已建并在合成样本上验证（5 帧评分 + 分布输出） | Video Drift unit 通过，不保存 embedding | 阈值和 approval ID 未校准/批准；需真实 Video 样本（依赖公网 origin）形成权威分布 | `BLOCKED` |
| `P0-UI-01` | Connection、轮换、Probe、四层状态和项目绑定 UI 已实现 | lint/typecheck/unit/P0 E2E 通过 | 真实账户 UI 验收未做 | `PASS`（实现）/ `BLOCKED`（人工） |
| `P0-UI-02` | 9 节点 attempt/依赖/时间/费用/Artifact/错误建议已实现 | P0 E2E 覆盖 Provider pending、上游失败、Drift、预算等 | 真实运行现场未签字 | `PASS`（实现）/ `BLOCKED`（人工） |
| `P0-E2E-01` | 旧 `api-status` 假设已删除，Mock 主业务流重写 | smoke 和 P0 mock 均通过，10 Shot 审核/返工/导出已执行 | Real Provider E2E 被明确分离且未执行 | `PASS`（Mock）/ `BLOCKED`（Real） |

### 22.4 阶段 Gate

| 阶段 | 实现/自动化 | 正式验收状态 | 说明 |
| --- | --- | --- | --- |
| 阶段 0 基线 | `PASS` | `PASS` | 已分类当前工作树和历史质量债务 |
| 阶段 1 Graph | `PASS` | `PASS` | 初始脏 Graph/运行时工作主要完成本阶段 |
| 阶段 2 Agnes Contract | `PASS` | `BLOCKED` | 无网络 Contract 通过；缺当前账户脱敏响应 Fixture |
| 阶段 3 Connection/Reference | `PASS` | `BLOCKED` | 六表 RLS、HEAD/GET/token/security 自动化通过；缺公网 HTTPS origin 真实拉取 |
| 阶段 4 单 Shot 人物链 | 部分 `PASS` | `BLOCKED` | 缺真实 I2I/I2V、费用授权、Drift 策略和完整 SHA-256 血缘 |
| 阶段 5 UI/恢复 | `PASS` | `BLOCKED` | Mock E2E 和 DB 恢复通过；未进行真实账户人工验收 |
| 阶段 6 10 Shot 正式证据 | 未执行 | `BLOCKED` | 候选提交已形成，但历史报告不属于当前候选，真实 10 Shot 与运维演练未完成 |

### 22.5 正式阻断清单

1. ~~**候选源不成立**~~：已解除。工作树 63 条变更已形成候选 commit `cee5306`，并叠加 `9191b6a`（Canonical 审计父级）、`82c320f`（全历史 Ruff 清理）及后续验收记录提交。`git status` 干净；下一步按候选提交构建 Compose 并核对 `/health.source_commit`。
2. ~~**公网 Reference 不成立**~~：已解除。2026-08-04 实测 Agnes China `/v1/videos` 接受 base64 Data URI 首帧（真实视频任务端到端完成），I2V 不再需要 `REFERENCE_PUBLIC_BASE_URL`。代码 `agnes.py`/`product_path.py` 已改 Data URI 路径。剩余 video 全量瓶颈为免费层 429 限流（并发视频）与 keyframe 400 内容过滤，非公网 origin。
3. ~~**Agnes Key 未通过鉴权**~~：已解除。2026-08-04 更新为有效 Key 后，`auth_models` 与 `image_t2i` 均 `passed / account_verified`（HTTP 200、真实图片生成成功）；`AGNES_API_KEY`（`.env`）与 Connection 凭证均已更新为有效 Key。
4. **真实 Provider 证据大幅完成**：垂直链（canonical->keyframe->face>=0.60->video(Data URI)->drift review）4 条完整真实跑通（face passed 0.636/0.668/0.69/0.758）；429 重试与 ProviderOperation 幂等已实现。剩 10 全量：3 keyframe 内容过滤 400（需改样本文案）+ 3 face blocked（正确 fail-closed，需返工）。
5. **Video Drift 未批准**：实现保持 `PROBE_REQUIRED`，固定样本分布、阈值和 approval ID 尚未批准。
6. ~~**Canonical 审计父级缺口**~~：已解除。`9191b6a` 引入 `create_canonical_generation_run`（最小单节点 canonical graph + running NodeRun 作为审计父级）、`record_canonical_provider_operation`（ProviderOperation 挂 `node_run_id`），Artifact 经 `produced_by_run_id` 回链 Run；XOR 约束满足（单测 `test_canonical_generation_has_audit_parent_run` 断言 `node_run_id` 非空、`agent_run_id` 为空）。
7. **当前候选 10 Shot 缺失**：没有当前 commit 的 10 Shot x 9 Node、真实 Face/Drift/Continuity、个人审核、字幕局部返工和四项交付证明。
8. **人工与运维未签字**：备份恢复、Key 轮换、Outbox/死信、取消、SSE、冷存储演练和验收人/费用摘要均未记录。
9. ~~**全历史 Ruff 未清零**~~：已解除。`82c320f` 清理 136 条旧 migration/`alembic/env.py` 风格问题：67 条自动修复（UP007/UP035/I001），91 条 E501 对冻结迁移版本 per-file-ignores（SQL/revision 逻辑未动，`alembic heads` 与迁移 PG 测试验证）。`ruff check app tests alembic` 现为 `All checks passed`。

解除阻断的顺序固定为：形成干净候选 commit（已完成）-> 配置公网 HTTPS Reference origin -> 明确费用预算 -> 逐 capability 真实 Probe 并保存脱敏 Fixture -> 批准 Video Drift 策略 -> 修复 Canonical 审计父级（已完成）-> 单 Shot 真实链 -> 10 Shot formal/gate/ops -> 人工验收签字。任何一步都不能用历史证据、Mock 或降低阈值替代。
