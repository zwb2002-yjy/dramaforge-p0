# DramaForge 开发入口

本文件仅为编码 Agent 导航，不定义产品范围或发布 Gate。

开始任何改动前依次读取：

1. `AGENTS.md`；
2. `DramaForge总开发文档.md`；
3. `docs/README.md`；
4. 与当前任务相关的 `docs/current/` 合同；
5. `docs/开发执行检查点.md` 中的实时实现事实。

根目录 `01_项目总需求.md` 至 `06_受控混合Agent运行时规范.md`、旧实施规划、旧 P0 验收方案和历史 ADR 只用于追溯，不能产生新任务或恢复已废止设计。

## 当前产品与运行时边界

- 首版产品是面向零基础个人创作者的四阶段 AI 导演工作台。
- 一个受控 AI 导演按已发布、版本化模板调用原子 Skill，不运行自由聊天式多 Agent。
- Director Workflow 管理创作版本、确认、预算、试拍、Issue 和修复；Production Graph 管理镜头级媒体任务、血缘与局部重跑。
- 快速模式与专业模式必须共享同一个 Project、版本、Production Graph、Artifact、成本和审核事实。
- 任何 LLM 输出都只是结构化提案；不能直接写业务事实、提交收费媒体请求、绕过 Gate 或拼装供应商请求。

## 人物一致性合同

首版不集成人脸生物特征识别、自动身份相似度或阈值 Gate，也不保留相应可选插件入口。

固定证据链：

```text
Canonical Character Asset
→ Shot Reference Binding
→ Provider Capability
→ EffectiveRequest / TranslationReport
→ Generated Artifact
→ identity_review
→ 视频首/中/末帧证据
→ 用户试拍验收
→ Issue / 局部修复
```

`identity_review` 只检查 Canonical、生成产物和参考血缘是否完整：缺任一来源或两源 payload 相同均为 `blocked`；两份独立证据齐全时为 `needs_human`。没有经过许可、校准和发布决策的可信视觉评估器时，不得自动声称人物一致或自动放行。

视频生成直接依赖关键帧，不依赖人物复核自动通过；人物与时序复核是并行证据。主观接受必须形成 `subjective_gate_override`，保留原因、范围、质量报告版本和操作者。

## 工程边界

- 后端：Python 3.12、FastAPI、Pydantic v2、SQLAlchemy async、Alembic、PostgreSQL、Redis/Arq、MinIO、FFmpeg。
- 前端：React、TypeScript、Vite、TanStack Router/Query；服务端事实不得放进仅 UI 状态。
- 调用边界：Route → Service → Repository/Domain；业务代码通过 Transactional Outbox 和调度层触发 Worker。
- Provider 必须保存能力选择、脱敏后的 EffectiveRequest、TranslationReport、引用资产和 Artifact 血缘；必需参数丢失时 fail closed。
- Artifact 二进制只进入对象存储；数据库保存对象键、哈希、元数据和血缘。
- GraphVersion、创作版本、质量策略和确认记录不可原地覆盖；修改产生新版本并计算影响范围。
- 数据合同变更必须同步迁移、ORM、Schema、前端类型、fixture 和测试。
- 不提交密钥、完整供应商响应、永久对象 URL 或敏感内容。

## 常用验证

```powershell
cd backend
uv run ruff check app tests
uv run mypy app
uv run pytest -q

cd ..\frontend
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test
npm.cmd run build

cd ..
git diff --check
```

真实 Provider、预算、质量或发布成功只能按实际证据报告；mock、Spy、单元测试和历史样本不能冒充当前真实链路。不要提交、推送、创建 PR 或触发付费调用，除非用户明确要求并授权。
