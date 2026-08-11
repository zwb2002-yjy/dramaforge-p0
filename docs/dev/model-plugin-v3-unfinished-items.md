# DramaForge 模型能力插件化 V3 — 未完成项汇总

> 目的：汇总「上轮：V3 Phase 0–12 实现轮（`84bd03b`/`0131009`/`fd3c349`）」与「本轮：1.md 评审修复轮（`0a07bac`）」中经确认**尚未完成**的项目，每项附性质、原因/依据、解除条件与归属阶段，作为 P1/P2 排期与发布验收的输入。
> 更新日期：2026-08-11
> 相关文档：`docs/dev/model-plugin-v3-gap-analysis.md`（Phase 0 审计）、`docs/dev/model-plugin-v3-implementation-report.md`（实现报告）、`docs/开发执行检查点.md` §5.2

---

## 1. 上轮（V3 Phase 0–12 实现）遗留未做项

| # | 项 | 性质 | 现状 | 原因/依据 | 解除条件 | 归属 |
|---|---|---|---|---|---|---|
| L1 | B6：删除 legacy 媒体路径 | 决策延后 | 旧 Flux/Kling getter（`flux.py`/`kling.py`）、`product_path.py` legacy 分支（`PROVIDER_UNIFIED_PATH_ENABLED` 门控）、前端 `ProviderConnectionPanel` 硬编码模型快捷按钮仍在 | A+B 检查点要求：生产切 unified 稳定后再清理；`test_v3_boundary.py` 将其钉死为 LEGACY_COMPAT | flag 翻转且新提交稳定后删除 | P0 收口后 |
| L2 | text.generate 未接入 V3 | 未做 | `creation/service.py` 的 Agent Brief/Plan 仍走 `get_openai_adapter_for_workspace`（LEGACY_COMPAT） | 需 V3 文本模型 compiler + manifest，未排期 | 建 text 模型 bridge 并切到 CapabilityRouter | P1 |
| L3 | Provider B 用 Agnes 而非 MiniMax/Hailuo | 偏差（已记录） | 第二 Provider 为 `agnes/agnes_cn_v1` | V3 §69 建议 Seedance + MiniMax/Hailuo；真实仓库第二个已完成的是 Agnes，§69.2 双 Provider 验收已通过 | 接 MiniMax/Hailuo 完整能力 | P1 |
| L4 | PG integration + 完整 7-job CI 未重跑 | 未做 | 仅本地 unit（458）+ ruff + mypy 绿；`postgres-integration`（真实 PG）与远端 CI 未在干净候选上跑 | 未排期 | 发布前在干净候选重跑 | 发布 |
| L5 | video 独立生成未开放 | 范围决策 | 独立 Generation API 仅支持 `image.generate`；video 模式 422 拒绝并指向 Shot pipeline | video 需 face gate 链（keyframe → face → video），独立开放会绕过门禁 | 产品需要独立 video 生成且门禁可复用时 | P1 |
| L6 | `ProviderConnectionPanel` 硬编码 agnes 模型快捷按钮 | 未做 | Phase 10 完成 manifest 驱动渲染，但该面板的 model-binding 快捷创建仍硬编码 `agnes-image-2.1-flash` / `agnes-video-v2.0` | Phase 10 范围未覆盖该面板 | 改为 registry/manifest 驱动 | P1 |
| L7 | ProviderOperation 独立列未迁移 | 决策延后 | `requested_capability`/`transport_profile_id`/`translation_report` 等暂存于 `request_summary`/`response_summary` JSON | 最小迁移，避免破坏运行链；enum 已含 `unknown_submission`/`submission_started`，无需迁移 | 随 fallback（1:N ProviderOperation attempt）一起迁移 | P1 |
| L8 | ExecutionFingerprint（§47） | 未做 | 未实现 | V3 §47 标 P0 可选、P1 推荐 | 需要审计/回放/成本分析时 | P1 |
| L9 | GenerationPolicy / fallback / health-aware / cost-aware routing（§36/§37） | 未做 | 未实现；P0 不自动 fallback | P0 决策 | 有 fallback 需求时 | P1 |
| L10 | Agnes 拆分子包（`client/transports/adapters/plugin`） | 可选重构 | `agnes.py` 单文件保留；provider/model 身份分离已通过 `test_v3_identity.py` 验证 | 最小迁移原则；Phase 7 记录为可选偏差 | 无硬性阻塞，纯结构整理 | 可选 |
| L11 | ProtocolModelSpec / best-effort / manifest version snapshot / 自定义 endpoint 映射 | 未做 | 未实现 | V3 §62/§72 P1 扩展 | 有聚合 Provider / 自定义 API 需求时 | P1 |

---

## 2. 本轮（1.md 评审修复）未做项

| # | 项 | 性质 | 现状 | 原因/依据 | 解除条件 | 归属 |
|---|---|---|---|---|---|---|
| R1 | TranslationReport 仍是空壳 | 缺陷（明确 P1） | `adapters_v2.py` `TranslationReport(requested_options, effective_options=requested_options)` —— requested==effective，transformations/warnings 为空；A+B Compiler 实际发生的参数归一化/字段映射/ratio 调整/默认值补充未写入 report | 1.md 原文：「这可以 P1 补，不一定挡 P0」 | bridge 从 compiler 收集实际变换写入 TranslationReport；补翻译审计测试 | P1 |
| R2 | B6 legacy 清理（继承 L1） | 决策延后 | 本轮未动 | 上轮决策保持门控 | 同 L1 | P0 收口后 |
| R3 | text.generate V3 bridge（继承 L2） | 未做 | 本轮未动 | 未排期 | 同 L2 | P1 |
| R4 | PG integration + CI 重跑（继承 L4） | 未做 | 本轮未动 | 未排期 | 同 L4 | 发布 |

> 说明：1.md 的 BLOCK-1~4 与 HIGH-1~4 **本轮全部修复并有测试**；上表 R2–R4 是上轮遗留项在本轮未触及的部分，R1 是 1.md 唯一显式保留到 P1 的项。

---

## 3. 已确认完成（对照基准）

- 本轮：BLOCK-1（幂等 input_hash 比较 + race 恢复）、BLOCK-2（revision 入指纹 + 契约驱动序列化）、BLOCK-3（validator 执行 ParameterSpec）、BLOCK-4（resolver URL/bytes 真正传递到 compiler）、HIGH-1（未知状态显式报错）、HIGH-2（durable token provider）、HIGH-3（transport id 从注册表解析）、HIGH-4（按 media_kind 选模型）。
- 质量：backend unit **458 passed / 0 failed**，ruff + mypy 全绿（138 源码）；frontend lint/typecheck 干净，vitest **22 passed**。
- 未触碰 `main`（按用户要求不 merge）；`dev` 已推送。

---

## 4. 建议优先级

1. **R1 TranslationReport** —— 本轮唯一显式 P1，也是 1.md 点名的「骨架 vs 真实审计」差距；改动局部（bridge 收集变换）。
2. **L2/R3 text bridge** —— 打通文本路径后业务层才真正「只通过 CapabilityRouter 调模型」，消除最后一项 LEGACY_COMPAT 行为。
3. **L1/R2 B6 清理** —— 依赖生产切 unified 稳定；删除后 legacy getter 与前端硬编码一起收口。
4. **L4/R4 CI 重跑** —— 发布验收必经，独立于上述功能项。
5. **L7 ProviderOperation 列迁移** —— 建议与 P1 fallback（1:N attempt）一并做，避免两次迁移。

---

## 5. 与 P0 候选版的关系（非 V3 范围，仅提示）

`docs/开发执行检查点.md` 中的 P0 候选版质量阻塞（视频末帧漂移门禁「先不做」、TTS 音质选型未定）按产品决定延后，**不属于**模型插件化 V3 的未完成项；V3 收尾（B6 清理、CI 重跑）完成后仍需在干净候选上重验 P0 正式 Gate。
