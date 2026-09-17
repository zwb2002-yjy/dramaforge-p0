# ARCHITECTURE_MAPPING — 当前代码到架构的映射

Status: current（入口见 [CURRENT.md](CURRENT.md)）

本文维护当前模块归属、能力处置与尚未解决的结构问题。某次扫描的行数、边数、
阶段执行记录和工期估计不作为当前事实；历史快照通过 Git 追溯。
架构规则见 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)，模型事实见
[DATA_MODEL.md](DATA_MODEL.md)，前端能力消费合同见 [API.md](API.md)。

## 1. 整理顺序：用户能力优先，不以“无消费者”推导删除

1. 找到该能力在桌面创作、审核、修复、交付中的实际用途。
2. 检查是否已有完整的权威替代路径；区分缺失的前端消费与无价值的旧实现。
3. 区分 UI、Worker、Provider 回调/投递、运维、持久历史的消费者。
4. 需要而未接入的能力先补设计；已有替代的旧入口才清退；持久数据另外确认。
5. 不为了减少目录数量移动大量活跃代码，不按 legacy/v1/phase 字样删文件。

## 2. 当前模块归属

| 模块位置 | 拥有的职责 | 当前处置 |
|---|---|---|
| api/v1、workers | HTTP/Arq/dispatcher 入站与命令转发 | KEEP；不能在这里复制业务与 Provider 执行规则 |
| access、assets | 工作空间、Project、Story/Scene/Shot、资产与版本 | KEEP；域模型不是临时 UI 状态 |
| director/assistant_*、proposal_*、story_* | 上下文、提案、显式部分接受 | KEEP；不自动创建媒体或 Formal |
| director/runtime、turn_*、invocation*、inbox*、wakeup* | 有界导演编排、引擎身份、恢复与信号 | KEEP；legacy/langgraph 是仍有调用的执行身份，不因命名而删 |
| director/creative_capabilities、workflows | 创作意图、模板、能力规划及镜头执行模板 | KEEP；逻辑职责与物理路径的整理另见待决问题 |
| production/application、execution_plan、workbench_execution | 类型化业务命令、授权、冻结计划、生产受理 | KEEP；用户生成/修复不能改走底层队列 helper |
| production/models、service、formal_selection、experiment_service、repair_service | Graph、当前 ExperimentBranch、显式 Formal、分步修复 | KEEP；当前实验创建已统一，不复活旧轨 |
| production/archive_models | 旧实验的历史存储映射 | ARCHIVE；只允许元数据注册，禁止运行时业务导入 |
| execution、runtime | NodeRun 执行、ProviderOperation/Artifact 血缘、调度与恢复 | KEEP；删除 HTTP helper 不删除内部 Worker 能力 |
| providers | Catalog/Manifest、编译、供应商 Runtime、连接/凭证版本、逻辑模型选择 | KEEP；不将名称含 bridge/legacy 的活跃实现当成死代码 |
| consistency、delivery、editing | 审核证据、人工决定、导出、EditSession | KEEP；视频证据需补桌面消费设计，不因缺入口删除 |
| events、security、storage | Outbox/死信/事件、加密与审计、对象存储 | KEEP；无直接 UI 不代表无消费者 |
| contracts | 共享业务命令、事实和 Runtime 端口 | KEEP；不引入第二份领域事实 |
| shared | 配置/DB/RLS/模型注册等公共设施 | KEEP 活跃设施；删除仅包装 stdlib 且无独立契约的死 helper |

当前源码仍使用这些物理目录；目标职责划分不等于已完成目录迁移。

## 3. 本轮已确定的能力处置

| 对象 | 产品判断 | 处置 |
|---|---|---|
| TEXT_LLM_* 直连配置 | 已由确认采用的实例 LiteLLM 合同取代 | 清理旧 knobs/helper/Compose 透传；保留真实网关配置、逻辑模型绑定与安全隔离 |
| dispatch/enqueue HTTP | 生成/修复/恢复已有业务命令，用户不应操作队列 | 退役 HTTP；保留 scheduler/Worker 与 qualified maintenance recovery |
| video-frames | 人工审片需要时间采样与参考对照 | KEEP + DESIGN；完整候选/修复证据消费方案见 API.md |
| ProductionExperiment/ShotExperiment | 当前实验已由 ExperimentBranch 拥有 | 隔离至 archive_models；保留表、迁移、RLS 与历史数据，不回接 UI |
| ExecuteKeyframeResult、_input_hash、shared/ids.py | 无独立用户能力；前者有 ExecuteNodeResult，后者只是未使用包装 | 删除别名/死函数，不改变当前执行 DTO 与 ID 策略 |
| checkpoint、Outbox、credential revision、reference token | 属恢复、隔离、投递和审计事实 | 保留，不按空表或缺前端按钮清空 |

视频设计尚未实现、历史表尚未物理删除，不能把本表解释成发布完成记录。

## 4. 尚未解决的结构问题

以下是有真实调用链的结构债务，不是本轮自动获准的大重构：

- Director 文本推理仍直接接触 Provider adapter；若收敛为 contract 端口，必须
  保留精确模型身份、冻结上下文、错误语义和测试 seam，不能用空壳转发掩盖依赖。
- workflows 中的执行模板、参与计划与引用能力跨 creative/production 职责；
  是否拆分物理路径需结合实际调用，不先大搬文件。
- creative_capabilities 的职责与 director 路径不完全一致；access/projects
  对 creative_templates 的依赖仍需明确是应用层注入还是允许的初始化依赖。
- ShotReferenceIntent 位于 production，而 contracts 引用它；迁移该契约需
  同步生产与编排调用，不只是重命名文件。
- Provider 对 execution.models 的事实依赖，与对 production/runtime 业务的
  依赖应分别判断；在修改 MODULE_BOUNDARIES 规则前，不把现状自动宣告合规。
- shared/db 的 RLS 上下文和 model_registry 的全图注册是组合根性质，不能因为
  shared 理想上是叶子层，就删除这些有消费者的基础设施。
- golden_project 是证明/测试种子而非产品入口；迁出前要核对证明脚本，不因
  位置看起来旧就删除测试资产。
- 历史 shot_experiment_id 字段与冻结计划序列化仍需做兼容审计，再设计前向迁移。

## 5. 可重复核查与门禁

先构建当前源码的 quality image，再运行已有信息性扫描：

    docker compose -f docker-compose.quality.yml build backend-quality
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality python scripts/arch_import_scan.py --matrix
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality python scripts/arch_import_scan.py --violations

该扫描只报告 import 结构，退出 0 不代表不存在架构违规或产品缺口。
静态图也不能独自证明反射、注册、HTTP、Worker 或仓库外调用已不存在。

现有硬门分别负责：canonical-surface 禁止已退役入口与归档模型回流；Provider
权威 map 检查旧 Adapter 缺席和替代实现存在；OpenAPI generated client 检查契约；
PostgreSQL metadata/CHECK/enum 与 RLS 集成测试检查迁移和隔离；完整容器门见
DEVELOPMENT.md。上述检查不能用修改错误期望或仅靠文件数量下降替代。
