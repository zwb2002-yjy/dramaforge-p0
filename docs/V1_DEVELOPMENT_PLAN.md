# DramaForge 首版开发方案与实施计划

版本：第二版方案（开发设计与执行合并稿）。日期：2026-09-15。  
状态：仅规划，待实施；本轮不修改业务代码、不运行服务、不调用模型。  
代码基线：`dev` / `5ea45d6373d840d37f34a472b3dbe4853da9f8e6`，含本次读取到的未提交改动。  
入口：[CURRENT.md](CURRENT.md)。

## 1. 这次到底开发什么

将现有工作台补成一套用户能够从故事开始、完成多镜头短剧并导出成片的产品。
目标作品仍为 15–30 秒、真人写实、角色对白驱动的短剧。主体工作是补功能、接通交互、
完善数据和状态处理；测试用于证明开发结果，发布是开发完成后的最后阶段。

本文件替代 [原发布设计](V1_RELEASE_DESIGN.md) 与
[原发布执行计划](V1_RELEASE_EXECUTION.md) 作为本次开发任务的规划入口。
它不替代 CURRENT 列出的产品、架构、API、数据和部署领域权威。
新增类型、表、端点、字段及组件均为**拟开发设计**，实施时先同步相应领域文档和术语。
不能把下面的接口表当作当前已经可调用的 API。

需求来源是用户的首版发布目标；[闭环审计](PRODUCT_CLOSURE_AUDIT.md)、
[能力矩阵](PRODUCT_CAPABILITY_MATRIX.md) 和 [架构映射](ARCHITECTURE_MAPPING.md)
提供问题线索，其全部建议不自动进入本次范围。

### 1.1 首版的功能边界

| 用户需求 | 本次开发后的能力 | 不在本次开发范围 |
|---|---|---|
| 开始作品 | 创建项目、导入支持格式的剧本，或通过 Story 提案创作 | 全格式文档解析、完整剧本版本编辑器 |
| 管理素材 | 生成结果入资产、选择版本、绑定镜头引用 | 本地媒体上传平台、多参考图能力扩展 |
| 设计镜头 | 已有设计表单可保存，导演建议可采用/拒绝，实际生效配置可解释 | 自由聊天、通用领域工具集、独立 Creative Pack 产品 |
| 制作镜头 | 预览计划、确认生成、查看进展、可靠恢复同一次操作 | 通用 DAG 编辑器、自动最小重算 |
| 审片和修复 | 媒体标注、人工判断、明确的局部重生成步骤、重新选正式版本 | 自动人脸评分、局部重绘、自动根因诊断 |
| 剪辑与交付 | 保存当前编辑结果，明确导出当前版本，获得真实 MP4/SRT | 专业多轨、拖拽吸附、时间线关键帧 |
| 重新打开 | 恢复有效项目/镜头、正在进行的生成/修复和已保存剪辑 | 跨设备最近项目、完整项目归档/回滚 |

资产入库、人工审查和修复流程不是“验收脚本功能”，必须有真实的产品 UI、API、
持久化及恢复路径。不能要求用户手写 HTTP 或修改数据库才能完成主链。

## 2. 已有基础与需要重新判断的事项

| 模块 | 可以复用的现有实现 | 本轮静态判断 |
|---|---|---|
| Script | `assets/script_import.py`、`api/v1/scripts.py`、Story proposal | 后端导入存在，开发重点是入口、确认、错误反馈和刷新后的结果 |
| Asset | `assets/models.py`、`version_service.py`、`assets/from-artifact` | 入库已能原子创建 Asset/Version/Reference；当前初始版本为 formal，UI 必须明确该动作 |
| Execution | `ProductionCommands`、`WorkbenchExecutionService`、计划与 receipt API | 不重建执行系统；重点补原键恢复与输入一致性 |
| Review | `ReviewAnnotation`、审查 NodeRun/Artifact、`formal_selection.py` | 标注 open/resolved 不能表达对具体证据的人工放行，需要补决定记录及统一准入 |
| Repair | `repair_service.py`、repair-plan/repair API | 现有两阶段选项只发关键帧；需要产品步骤、后续视频动作与持久恢复 |
| Editing | EditSession、FinalFilm prepare/export、真实 ffmpeg renderer | 保留剪辑模型，补版本反馈、审查衔接、正式交付的真实性校验 |
| Director | 现有提案服务、轮次与 LangGraph runtime | 补可达性和配置联动，不把确定性 runtime 描述成自由对话 Agent |

本轮开始前，工作区已经出现以下未提交改动：推荐路由及前端请求构造、生成 OpenAPI、
`directorApiContract.test.ts`、`test_timeline_render_ffmpeg.py`。它们不属于本轮修改，
也不能在没有测试报告时算作完成。后续开发先审阅和验证，再补剩余缺口，避免覆盖。

两项纠偏必须进入后续基线记录：

- 推荐接口：HEAD 与工作区不同；工作区已把后端移到 `/director/shots/.../recommendation`，
  前端和生成契约也有对应修改。不能机械执行旧计划的“删掉前端 /director”。
- 渲染测试：当前真实集成测试明确将 renderer settings 替换成 development，原有测试
  已具备真实 ffmpeg 路径，工作区又增加了解码等检查。因此“所有 CI 渲染都是假”的
  笼统结论不能沿用。仍需区分单测 stub、真实 renderer 测试、完整交付服务校验和实际下载。

本轮不声明这些改动已经通过 CI；未读取密钥、未核实 DS/Agnes 模型可用性或远端发布状态。

## 3. 总体实现结构

```text
现有 Project / Script / Scene / Shot 页面
  ├─ 设计保存、Story/Director 提案与 Apply
  ├─ Artifact 入资产、AssetVersion 引用
  ├─ 生成计划与原操作回执
  └─ Review / Repair / Editing 的用户动作
        ↓ 统一 API 客户端、身份验证、CSRF、版本与输入校验
应用服务 / typed Command
  ├─ 人工审查决定与准入查询
  ├─ Repair 计划和分步骤确认记录
  └─ ProductionCommands / 既有编辑与交付服务
        ↓
现有 ProductionGraph → NodeRun → Outbox → Worker
        ↓
ProviderOperation / Artifact → Formal 选择 → EditSession → FinalFilm
```

不增加第二套媒体执行器、任务队列或生产状态表。Review 决定记录用户判断；Repair 记录
用户选择与步骤关联，运行状态仍来自 NodeRun，媒体结果仍来自 Artifact。
Candidate 继续是查询结果，Formal 继续由现有指针确定。

前端使用现有 React、TanStack Query/Router、Zustand 与
[前端骨架](../frontend/design/README.md)：路由只装配，业务放 features，通用请求放 lib，
服务端状态归 Query；不新建并列工作台、请求封装或样式体系。

## 4. 功能一：剧本输入与项目恢复

### 4.1 用户交互

在现有 ScriptWorkspace 中提供“创作提案”和“导入剧本”两个入口。
导入面板支持粘贴文本和本地读取 UTF-8 `.md`/`.txt`，文件在浏览器转成文本，
提交现有 JSON API；这不引入通用文件上传服务。
面板展示支持的 `# Episode / ## Scene / ### Shot` 示例、文件名和文本内容。

“确认导入”才写 canonical 数据。成功显示新增/复用结果和 Scene/Shot 数量，提供
“进入第一个镜头”；解析失败保留文本并定位错误。Story 的部分采用/全部采用/拒绝行为不变。

### 4.2 后端与数据

- 复用 `import_script` 的事务、内容 hash 与重复校验；失败整笔回滚，不能留下半个 Scene。
- `ScriptImportBody` 继续使用 `filename`、`text`；在 API 与解析器统一约束非空、大小和
  受支持结构。拟定首版文本上限为 1 MiB UTF-8 字节，并与网关上限核对。
- 在现有响应上新增 `import_outcome: created | reused`，让重试不被误报为再次创建。
  旧 `script_document_id / episode_id / scene_count / shot_count / shot_ids / content_hash` 保留。
- 不把重复导入做成覆盖更新，不增加 Script 版本历史表，不自动为名字相同的角色绑定资产。

项目恢复复用 `UserProjectPreference.workspace_state`。写入与读取均对账 Project、Scene、
Shot 归属；允许清除选择，不接受其他项目的 ID。过期 Shot 回到仍有效 Scene，Scene 也失效
则回项目概览。现有 UI 偏好可保留，生产事实不得从 localStorage 恢复。

### 4.3 前端改动与完成条件

在 `features/script/ScriptWorkspace.tsx` 装配拟新增 `ScriptImportPanel`；复用
`lib/api.ts` 的 `importScript`。成功后失效 Script/Scene/Shot 查询，再从服务端取回结果。
无效编码、过大文件、空文本在提交前解释；服务端错误映射为可读信息。

完成条件：浏览器可导入、重复导入不重复创建、失败不丢输入；重新打开定位合法镜头，
不存在或无权访问的项目/镜头不造成空白页或无限重定向。

## 5. 功能二：生成结果入资产与镜头引用

### 5.1 用户交互

在关键帧/视频候选详情和 Artifact 可见位置提供“加入资产”。弹窗选择名称、类型、
reference role，展示来源；按钮明确写“创建资产并将此版本设为正式”，对齐当前 API 语义。
成功后显示资产卡片及“绑定到当前镜头”；绑定仍是另一个显式动作。

新增拟复用组件 `AddArtifactToAssetDialog`，在不同候选入口共用；资产面板显示生成来源，
已有 `current_formal / pinned_version / direct_artifact` 模式以用户能理解的中文说明呈现。
角色名相同不能代替版本或 Artifact ID 的选择。

### 5.2 后端、API 与持久化

沿用 `POST /projects/{project_id}/assets/from-artifact` 的单事务创建链。
增加 Artifact 属于当前项目、存储可用、未删除及类型/reference role 相容校验。
将 HTTP 内的创建逻辑下沉到资产应用服务，便于原子幂等与复用。

为一次入库提交增加 `Idempotency-Key`。推荐最小持久化方案是给 Asset 增加可空
`creation_request_key`、`creation_request_hash`，按 `(project_id, creation_request_key)`
非空唯一；hash 覆盖 artifact/name/kind/description/reference role/metadata 的规范化输入。
同键同输入返回原 Asset，同键不同输入返回 409，另一明确新操作可以使用新键。
这解决传输重试，不禁止用户明确把同一 Artifact 用于多个不同资产。

前端在首次提交前保存该操作键；丢响应后用同键同输入重新获取原结果，不随机换键。
已有 reference API 继续负责镜头引用，生成前再从服务器解析实际版本和能力槽位。

完成条件：连续点击/丢响应最多产生一套 Asset/Version/Reference；回收、恢复和绑定
仅在成功后更新状态，失败显示原因，刷新后版本引用仍可追溯。

## 6. 功能三：镜头设计、导演建议与有效配置

### 6.1 设计保存

保留 Scene/Shot 的现有表单和 design API。区分编辑中的草稿、服务器已保存值和
已冻结执行输入；未保存设计不直接伪装成新执行方案。版本冲突保留本地草稿，展示
“服务器已有更新”，允许重载并重新检查，不自动覆盖。

生成前的计划摘要显示实际模型、引用版本、已采用创意配置及不支持项。
Style/Skill/ShotLanguage 继续由现有编译器产生内容，不能展示成 Provider 硬参数保证。
模板推荐但尚未消费的值标为建议，需要用户选择/保存后生效；首版不新建创意版本仓库。

### 6.2 导演接线

优先审阅现有未提交的推荐路由修改。建议采用当前工作区已经一致的
`/projects/{project_id}/director/shots/{shot_id}/recommendation`，同步 `API.md`、
全部消费者、OpenAPI 和测试，不同时保留两个 canonical 推荐入口。
是否已有外部调用者在发布前检查；如有，明确迁移说明，不擅自恢复退休 API。

建议生成只产生 typed proposal；Apply 时再次校验 Shot 版本、用户锁和所选字段。
拒绝或仅查看建议不写 Shot，不创建媒体 NodeRun。
轮次状态从服务端恢复，保留 AUTO/ASSIST/MANUAL 的原有区别，不新增聊天产品。

### 6.3 运行能力与部署

发布目标配置使用实际验证的 langgraph。API 与 director worker 读取一致配置，
checkpoint URL、私有 schema/角色由现有 bootstrap/migration 路径准备。
在现有项目/Director 运行信息响应中提供有效引擎和可执行能力及阻塞原因，
优先扩展已有 read model；如确实没有合适响应再增加只读 capabilities API。
前端据此显示可执行动作；服务端仍必须独立验证，不能只靠禁用按钮。

只有 Director 不可用时，MANUAL 仍能进入现有生产链；不能悄悄选择另一个引擎或模型。
更改默认配置不改写已开始轮次的引擎身份，安装升级保留用户的凭据和显式设置。

完成条件：保存值与计划一致，推荐/采用路径可达，过期提案受阻，默认发布配置下
AUTO 能开始轮次，MANUAL 不依赖导演 worker 存活。

## 7. 功能四：可靠生成、执行回执与状态展示

### 7.1 一次操作的产品流程

```text
修改并保存设计 → 预览计划 → 用户确认生成
  → 先记录本次操作键 → 提交 executions
      ├─ 收到回执：按 node_run_id 展示真实进度
      └─ 超时/断网：保持原键 → 查询 receipt → 恢复同一次运行
```

计划与 operation identity 分开：同一计划可以被用户明确再生成一次；同一次操作的
网络重试不能变成再生成。不能仅把 plan_fingerprint 当作永远不变的操作 ID。

### 7.2 前端开发

在 `features/shots` 增加操作恢复 hook，供 `ShotProductionActions` 使用。
发送前持久保存用户/工作空间/项目/镜头、stage、operation key、plan fingerprint、
时间及回执 ID；不保存凭据。存储命名隔离账号，登出清除，切换账号不读取原记录。

前端请求阶段仅表达 `确认中 / 提交中 / 正在核对回执 / 已取得回执 / 明确被拒绝`，
不添加这些值到 NodeRun 的数据库枚举。
查询 `GET .../executions/receipt?stage=...&idempotency_key=...` 有界退避；404 只表示
暂未查到已提交回执，不足以证明没有发生操作。可同键重发同一冻结请求，不能自动换键。
存在 `unknown_submission` 时展示对账入口和说明，禁止“一键重试”偷偷创建新请求。

### 7.3 后端开发

继续经过 `ProductionCommands.submit_user_execution` 与 `find_command_receipt`。
补查同键不同输入是否被可靠拒绝：回执解析至少比较 project、shot、stage 和冻结计划
指纹/请求身份。对已提交同次请求先返回原回执，不因当前 Shot 随后变更而丢掉已发生事实。
新操作才重新检查版本、计划、模型/凭据 revision、引用和审查准入。

并发请求必须由现有数据库唯一约束/事务锁闭合，不能依赖按钮禁用。
拒绝版本过期/输入冲突的请求，不创建 ProviderOperation；记录请求状态不能额外发模型探测。

`production-page.tsx` 与相关工作台按真实 NodeRun 展示节点状态。集中补全中文标签，
包括 `completed_after_cancel`；整体比例只能是实际节点状态的汇总，不能反推单节点状态。
无运行数据显示“尚未开始/状态待刷新”，不虚构完成。

完成条件：双击、超时、刷新和页面重开回到同次运行；同键异参 409，新生成须明确动作；
状态与 API 一致，未知提交不触发额外外部 create。

## 8. 功能五：人工审查与生产准入

### 8.1 要新增的产品能力

在现有 ReviewWorkspace 中并列展示“媒体与标注”“自动检查证据”“人工判断”。
`needs_human` 显示“待人工判断”；用户查看当前素材后选择通过或拒绝，填写理由。
标注的 open/resolved 继续表示问题处理，不等于整段媒体获准。
“审查通过”和“设为正式”保留两个明确动作，不能互相隐式触发。

### 8.2 拟新增的人工决定记录

在 `delivery/models.py` 增加 `HumanReviewDecision`，表名拟为 `human_review_decisions`。
这是人工决定事实，不替代审查 NodeRun，不复制媒体结果，也不引入泛化 Review 引擎。

| 字段 | 约束与用途 |
|---|---|
| id / project_id / shot_id | UUID，项目/镜头外键与租户隔离 |
| artifact_id | 必填，指向正在判断的不可变素材 |
| review_node_run_id / review_artifact_id | 必填，指向这次判断依据的审查运行及其证据 Artifact |
| review_kind | 限既有 identity / video_drift / continuity 三类语义，映射现有节点键 |
| subject_fingerprint | 由服务端生成，绑定媒体、证据及适用创作输入 |
| shot_version_at_decision | 决定当时的 Shot 版本，作为审计信息 |
| decision / reason | `approved | rejected`；理由不可为空 |
| actor_id / created_at | 从已认证身份和服务器时间填写，不接受客户端指定 |
| request_key / request_hash | 同键同请求回读；同键不同请求 409 |
| supersedes_id | 可空，新决定追加并指向上一决定，不覆写历史 |

按 project/shot/artifact/review_kind 建查询索引；request key 在项目内唯一。
在事务中锁定对应审查对象，防止同一当前决定被同时替代两次。所有关联逐项检查项目、
镜头、媒体类型和真实血缘；RLS 与非属主不可见行为沿用项目规范。

**版本处理：** Shot.version 用于写入时的乐观锁，不直接当作批准有效期。
Formal 选择本身会推进版本，不能因此让刚通过的同一素材立即失效。
subject fingerprint 绑定 Artifact/生产冻结输入/审查证据和对应阶段的设计、身份引用；
UI 偏好与无关字段不参与。素材、相关设计/引用或审查证据变化，重新判断；
仅 Formal 指针确认和页面切换不使同一审查失效。阶段相关字段清单必须在契约与测试中显式列出。

### 8.3 拟新增 API 与共享服务

所有下列相对路径前缀为 `/api/v1/projects/{project_id}`：

| 动作 | 拟新增接口 | 请求/响应核心字段 |
|---|---|---|
| 读取当前审查 | `GET /shots/{shot_id}/review-summary?artifact_id=...` | 返回机器证据、当前人工决定、适用性、允许动作、阻塞原因 |
| 提交人工决定 | `POST /shots/{shot_id}/review-decisions` | 请求 artifact/review run/expected shot version/expected decision ID/decision/reason；header 幂等键；返回持久化决定及新摘要 |

API 只鉴权/校验/转发；应用服务负责关联校验与决定写入。业务准入函数拟放
`production/review_gate.py`，读决定与执行事实；中立输入/输出类型放 `contracts`。
domain 模型不 import Production/Director 服务。审查摘要用有类型的阻塞原因，
不让前端根据多个字符串自行猜测批准状态。

### 8.4 放行顺序，避免死锁

| 生产位置 | 需要开发的行为 |
|---|---|
| 关键帧生成结束 | 通过现有 Outbox/节点机制创建身份审查，证据关联该候选；不要求先成为 Formal |
| 选择正式关键帧 | 验证当前候选血缘、适用身份审查及人工决定，通过后才写指针 |
| 生成视频 | 原正式关键帧存在且对应人工审查仍适用；未通过则提交前阻止 |
| 视频生成结束 | 创建对应漂移审查；人工通过后允许设为正式视频 |
| FinalFilm prepare | 允许制作零成本 voice/subtitle/composite/continuity 证据，返回待判断对象；不能因尚未生成的 continuity 决定而阻止 prepare |
| FinalFilm export | 校验冻结素材与适用审查决定、已保存 timeline 版本；通过后才启动交付渲染 |

扩展真实执行入口，不只给静态模板加边。人工等待作为产品待办处理，不占用 worker
轮询、不创建新 node_type；创建后续媒体运行前校验，必要的执行时复核也走相同判断。
自动检测的技术硬失败不能被人工质量通过覆盖；机器 `needs_human` 保持原样，
由独立人工决定满足准入。新增阻断规则不回写旧 Artifact/NodeRun 的历史结果。

历史素材没有充分审查证据时显示待补审查，可生成零成本审查并人工处理，不能迁移成默认通过。
决定后来被撤销时阻止新的生产/导出，保留已有运行和交付历史，不宣称能撤回已经发生的调用。

完成条件：在浏览器完成“候选 → 审查 → 人工判断 → Formal”；缺失、拒绝、过期、越权
在所有手动/AUTO/Repair/Export 入口都不能绕过，但 prepare 能生成被审查的素材。

## 9. 功能六：可恢复的分阶段 Repair

### 9.1 用户交互

审片页“创建修复计划”打开侧面板：展示当前问题、相关媒体、两个修复选项、
本步生成内容、保留素材、后续人工动作及费用估计（无法估计明确说明）。
生成关键帧成功后，面板进入“审查并确认关键帧”，不显示“修复完成”。
确认后才出现下一步视频计划及生成按钮；视频通过审查并被明确设为 Formal 才完成修复。

用户可关闭面板再打开、刷新、切换页面。结果来自服务端记录与 NodeRun，
不依赖某次 React mutation 仍在内存里。

### 9.2 拟新增的最小持久化

在生产领域新增 Repair 记录，建议在 `production/models.py` 定义以下两张表：

| 表 | 核心字段与职责 |
|---|---|
| repair_requests | id、project_id、shot_id、created_by、option、计划 schema_version/hash、选中标注 ID 与内容摘要、源 Formal Artifact ID、相关输入指纹、created_at、关闭原因/时间、request_key/hash；保存用户确认的修复意图 |
| repair_steps | id、repair_request_id、ordinal、stage、冻结 plan fingerprint、command_key、node_run_id、用户确认 actor/time、采纳的 Artifact/审查决定关联；保存每步动作与执行事实的引用 |

`(repair_request_id, ordinal)` 唯一，command key 唯一并沿用统一执行幂等。
不存第二份 Provider task ID、产物字节或 running/completed 状态；UI 步骤由现有
NodeRun、当前 Formal、审查决定及确认记录计算。这个表不是另一个调度器。
费用估计仅是计划说明，不创建退休的 budget/batch runtime gate。

### 9.3 计划和继续执行 API

复用已有端点并补足合同（以下新增字段和端点均待开发）：

| 接口 | 开发内容 |
|---|---|
| `POST /shots/{shot_id}/repair-plan` | 请求可选 annotation IDs/修复选项与期望版本；返回 plan hash、源素材/证据、步骤列表、保留素材和费用估计来源；只读计算，不生成媒体 |
| `POST /shots/{shot_id}/repair` | 要求所选 option、expected shot version、预览 plan hash、原幂等键；服务端重算核对，原子创建修复记录/第一步，并经 ProductionCommands 提交；响应增加 repair ID/步骤摘要，保留现有回执字段 |
| `GET /shots/{shot_id}/repairs` | 返回可继续的修复记录，支撑页面重开 |
| `GET /shots/{shot_id}/repairs/{repair_id}` | 返回每步实际回执、审查/采纳结果与 next_action |
| `POST /shots/{shot_id}/repairs/{repair_id}/steps/{step_id}/execute` | 当前步骤及版本、已确认执行计划指纹、该步操作键；校验人工门后提交同一生产入口 |

从 Preview 到 Submit 间，标注、相关设计、模型选择或源素材改变时 409 `REPAIR_PLAN_STALE`，
要求重新预览。事务中保持 RepairStep 与 NodeRun/outbox 一致；回执丢失同键返回原步骤。
已确认第一步造成的 Formal/版本变化是预期状态转移，读取确认记录后更新下一步基线，
不能把正常继续误判成整个修复过期。其他用户修改仍要求重新预览。

### 9.4 两条具体流程

| 选项 | 产品步骤 | 保留/替换规则 |
|---|---|---|
| rerun_video | 已批准正式关键帧 → 预览视频 → 确认生成 → 视频审查 → 人工通过 → 显式 Formal | 关键帧保留；原视频到最后确认前不变 |
| regenerate_keyframe_then_video | 预览关键帧 → 确认生成 → 身份审查 → 人工通过/设为 Formal → 预览视频 → 确认生成 → 视频审查/设为 Formal | 每步只生成候选；不跳过中间人工门，不自动覆盖旧 EditSession |

步骤技术失败显示失败原因和仍可用的旧素材；同次提交未知先查回执。
明确重新生成属于新的 Repair 步骤尝试，保留旧关联，不覆写 NodeRun。
只停止后续修复不会取消已经提交给 Provider 的运行，UI 必须解释实际边界。
标注只有用户明确处理才变为 resolved，修复成功不能自动关闭全部历史标注。

完成条件：两种修复都能在浏览器走完、重开恢复，局部失败可理解，全部媒体仍有
统一生产血缘，旧 Formal 与编辑会话没有被后台静默改写。

## 10. 功能七：编辑保存、尾部准备与真实交付

### 10.1 开发用户流程

继续使用现有 EditSession 表单式剪辑：素材排序、时长、字幕及已支持的音量/转场。
界面分别显示“有未保存修改”“已保存 vN”“正在准备素材”“待连续性审查”“可导出”。
这些是视图状态，不复用 NodeRun.status 表示所有产品状态。

```text
编辑 → Save 成功取得版本 N
  → prepare 已保存版本 N 的 voice/subtitle/composite/continuity
  → Review 完成适用人工决定
  → 用户 Export N → 渲染 → 播放/下载 MP4 与 SRT
```

用户继续编辑时，旧导出保留并标注所属版本；不能把 vN 的成片显示成最新草稿成片。
Save 冲突保留草稿；重复 Export 同次请求回读原结果，另存新版本须明确再次导出。

### 10.2 后端与产物处理

复用 `editing/models.py`、现有 timeline 保存服务和 `production/final_film.py`，
不创建 EditingGraph，不把剪辑写回 Shot 或 Formal。
prepare/export 都绑定已保存 timeline 版本；导出提交时冻结具体素材、审查决定和引用。
后续修改不能让排队中的任务偷偷读取另一组“当前 Formal”。

为正式交付校验提取明确的校验函数：拒绝 `summary.test_render == true`；检查实际字节
能被探测/解码、视频/音频/字幕与时间线要求一致，失败不写交付成功状态。
快速单测可保留 stub，但 stub 不能调用“正式证明通过”的分支；相关单测改为注入
受控服务边界或验证正确拒绝，不能增加测试环境绕过正式校验的开关。

对象写入与数据库提交之间失败时，不发布半成品 manifest；保留可诊断结果，
重试用原幂等键/对象身份对账，不重新生成上游付费素材。
独立解码在正式交付边界及对应集成验证执行一次，不在每次网页 GET 下载时重复解码。

针对首版对白作品，缺失对白源或预期字幕应作为交付阻塞；对未来合法的静音片段不能
用“每个 Shot 都必须说话”替代需求。音轨存在只能证明格式，最终对白与字幕质量需人工判断。
声音、字幕、烧录与混音路径复用现有本地实现，DS/Agnes 不被擅自当成语音 Provider。

完成条件：保存/准备/审查/导出步骤可恢复，下载真实文件可播放；只改剪辑重导出时
媒体 ProviderOperation 数量不增加，FinalFilm 仍绑定保存版本和完整血缘。

## 11. 数据、API 和并发规则汇总

### 11.1 数据库变更清单

| 变更 | 所属开发项 | 迁移要求 |
|---|---|---|
| Asset 的 creation request key/hash 及非空唯一索引 | 资产入库 | 旧数据可空，不臆造旧提交键；唯一冲突回读 |
| human_review_decisions 表、外键、索引和 RLS | 人工审查 | 不回填“已批准”；旧素材按实际状态补审查 |
| repair_requests / repair_steps 表、唯一约束和 RLS | Repair | 仅记录新操作；不把历史 NodeRun 猜成完整修复流程 |
| workspace_state 校验/清理 | 项目恢复 | 优先应用层归属校验，不新增通用工作区状态表 |

迁移编号根据实施时实际 Alembic head 分配，不预占 `0067` 等编号。
同一功能的模型、迁移、API 和 RLS 一起交付。新建库与从当前 head 升级都需验证。
开发前若发现现有结构已完整表达上述记录则复用，并在本方案记录映射，禁止创建同义表。

### 11.2 错误和响应设计

所有写入使用统一身份/工作空间/CSRF/错误封装。409 表示并发版本、同键异参或计划过期；
422 表示输入无效；404 表示资源不存在或按既有约定不可见。
“待人工判断”“运行中”“暂无已提交回执”是具体业务结果，不能统统变成泛化服务器错误。

新错误子码须在现有结构内注册，前端使用统一标签映射。
变更 API 后生成 `frontend/src/shared/api/generated.ts`，不手改生成文件，
同时更新真实路由与消费者的契约检查。路由表中标为拟新增的端点只有落地后才能使用。

### 11.3 各类版本分别负责什么

| 标识 | 职责 |
|---|---|
| Shot.version | 用户写入/确认时的并发控制，不能代替完整设计历史 |
| plan fingerprint | 一个冻结执行方案的内容身份 |
| command/idempotency key | 用户一次明确操作的传输重试身份 |
| Artifact ID / content hash | 不可变媒体及其内容身份 |
| review subject fingerprint | 人工决定究竟适用于哪一份素材、证据和相关输入 |
| EditSession.version | 当前保存后的剪辑版本，导出必须绑定 |

## 12. 按什么顺序开发

任务按完整功能闭环组织，不拆成“全部写后端、最后才接 UI”。每项包含实现、相关验证和
必要文档；下面的验证栏是收尾条件，不是开发任务主体。不因此自动派生子代理。

| ID | 开发交付物 | 主要代码位置 | 依赖 | 对应旧工作包 |
|---|---|---|---|---|
| DEV-00 | 校准当前分支与 dirty、审阅已有路由/渲染改动，形成保留与待补项清单 | 现有 diff、相关领域文档 | 无 | W0 |
| DEV-01 | 可靠生产提交 hook、原键回执恢复、同键异参拒绝、真实状态标签 | features/shots、routes/production-page、production/application、workbench_execution | DEV-00 | W2 |
| DEV-02 | ScriptImportPanel、导入结果类型、项目/镜头恢复校验 | features/script、api/v1/scripts、assets/script_import、workspace_state_service | DEV-00 | W5＋恢复缺口 |
| DEV-03 | 生成结果入资产组件、入库幂等和迁移、版本引用 UI | features/assets、api/v1/assets、assets/models/version_service | DEV-00，复用 DEV-01 的交互纪律 | W5 |
| DEV-04 | 镜头保存反馈、推荐契约修正、有效配置摘要、Director 部署能力读模型 | features/director、api/v1/director、config、Compose/bootstrap | DEV-00 | W2/W6 |
| DEV-05 | 人工决定契约/迁移/API、审查摘要组件、统一准入及审查节点触发 | delivery/models、api/v1/review、production/review_gate/formal_selection、ReviewWorkspace | DEV-01 | W3 |
| DEV-06 | Repair 计划/步骤模型、继续 API、恢复与侧面板、两个选项闭环 | production/repair_service/models、api/v1/workbench、features/review | DEV-01/05 | W4 |
| DEV-07 | Save/prepare/review/export 联动、版本反馈、冻结审查与素材关系 | features/editing、editing、production/final_film | DEV-05 | W1/尾部交付 |
| DEV-08 | 正式交付字节校验、stub 拒绝、下载完整性与现有真实 ffmpeg 测试补齐 | timeline_renderer、final_film、integration/test_timeline_render_ffmpeg | DEV-00，整链接 DEV-07 | W1 |
| DEV-09 | API 生成、迁移/依赖收敛、免费全链联调、领域说明和用户引导 | 已修改模块、生成类型、容器与 live 测试 | DEV-01–08 | W7/W8 |
| REL-01 | 干净候选、完整门、DS＋Agnes 真实场景、候选绑定证据 | 现有质量容器、R7 驱动与 live 浏览器 | DEV-09 | W9/W10 |
| REL-02 | 发行包预演、Owner 审阅合并、实际发布及安装恢复 | 现有 Release workflow、installer、部署文档 | REL-01 | W11 |

**第一轮开发范围：DEV-00 → DEV-01，并补齐 DEV-08 中可独立处理的交付校验。**
先稳住请求和交付事实，再推进 DEV-02/03/04，随后完成 DEV-05/06/07 的较大业务闭环。
DEV-05 不只增加数据库表：必须带最小审查 UI 和真实准入，避免新门锁死现有生产。

以上是开发顺序建议，本轮只生成方案；不得因为这张表存在便开始写代码或收费测试。

### 12.1 每项开发的最小完成条件

| 开发项 | 对应验证 |
|---|---|
| DEV-01 | 双击/丢响应/页面重开/同键异参；数据库约束与 API 回执一致 |
| DEV-02 | 合法/错误/重复文本；事务回滚；过期 Scene/Shot 恢复 |
| DEV-03 | 重复并发入库、跨项目/失效 Artifact、初始正式版本与引用往返 |
| DEV-04 | 路由与生成 OpenAPI 一致；拒绝/部分 Apply；保存冲突；引擎可达性与 MANUAL 独立 |
| DEV-05 | 当前素材人工通过可继续；拒绝/旧证据/无证据/越权受阻；Formal 版本推进不造成自失效 |
| DEV-06 | 两阶段修复、刷新恢复、计划过期、回执丢失、旧 Formal 保留 |
| DEV-07/08 | 已保存版本才导出、prepare 不死锁、剪辑重导出零媒体调用、实际字节解码、损坏/stub 拒绝 |
| DEV-09 | 新库与升级迁移、RLS、OpenAPI、无新跨层旁路、免费真后端全链 |

优先使用项目现有测试夹具和锁定依赖。mock UI 证明交互，PG 证明事务与隔离，
本地合成媒体证明 renderer；三者不能互相代替真实 Provider 的候选验收。

## 13. 真实联调与发布安排

只有 DEV-09 完成并冻结候选后，才进入真实模型验收阶段。用户已指定 DS＋Agnes 作为
测试通道方向；具体模型/连接/能力从该实例的 ModelManifest 与有效配置读取并冻结，
不根据简称猜测模型，不静默切换。DS 负责所配置的文本通道、Agnes 负责其实际支持的
图像/视频通道，语音继续使用项目明确配置的既有链路。

先用本地确定性素材和替身解决开发问题，再用真实调用确认产品链与质量。实际收费操作
按仓库要求记录本次操作、正数预算和 Owner 授权；该操作约束属于测试执行管理，
不在产品中恢复已经删除的 budget/batch 前置系统。未知提交先对账，不盲重试。

正式候选必须从干净 checkout 构建；来源报告绑定完整 SHA、镜像 digest、迁移 head、
模型身份、运行和 Artifact/媒体 hash。现有未提交工作不能凭改报告就成为正式候选。
通过现有 CI `policy`、`container-gates` 与安全门，真实浏览器覆盖用户按钮到后端持久化。

实际作品至少覆盖 Template＋AUTO、Free＋ASSIST 两条初始化组合，并证明 MANUAL
在导演 worker 不可用时可完成；作品都走同一生产链。检查真实 MP4/SRT、对白/字幕与
人工审片结论，证据按候选保存，不能以搜索日志里的 PASS 替代结构化收据。

发行仍按 [RELEASE.md](RELEASE.md) 与 [DEPLOYMENT.md](DEPLOYMENT.md)：
`dev → main` 由 Owner 审阅并合并，Agent 不自批自合；核对最终来源后发布版本化制品。
安装、重启、备份恢复和实际声明的平台验证完成后才记录发布完成。
第一版产品范围不强制对应 SemVer `1.0.0`，版本按仓库 release contract 一致性处理。

## 14. 本文交付与后续维护

本轮交付是一份可指导开发的合并方案，包含用户交互、服务职责、拟新增模型/API、
事务与状态设计、代码落点和开发顺序。没有在本轮执行任何 DEV/REL 任务。

后续实施在本文件相应任务旁记录实际状态与差异；代码事实落到 DATA_MODEL、API、
PRODUCTION_RUNTIME 等各自权威，发布状态仅更新 V1_STATUS。
原 W 编号保留在第 12 节用于对照；不要同时按两套计划重复开发或将旧审计结论当作最新事实。
