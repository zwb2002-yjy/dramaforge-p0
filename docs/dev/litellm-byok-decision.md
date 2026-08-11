# LiteLLM 与 Workspace BYOK — 决策（F11）

> 来源：`DramaForge_LiteLLM_Proxy_Current_Dev_Fix_Spec_for_DS.md` §49–§59/§107/§108。
> 日期：2026-08-11。分支 `dev`。

---

## 1. 结论

**DramaForge Credential Store 仍是用户 BYOK 的 Source of Truth；LiteLLM 只是 execution
gateway**（fix spec §50）。本轮（Phase 1）不迁移 Workspace BYOK 到 LiteLLM 的
clientside credentials；`TEXT_LLM_*` 旧 BYOK 路径保留在 `TEXT_V3_ROUTER_ENABLED=false`
（默认）后（LEGACY_COMPAT）。不得宣称 Workspace BYOK 已迁移（fix spec §54/§108）。

## 2. 现状（2026-08-11）

| 凭据 | 存放 | 当前使用 |
|---|---|---|
| Agnes BYOK | `encrypted_provider_credentials`（Fernet）+ `ProviderConnection` | A+B 媒体执行（native） |
| Volcengine BYOK | 同上 | A+B 媒体执行（native） |
| Text LLM BYOK | `TEXT_LLM_*`（settings，进程级） | legacy OpenAI 文本路径 |
| LiteLLM Gateway | `LITELLM_GATEWAY_URL` + `LITELLM_API_KEY`（settings） | V3 文本桥（flag 开时） |

`security/credentials.py` + `byok_keyring.py`：Fernet 加密、keyring 版本轮换、
`ProviderConnection.credential_id → encrypted_provider_credentials`。

## 3. 两阶段

### Phase BYOK-1（本轮）— Gateway-managed Provider Key + DramaForge Virtual Key

```text
LiteLLM（config.yaml os.environ/<KEY>）管理 Provider Key（系统默认模型）
DramaForge 用 dedicated Virtual Key（LITELLM_API_KEY）调用 Gateway
DramaForge Credential Store 仍是 BYOK 的事实来源；LiteLLM 不持久化用户 BYOK
```

- 适用范围：系统默认 / 非 workspace 特定模型。
- 必须：`LITELLM_API_KEY` 用 Virtual Key，不长期用 `LITELLM_MASTER_KEY`（spec §57/§128-6）。
- 必须：`LITELLM_MASTER_KEY` 只进 litellm service，不进 api/worker（spec §23/§128-5）。
- 必须：Secret 不进 log / request_summary / TranslationReport / ProviderOperation /
  fingerprint（spec §53/§121）。

### Phase BYOK-2（未排期）— Workspace Clientside Credential

```text
Workspace → ProviderConnection → CredentialResolver → 解密 Provider Key
→ 构造 LiteLLM clientside credential config（user_config / user model config）
→ 请求带独立 Key → LiteLLM → Provider
```

- 每 Workspace 独立 Key（spec §52/§55）。
- 需按 pinned LiteLLM 版本核对 `user_config` HTTP schema（spec §51）——本轮不做。
- 媒体（MiniMax/Volcengine）仍在 native A+B 路径，不经过 LiteLLM，BYOK-2 只影响文本。

## 4. 边界与限制（本轮必须明确）

1. **TEXT_LLM 旧 BYOK 未迁移**：`TEXT_V3_ROUTER_ENABLED=false` 时 brief/plan 走 legacy
   OpenAI adapter（`TEXT_LLM_*`）。flag 翻转后走 Gateway（Virtual Key），此时
   workspace 级文本 BYOK 不再生效——需在 UI/文档标注（fix spec §108 不允许静默忽略）。
2. **每 Workspace 一个 Proxy 不可取**：单中央 Gateway 足够（spec §56）。
3. **LiteLLM DB 不回答业务账本问题**：`这个 Shot 花了多少钱` 仍由 DramaForge
   ProviderOperation / CostLedger 回答（spec §59）；LiteLLM Spend 只是旁证。
4. **成本来源**：`x-litellm-response-cost`（gateway 计算）→ adapter metadata →
   ProviderOperation.provider_cost（spec §46）。
5. **Virtual Key attribution**（workspace/project → LiteLLM spend 分析）未实现（P1，
   spec §58/§133）。Phase 2 一并做。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| Gateway down 时 V3 文本不可用 | API 不硬依赖 litellm（spec §122）；`/health` 报 `dependencies.litellm=unavailable`；媒体仍可用 |
| Virtual Key 泄露 | 环境/Secret Manager 注入；禁止写进 git；redact 审计 |
| TEXT_LLM BYOK 用户在 flag 翻转后 Key 失效 | flag 默认 false；文档 + UI 提示；Phase 2 迁移工具 |

## 6. 验收

- [x] `docs/dev/litellm-byok-decision.md` 存在（本文件）。
- [x] 未静默忽略旧 BYOK：legacy 路径保留 + flag 后回退语义明确。
- [ ] Phase 2 clientside credentials 实现（未排期，触发条件：workspace 级文本 BYOK 需求）。
