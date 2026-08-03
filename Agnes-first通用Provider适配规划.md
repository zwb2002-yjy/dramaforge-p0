# DramaForge Agnes-first 通用 Provider 适配规划

> 文档状态：待评审
>
> 核验日期：2026-08-03
>
> 本文范围：基于可访问的官方文档规划 Provider 适配；本轮不修改业务代码，不把内部业务概念伪装成厂商 API 参数。

## 1. 结论先行

1. **Agnes Image 2.0/2.1 官方明确支持图生图、图像编辑和多图合成。** 之前对 `/v1/images/edits` 发 multipart 请求得到 HTTP 500/503，只能证明请求使用了错误合同，不能证明 Agnes 不支持参考图。
2. Agnes Image 2.1 的官方图生图合同是 `POST /v1/images/generations`，JSON 请求中的参考图放在 `extra_body.image[]`，支持公网 URL 或 Data URI。
3. **Agnes Video V2.0 官方明确支持图生视频和关键帧动画。** 图生视频使用顶层 `image`；关键帧动画使用 `extra_body.image[]` 和 `extra_body.mode: "keyframes"`。
4. 当前 DramaForge 的图片 Adapter 对有 canonical 的请求调用了错误的 `/images/edits`；视频 Adapter 只发送 `model + prompt`。这两项是当前 Adapter 实现缺口，不是模型能力缺口。
5. 官方“支持参考图”“帧间视觉一致性”不等于 DramaForge 的人物一致性已达标。正式链路仍须经过账户实测和 InsightFace `>= 0.60` Gate，失败时关闭链路，不能回退为纯文字生成。
6. 通用层应统一**业务意图、参考资产用途和执行结果**，不应要求各厂商接受同一套 HTTP JSON。每个 Adapter 负责把内部意图翻译成厂商官方 Wire Contract。
7. 当前基座已有执行、审计、BYOK、canonical 和人脸 Gate 等可复用组件，但 Agnes 人物一致性闭环尚未完成，不能宣称 P0 Provider 链路已上线。

## 2. 官方文档核验结果

### 2.1 Agnes Image 2.1 Flash

官方文档明确列出文生图、图生图、多图合成，以及基于输入图像的转换、重绘和风格化编辑。

官方端点：

```text
POST https://api.agnes-ai.cn/v1/images/generations
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

官方图生图示例所表达的合同：

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

已确认的约束：

- 图生图和多图合成的输入图像放在 `extra_body.image[]`。
- 输入支持公网图片 URL 或 Data URI Base64。
- `response_format` 放在 `extra_body`，不放请求体顶层。
- 不需要发送 `tags: ["img2img"]`。
- 2.1 文档支持常规尺寸，并给出 `1K`、`2K` 等尺寸及比例方式；具体组合须进入模型级 Contract Test，不能跨模型假设。
- 文档参数表中有一处将 `image` 展示为顶层字段，但“重要说明”、请求示例、故障排查和接入清单一致使用 `extra_body.image`。本规划以反复出现的 `extra_body.image` 为当前合同，并用真实 Contract Test 锁定行为。

Agnes Image 2.0 官方文档也明确支持文生图、图生图、多图合成和图像编辑。首个实现以 2.1 为主，2.0 作为独立模型绑定验证，不默认继承 2.1 的已验证状态。

### 2.2 Agnes Video V2.0

官方端点：

```text
POST https://api.agnes-ai.cn/v1/videos
```

图生视频官方合同：

```json
{
  "model": "agnes-video-v2.0",
  "prompt": "The character turns toward camera, stable facial appearance",
  "image": "https://short-lived.example/reference.png",
  "num_frames": 121,
  "frame_rate": 24
}
```

关键帧动画官方合同：

```json
{
  "model": "agnes-video-v2.0",
  "prompt": "A controlled transition between the supplied keyframes",
  "extra_body": {
    "image": [
      "https://short-lived.example/first.png",
      "https://short-lived.example/last.png"
    ],
    "mode": "keyframes"
  },
  "num_frames": 121,
  "frame_rate": 24
}
```

查询结果：

```text
推荐：GET https://api.agnes-ai.cn/agnesapi?video_id=<VIDEO_ID>
兼容：GET https://api.agnes-ai.cn/v1/videos/<TASK_ID>
```

已确认的约束：

- 图生视频的 `image` 必须是公网可访问 URL；Agnes 视频文档未声明这里支持 Data URI。
- `num_frames <= 441`，并满足 `8n + 1`。
- `frame_rate` 范围为 1 至 60。
- 创建响应可同时包含 `task_id` 和 `video_id`；新接入优先保存并使用 `video_id`，同时把两者当作不透明 ID。
- 官方声明支持图生视频、关键帧动画和帧间视觉一致性，但没有给出 DramaForge 的人物相似度阈值，因此仍需产品 Gate。

### 2.3 Agnes Host 与协议边界

当前代码默认 Base URL：

```text
https://apihub.agnes-ai.com/v1
```

本次核验到的 Agnes 中国站官方合同：

```text
https://api.agnes-ai.cn
```

不能仅因为两者模型 ID 相同，就假设路径、扩展字段、查询方式和能力完全一致。实施时必须：

- Base URL 属于 Workspace Connection 配置，不再只来自进程级 Settings。
- Connection 绑定明确的 `protocol_profile` 和版本。
- `agnes_cn_v1` 按上述官方合同实现。
- 现有 `apihub.agnes-ai.com` 作为 `agnes_apihub_legacy` 独立验证；未通过 Probe 前不得继承中国站能力。
- 用户修改 Base URL 后，将验证状态重置为未验证，不能沿用旧 Host 的能力证据。

### 2.4 MiniMax / 海螺对通用设计的验证

MiniMax 官方文档证明不同 Provider 的参考输入合同确实不同：

- 图片生成 `POST /v1/image_generation` 的 `image-01` 支持 `subject_reference.image_file`，输入可为公网 URL 或 Data URL。
- `S2V-01` 视频生成支持 `subject_reference.image`，当前文档声明单个主体。
- H3 V2 使用 `POST /v2/video_generation`，通过 `content[]` 表达多模态输入。
- H3 V2 官方角色包括 `first_frame`、`last_frame`、`reference_image`、`reference_video`、`reference_audio`。
- H3 V2 的首尾帧工作流和多模态参考工作流互斥，Adapter 必须在请求前校验，不能把所有参考资产无条件塞进一个请求。

这说明通用层不能定义一个所谓“所有 Provider 都接受”的 JSON；它只能定义内部意图，由 Agnes、MiniMax 等 Adapter 分别翻译。

### 2.5 Seedance 与可灵的当前证据边界

Seedance 2.0 官方模型页明确声明：支持文字、图片、音频、视频四种模态输入，并提供多模态内容参考和编辑能力。火山方舟官方文档库也有视频生成 API 页面，但本次通过公开页面未稳定取得可用于实现的完整 Seedance Wire Schema。因此：

- 可将“存在多模态参考能力”记为官方已声明。
- 暂不能把具体字段、角色、上传方式记为已核验合同。
- 实现 Seedance Adapter 前，必须从火山方舟官方 API 页面或已开通账户控制台取得请求/响应示例并固化 Contract Fixture。

可灵官方开放平台确认提供 Video Generation、Image Generation，并公开 image-to-video/character animation 能力入口；官方 API Reference 页面在当前环境主要由前端动态加载，未稳定提取出完整字段。因此：

- 可记录能力类别已由官方平台确认。
- Wire Contract 暂记为待取得，不使用第三方聚合站或社区示例猜字段。
- 获得官方控制台文档后，再新增 `kling_*` protocol profile 和 Contract Test。

## 3. 对此前 500/503 结论的纠正

此前请求是：

```text
POST /v1/images/edits
Content-Type: multipart/form-data
```

而 Agnes Image 2.1 官方合同是：

```text
POST /v1/images/generations
Content-Type: application/json
extra_body.image = [URL 或 Data URI]
```

所以原证据应重新标记为：

```text
invalid_contract_probe / legacy_endpoint_probe
```

原证据不能用于以下结论：

- Agnes Image 2.0/2.1 不支持图生图。
- Agnes 不支持参考图。
- Agnes 无法用于人物一致性链路。

正确的新证据顺序是：

1. 按官方合同发送图生图请求。
2. 记录 Host、protocol profile、模型 ID、请求字段摘要和 canonical SHA-256。
3. 成功返回并完成产物入库后，标记当前账户的合同验证通过。
4. 对产物执行 InsightFace Gate；只有 `>= 0.60` 才标记该模型绑定的质量 Gate 通过。

## 4. 当前代码差距

### 4.1 `backend/app/providers/agnes.py`

- `create_image()` 在存在 canonical 时切换到 `/images/edits` multipart，与 Agnes 官方合同不符。
- `create_video()` 当前只发送 `model + prompt`，没有传 `image`、关键帧、`num_frames` 或 `frame_rate`。
- 视频轮询固定使用 `/videos/{id}`，没有实现官方推荐的 `/agnesapi?video_id=...` profile 行为。
- 图片创建和视频创建最多重试 8 次。官方文档未确认创建接口支持幂等键，自动重试 POST 可能重复计费或产生重复任务；创建重试策略必须收紧，轮询重试可保留。
- `AgnesImageAdapter.provider = "flux"`、`AgnesVideoAdapter.provider = "kling"`，导致产品槽位和真实 Provider 身份混淆。

### 4.2 Provider 选择与执行合同

- `backend/app/providers/base.py` 只有弱类型 `create(dict)`，无法在进入 Adapter 前表达或校验参考资产角色。
- `backend/app/execution/product_path.py` 仍按 Flux/Kling 槽位选择 Adapter，并用类名和 Provider 名猜实际模型。
- keyframe 会传 `canonical_image_bytes`，但 video/video_review 不会传已经批准的关键帧引用。
- `ProviderOperation` 已能记录 `actual_provider`、`actual_model`、fingerprint、request/response summary、状态和成本，可复用为首期审计，不必为了规划一次性重构全部审计表。

### 4.3 Workspace 配置

- 当前 BYOK 已具备 Workspace 隔离、加密和 RLS，是可复用基座。
- 当前凭据按 `workspace_id + provider` 唯一，只能保存一个 Agnes Key，不支持同一 Workspace 的多个 Host、账户或区域 Connection。
- Base URL、模型 ID、enabled 仍来自全局 Settings。
- Credentials API 只接受 `text|agnes`，没有 Connection、模型绑定、能力验证和项目用途绑定。
- `UserProjectPreference` 用于体验模式，不应承载 Provider/模型路由。

## 5. 设计原则

### 5.1 统一业务意图，不统一 Wire Schema

DramaForge 内部表达“要生成什么、为什么使用这个参考资产”，Adapter 表达“厂商具体接受什么字段”。

内部概念示例：

```text
资产业务用途：character_identity
生成阶段用途：canonical_image / keyframe / video_first_frame
Provider 传输角色：reference_image / first_frame / keyframe
```

其中 `character_identity` 是 DramaForge 业务语义，不是 Agnes API 字段。Agnes Adapter 可将该资产映射到 `extra_body.image[]`；MiniMax Adapter 可映射到 `subject_reference` 或 `content[].role`。两者不得互相冒充。

### 5.2 能力属于 Connection + Protocol Profile + Model

能力不能只挂在 `provider=agnes` 上。验证键至少包括：

```text
connection_id + protocol_profile + model_id + capability + account
```

同一模型在不同 Host、区域、账户权限或协议版本下，运行能力可能不同。

### 5.3 人物一致性是执行链，不是模型布尔值

Provider 支持参考图只是必要条件。DramaForge 的一致性由以下组合实现：

- canonical 角色资产及版本锁定；
- 正确的 Provider 参考输入；
- prompt 中的角色/镜头约束；
- 生成后的人脸相似度 Gate；
- 只把 Gate 通过的关键帧送入视频模型；
- 视频关键采样帧的漂移复核；
- 完整的 reference 和输出证据链。

### 5.4 正式链路失败关闭

- 主角镜头缺 canonical：不调 Provider。
- 模型绑定未完成账户验证：不进入正式人物链。
- Provider 不支持所需参考角色：不回退纯文字生成。
- keyframe 人脸分数低于 `0.60`：不进入视频生成。
- 视频漂移超过阈值：标记失败或人工复核，不伪装成功。

## 6. 内部请求模型（业务合同，不是厂商字段）

首期不再把任意 `dict` 直接从执行层送入 Provider。建议定义两个最小的类型化意图；字段名可在实施 PR 中按仓库命名规范调整，但语义必须保持。

### 6.1 ImageGenerationIntent

```text
purpose                 canonical_image | shot_keyframe | auxiliary_image
prompt                  剧情和画面意图
output_spec             比例、分辨率、格式
reference_assets[]      受控 Artifact 引用，不直接携带任意远程 URL
reference_assets[].use  character_identity | composition | style
reference_assets[].id   DramaForge Artifact ID
```

首期正式主角 keyframe 只要求一个 `character_identity` canonical。多人物、多参考图的角色对应关系放到 P1，不因 Agnes 支持多图就提前宣称已解决多人物绑定。

### 6.2 VideoGenerationIntent

```text
purpose                  shot_video
prompt                   动作、镜头和场景意图
output_spec              帧数、帧率、比例、分辨率
reference_assets[]       已批准 Artifact 引用
reference_assets[].role  first_frame | last_frame | keyframe | reference_image
```

这些 role 仅选取已在 Agnes/MiniMax 官方合同中出现或能明确映射的最小语义。后续 `reference_video`、`reference_audio` 在接入 H3/Seedance 时扩展，不让 Agnes Adapter接收其无法处理的角色。

### 6.3 Adapter 返回值

规范化返回值至少包含：

```text
actual_provider
actual_model
protocol_profile
remote_task_id
remote_secondary_id
status
artifact_result
request_fingerprint
reference_fingerprints[]
```

`remote_secondary_id` 用于同时保留 Agnes 的 `task_id`/`video_id` 等厂商 ID。执行层不得再通过 Adapter 类名猜模型。

## 7. Agnes 官方合同映射

| DramaForge 意图 | Agnes Image/Video 字段 | 说明 |
| --- | --- | --- |
| 图片 prompt | `prompt` | 原样表达创作意图；策略改写须形成独立审计 attempt |
| 图片模型 | `model` | 来自已验证的模型绑定 |
| character identity canonical | `extra_body.image[]` | Agnes 图片官方图生图合同；优先 Data URI，避免公开 canonical |
| 图片输出格式 | `extra_body.response_format` | 不放顶层 |
| 图片尺寸/比例 | `size`/文档允许的比例字段 | 每个模型 profile 通过 Contract Test 决定允许组合 |
| 视频首帧 | 顶层 `image` | 必须转换为短时公网 HTTPS URL |
| 视频关键帧数组 | `extra_body.image[]` | 同时发送 `extra_body.mode: "keyframes"` |
| 视频帧数 | `num_frames` | Adapter 校验 `<= 441` 且 `8n + 1` |
| 视频帧率 | `frame_rate` | Adapter 校验 1 至 60 |
| 视频轮询 | `/agnesapi?video_id=...` | `agnes_cn_v1` 首选；兼容路径按响应 ID 和 Probe 结果决定 |

不允许的映射：

- 不再把 Agnes canonical 请求映射到 `/images/edits`。
- 不把 `character_identity` 当作 Agnes Wire 字段发送。
- 不把所有图片统一塞到视频顶层 `image`。
- 不因 `/v1/models` 返回模型 ID 就自动标记图生图/图生视频已验证。

## 8. 用户自由配置的数据模型

以下是 DramaForge 内部持久化规划，不是 Agnes 官方字段。

### 8.1 ProviderConnection

Workspace 级连接，表示一个真实账户和 API Host：

```text
id
workspace_id
provider_type            agnes | minimax | kling | volcengine
display_name
base_url
protocol_profile         agnes_cn_v1 | agnes_apihub_legacy | ...
credential_id
enabled
config_json              仅保存非敏感、profile 允许的参数
verification_status
verified_at
created_by / updated_by
```

规则：

- 普通用户可以配置显示名、官方/企业代理 Base URL、Key 和启用状态。
- 普通用户不能填写任意 endpoint path 或任意 JSON 模板；路径和 Wire Schema 固定在经过代码审查的 protocol profile 中。
- Base URL 必须使用 HTTPS；本地开发例外由环境开关控制。
- 禁止 localhost、环回、链路本地、私网、云元数据地址和 DNS rebinding；企业私有代理如确有需要，必须走管理员 allowlist。
- 修改 Base URL、profile 或 credential 后，清空旧验证状态。

### 8.2 ProviderModelBinding

Connection 下的真实模型绑定：

```text
id
connection_id
media_type               image | video | text | voice
model_id
purpose                  canonical_image | keyframe | video
enabled
documented_capabilities
verified_capabilities
verification_evidence
quality_gate_evidence
```

模型 ID 允许用户从 Probe 返回的模型列表选择，也允许管理员录入官方文档提供但列表暂未返回的 ID；后一种状态必须保持“未验证”，不能直接用于正式链。

### 8.3 ProjectProviderBinding

项目级用途路由：

```text
project_id
purpose                  canonical_image | keyframe | video | text | voice
model_binding_id
fallback_policy          正式人物链首期固定为 none
```

这样用户可以在同一个 Workspace 中：

- 项目 A 使用 Agnes 图片 + Agnes 视频；
- 项目 B 使用 MiniMax 图片 + 海螺视频；
- 后续只替换某一用途，不改执行图和业务对象。

### 8.4 凭据迁移

现有 `EncryptedProviderCredential(workspace_id, provider)` 先保留兼容读取，再迁移到 Connection 引用的加密凭据：

1. 为现有 Agnes Workspace 创建默认 legacy Connection。
2. 将现有密文关联到该 Connection，不解密回传前端。
3. 后台 Settings 作为部署级兜底只用于管理员预置，不覆盖 Workspace 显式绑定。
4. 新写入只走 Connection API；兼容期结束后移除按 provider 唯一的限制。

## 9. Reference Artifact 输送

### 9.1 Agnes 图片

Agnes 图片官方支持 Data URI。canonical 图像由服务端读取受控 Artifact 后编码到请求中：

- 不把本地 Windows 路径发给 Provider。
- 不把长期公开对象存储 URL 发给 Provider。
- 校验 MIME、像素、文件大小和 Artifact 所属 Workspace。
- 审计只记录 Artifact ID、SHA-256、MIME、大小和 `transport=data_uri`，不记录完整 Base64。

### 9.2 Agnes 视频

Agnes 视频官方要求公网 URL，需要新增 Reference Artifact Delivery：

- 生成短时签名 HTTPS URL，只允许读取指定 Artifact。
- 允许 Provider 常见的 `GET`/`HEAD`，不做只读一次后立刻失效，以免厂商预检和正式拉取分两次导致失败。
- TTL 建议默认 60 分钟，并覆盖排队和 Provider 拉取延迟；最终值需真实 Probe 验证。
- 限定 MIME、最大字节数、响应头和下载速率；禁止目录遍历和任意对象访问。
- Provider 请求完成后可提前吊销，超时自动失效。
- 日志和 `ProviderOperation` 不保存完整签名 URL，只记录 Artifact ID、SHA-256、transport 和 URL token 指纹。

Provider 产物 URL 也必须立即下载、校验并入 DramaForge 对象存储，不能把厂商临时 URL 当作永久 Artifact。

## 10. 能力证据状态机

每项能力分四层，不再使用单一 `supports_reference=true`：

| 层级 | 含义 | Agnes 当前状态 |
| --- | --- | --- |
| `documented` | 官方文档明确声明并给出合同 | Image 2.0/2.1 I2I、Video V2.0 I2V/keyframes 已满足 |
| `contract_tested` | Adapter 的请求/响应 Fixture 与官方合同一致 | 当前错误 `/images/edits` 实现未满足 |
| `account_verified` | 指定 Connection/账户/模型真实请求成功 | 需按新合同重跑 |
| `quality_gated` | 真实产物通过 DramaForge 质量阈值 | 需重跑 InsightFace `>= 0.60` 和视频漂移 Gate |

正式主角链的最低条件：

```text
documented
AND contract_tested
AND account_verified
AND quality_gated
```

验证证据至少记录：

```text
connection_id / profile / host
model_id / capability
probe_version / tested_at
request schema fingerprint
reference artifact SHA-256
HTTP status / provider request ID
result artifact SHA-256
face score / threshold / gate version
```

不记录 API Key、完整 Data URI、完整签名 URL或厂商可能返回的敏感原始请求。

## 11. 人物一致性正式执行链

首期单主角链：

```text
锁定 Canonical Character Artifact
  -> Agnes Image 2.1 I2I（extra_body.image，Data URI）
  -> Keyframe Artifact 入库
  -> 人脸检测与 InsightFace 相似度 >= 0.60
  -> Approved Keyframe Artifact
  -> 生成短时签名 HTTPS URL
  -> Agnes Video V2.0 I2V（顶层 image）
  -> Video Artifact 入库
  -> 抽取起始/中段/结束及镜头变化采样帧
  -> 人脸漂移 Gate
  -> 通过、失败或人工复核
```

执行要求：

- 每个主角 keyframe 必须引用具体 canonical 版本，角色更新后不隐式替换旧运行的 canonical。
- keyframe Gate 未通过，不得发布给视频 Provider。
- 视频只使用 `ApprovedKeyframe`，不能从任意用户 URL直接发起。
- 正式证据记录 canonical、keyframe、video 三段 SHA-256 和 lineage。
- Provider 的“视觉一致性”声明只作为选择模型的依据，不替代 Gate。
- 自动重试必须生成新的 `ProviderOperation attempt`；不得覆盖失败证据。
- 未有官方幂等合同前，创建请求默认不做多次自动 POST。网络结果不确定时标记 `unknown_submission` 并先查任务/人工确认，避免重复计费。

P1 多人物链再增加：

- 每个出场角色独立 canonical embedding。
- 每张脸与预期角色做一对一匹配，防止两个人都匹配到同一张脸。
- 检测漏脸、错脸、角色互换和额外人脸。
- 对不支持多人物参考绑定的模型，拒绝该用途或拆分工作流，不以 prompt 假装能力存在。

## 12. 分阶段实施

### 阶段 A：纠正 Agnes 合同与 Adapter 身份（P0，2-3 个工程日）

任务：

- 为 Agnes 中国站建立 `agnes_cn_v1` protocol profile。
- 图片 canonical 改为 `/v1/images/generations` JSON + `extra_body.image[]`。
- 输出格式放入 `extra_body.response_format`。
- 视频 Intent 支持 `first_frame` 和 `keyframe`，映射官方字段。
- 视频轮询优先实现 `video_id` 查询方式。
- 将 Adapter 的 `provider` 改为真实 `agnes`；移除通过类名猜模型的逻辑。
- 收紧创建 POST 的重试策略，区分创建、轮询和下载重试。
- 添加无网络的 Request Contract 单测，断言路径、Content-Type、JSON 位置、日志脱敏和失败关闭。

验收：

- 测试可证明 canonical 请求不再访问 `/images/edits`。
- 测试可证明视频首帧实际进入 Agnes 官方 `image` 字段。
- `ProviderOperation` 记录真实 Provider、模型、profile 和 reference fingerprint。
- 缺参考输入时，正式主角任务在 Provider 调用前失败。

### 阶段 B：Connection/Model/Project Binding（P0，3-5 个工程日）

任务：

- 新增 Workspace Connection、模型绑定和项目用途绑定数据表、RLS、服务与 API。
- 凭据继续加密保存，支持同一 Workspace 多个 Agnes Connection。
- Base URL/profile 变更触发能力验证失效。
- Adapter Registry 按 `protocol_profile` 解析，不按 Flux/Kling 槽位解析。
- 迁移现有 Settings/BYOK，保留一段兼容期。

验收：

- 两个 Workspace 不能看到或使用对方 Connection、模型或 Key。
- 同一 Workspace 可配置中国站和 legacy Hub 两个 Agnes Connection，验证状态互不继承。
- 项目可分别绑定 keyframe/video 模型。
- API 永不回传明文 Key。

### 阶段 C：Reference Artifact Delivery（P0，2-3 个工程日）

任务：

- 图片 Data URI transport。
- 视频短时签名 HTTPS transport。
- URL 脱敏、TTL、MIME/大小限制、Workspace 归属校验和 SSRF 防护。
- Provider 结果立即入库并生成 Artifact lineage。

验收：

- Agnes 能从签名 URL完成 `HEAD/GET` 并创建 I2V 任务。
- 过期 URL不可访问，其他 Artifact ID不可枚举。
- 数据库和普通日志中没有 Base64、API Key 或完整签名 URL。

### 阶段 D：真实 Probe 与人物 Gate 证据（P0，2-4 个工程日，Provider 正常可用前提）

Probe 顺序：

1. Connection 鉴权和模型可见性。
2. Agnes Image 2.1 文生图 smoke test。
3. Agnes Image 2.1 canonical I2I test。
4. keyframe InsightFace `>= 0.60`。
5. Agnes Video V2.0 first-frame I2V test。
6. 视频状态轮询和产物下载。
7. 视频采样帧人物漂移 Gate。

验收：

- 每项能力分别得到 `account_verified` 证据，不因一个端点成功而推断其他端点。
- 至少一条固定 canonical 的正式链完整通过，产物和结构化证据可重放核验。
- 任何一步失败均保持 fail-closed，且失败原因区分合同、账户、Provider 服务、内容策略和质量 Gate。

### 阶段 E：用户配置界面与上线加固（P0 上线，3-5 个工程日）

任务：

- Workspace Provider Connection 管理界面。
- Key 只写不读；Connection Test 显示结构化结果。
- 模型和能力状态显示 `官方声明/合同测试/账户验证/质量通过`，不显示模糊“已支持”。
- 项目级 keyframe/video 用途绑定。
- 配额、超时、熔断、成本、告警和操作审计。
- 正式环境集成测试与回滚演练。

验收：

- 用户无需修改环境变量即可配置和验证 Agnes。
- 未通过质量 Gate 的模型不可被项目绑定为正式人物链。
- Provider 5xx 不触发纯文字 fallback，不产生伪成功关键帧。

### P1：扩展其他 Provider 与多人物一致性

优先顺序：

1. MiniMax Image `subject_reference` 与 H3/海螺视频，因官方 Wire Contract 已较完整。
2. Seedance，取得火山方舟账户级官方请求合同后实施。
3. 可灵，取得官方控制台/API Reference 完整字段后实施。
4. 多人物匹配、角色互换检测、跨镜头漂移趋势和自动选帧。

每新增一个 Provider 的固定流程：

```text
官方合同归档
-> protocol profile
-> request/response Contract Fixture
-> 账户 Probe
-> 质量 Gate
-> 项目绑定开放
```

## 13. 当前完成度与工期判断

按“Agnes 可由用户配置并完成正式人物一致性链”这个交付目标评估：

| 能力包 | 当前状态 |
| --- | --- |
| 执行图、任务运行、ProviderOperation 审计 | 已有可复用基座 |
| Workspace BYOK 加密与隔离 | 已有单 Provider Key 基座，需 Connection 化 |
| canonical 资产与 keyframe 人脸 Gate | 已有基座，需接到正确 Agnes I2I 合同 |
| Agnes 图片参考输入 | 官方能力已确认，当前代码合同错误 |
| Agnes 视频参考输入 | 官方能力已确认，当前代码尚未传引用 |
| 短时 Reference URL | 尚未完成 |
| 账户级能力 Probe 与正式 `0.60` 证据 | 尚未完成 |
| 用户自由配置 Connection/Model/Project | 尚未完成 |

因此不能用“模型不支持”否定整个基座，也不能把现状称为人物一致性 P0 已完成。已有基座解决了执行、审计、安全和 Gate 的一部分；真正决定产品特点的参考输入闭环仍是当前 P0 主路径。

单工程师、现有测试基座可用、Provider 服务正常的前提下：

- 阶段 A-D：约 9-15 个工程日，可形成 Agnes 技术闭环和正式证据。
- 加上阶段 E：总计约 12-20 个工程日，可达到受控上线条件。
- Provider 审核、账户权限、服务 5xx、网络备案/域名和外部质量调参不计入纯开发工期。
- 每个后续 Provider 在取得完整官方合同后，基础接入约 3-7 个工程日；质量调参与正式 Gate 证据另计。

## 14. 测试矩阵

### 14.1 Contract 单测

- Agnes I2I 路径、JSON 和 `extra_body.image`。
- `response_format` 层级。
- Agnes I2V 顶层 `image`。
- Agnes keyframes 的 `extra_body.image/mode`。
- `num_frames` 的 `8n + 1` 校验。
- `video_id` 和 `task_id` 解析。
- 不支持的 reference role 在发送前失败。
- 请求摘要不包含 Base64、Key 或签名 URL。

### 14.2 集成测试

- Workspace/RLS 隔离。
- Connection、模型绑定和项目路由。
- canonical -> keyframe -> Gate -> video lineage。
- Provider 400/401/403/429/500/503 分类。
- 创建请求网络结果不确定时不盲目重复创建。
- Provider 临时产物 URL下载失败、过期和 MIME 不符。

### 14.3 正式 Provider 证据

- 固定 canonical、prompt、模型和 profile。
- 保存结构化请求摘要、响应摘要、SHA-256、耗时和成本。
- keyframe 人脸分数必须 `>= 0.60`。
- 视频抽样策略和漂移阈值版本化。
- 正式证据不使用 Fake、不使用纯文字 fallback、不使用错误 endpoint。

## 15. 迁移、兼容与回滚

- 第一步只新增 profile 和新配置读取，不删除现有 Settings。
- 现有 `get_flux_adapter()`/`get_kling_adapter()` 调用点先由 Registry 兼容，随后移除误导命名。
- 数据迁移为每个已有 Agnes BYOK 创建默认 legacy Connection；默认不把旧 500/503 证据迁移为能力失败。
- 新旧路径并行期，`ProviderOperation` 必须写入 profile，便于区分证据来源。
- 回滚时可关闭新 Connection 路由并恢复旧文本/非人物任务，但正式人物任务继续 fail-closed，不能回滚到纯文字关键帧。

## 16. 安全与运维要求

- API Key 只写不读、信封加密、按 Workspace 和 Connection 授权。
- Base URL 防 SSRF、DNS rebinding 和重定向到私网；重定向目标也要重新校验。
- 出站请求限制 Host、协议、端口、Content-Type、响应大小和超时。
- Provider 错误消息先结构化和脱敏，再写审计；不直接保存可能含签名 URL 的完整响应。
- 创建、轮询、下载分别配置超时和重试，不共用一个“重试 8 次”策略。
- 费用按 `ProviderOperation` attempt 记录；结果不确定也应标记潜在费用。
- Connection Probe 设置频率限制，避免用户反复触发付费生成。
- profile 和能力证据版本化；官方合同变化后可使旧验证自动过期。

## 17. 需要产品/技术负责人决策

以下决策不影响先完成阶段 A，但会影响阶段 B-E。括号内为建议默认值。

1. **首个正式 Host**：优先按官方中国站 `api.agnes-ai.cn` 建立 `agnes_cn_v1`，还是必须继续以现有 `apihub.agnes-ai.com` 为生产 Host？（建议：中国站作为首个官方 profile；legacy Hub 单独 Probe）
2. **配置作用域**：是否允许同一 Workspace 配多个 Agnes Connection，并由项目分别绑定？（建议：允许，这是后续多 Provider 和企业代理所必需）
3. **正式 fallback**：主角 keyframe/video 的 Provider 失败时，是否允许切换到另一个已通过同等人物 Gate 的模型？（建议：P0 为 `none`；P1 只允许切换到已单独 `quality_gated` 的绑定）
4. **视频 Gate 策略**：漂移失败后直接失败，还是进入人工复核队列？（建议：主角硬失败，边缘分数进入人工复核；阈值需用正式样本校准）
5. **用户可配置边界**：是否允许企业管理员配置私有代理 Host？（建议：普通用户仅官方 Host；企业管理员通过 allowlist 配代理，禁止任意内网地址）
6. **P1 首选 Provider**：MiniMax/海螺、Seedance、可灵的优先级。（建议：先 MiniMax/海螺，因为当前可获取的官方 Wire Contract 最完整）

在上述决策确认前，可以先执行阶段 A 的合同修正、类型化请求和 Contract Test；真实付费 Probe 需明确使用哪个 Agnes Host/账户。

## 18. 官方资料清单

Agnes：

- Agnes Image 2.1 Flash：<https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-image-21-flash.md>
- Agnes Image 2.0 Flash：<https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-image-20-flash.md>
- Agnes Video V2.0：<https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-video-v20.md>
- Agnes 快速开始：<https://wiki.agnes-ai.cn/zh-Hans/docs/quickstart.md>
- Agnes 错误码：<https://wiki.agnes-ai.cn/zh-Hans/docs/code.md>
- Agnes 官方文档索引：<https://wiki.agnes-ai.cn/llms.txt>

MiniMax / 海螺：

- MiniMax 官方文档索引：<https://platform.minimaxi.com/docs/llms.txt>
- 图片图生图/主体参考：<https://platform.minimaxi.com/docs/api-reference/image-generation-i2i.md>
- 主体参考生视频 S2V：<https://platform.minimaxi.com/docs/api-reference/video-generation-s2v.md>
- H3 V2 创建视频任务：<https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create.md>
- 海螺图生视频 I2V：<https://platform.minimaxi.com/docs/api-reference/video-generation-i2v.md>

Seedance / 火山方舟：

- Seedance 2.0 官方模型页：<https://seed.bytedance.com/zh/seedance2_0>
- 火山方舟官方文档库：<https://www.volcengine.com/docs/82379>
- 火山方舟视频生成 API 页面：<https://www.volcengine.com/docs/82379/1520758>

可灵：

- 可灵开放平台：<https://klingai.com/dev>
- 可灵官方 Image to Video API Reference 路由：<https://kling.ai/dev/document-api/apiReference/model/imageToVideo>

以上链接用于记录本次规划依据。实现每个 profile 时仍须保存当时可访问的请求/响应 Contract Fixture，并在官方文档变化后重新验证。
