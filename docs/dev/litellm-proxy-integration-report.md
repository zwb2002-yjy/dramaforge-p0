# DramaForge 当前 dev LiteLLM Proxy 集成修复 — 实现报告

> 来源：`DramaForge_LiteLLM_Proxy_Current_Dev_Fix_Spec_for_DS.md`（§130 输出要求）。
> 完成日期：2026-08-11。分支 `dev`。
> Gap Analysis：`docs/dev/litellm-proxy-current-dev-gap-analysis.md`（F0 强制产物）。
> BYOK Decision：`docs/dev/litellm-byok-decision.md`（F11）。

---

## 1. 结论

当前 dev 的 LiteLLM 集成已闭环：**DramaForge 不装 litellm SDK**，官方
`ghcr.io/berriai/litellm:v1.96.0` 作为独立 Proxy Runtime 由 Docker Compose 启动，DramaForge
通过 HTTP 调用其 OpenAI-compatible 表面。LiteLLM Router 拥有 provider/deployment 的
retry/fallback/cooldown；DramaForge 一次 POST、错误分类、SUBMIT_UNKNOWN、成本 Header、
逻辑别名（script-quality / script-fast / legacy-text）与真实 Proxy 集成测试全部落地。

**真实 Proxy integration test 通过**（DramaForge → Real Proxy → Router → mock 多 deployment，
6 项全过）。**未做真实 Provider E2E**（无 Provider Key，按 spec §111/§129-34 明确报告）。

---

## 2. 交付对照（DoD §129，34 项）

| # | DoD | 状态 | 落点 |
|---|---|---|---|
| 1 | 无 litellm pip 依赖 | ✅ | pyproject 无 litellm；`test_backend_never_imports_litellm_sdk`（§116） |
| 2 | Compose 有真正 LiteLLM Proxy | ✅ | `docker-compose.yml` `litellm` service |
| 3 | 官方 image | ✅ | `ghcr.io/berriai/litellm:v1.96.0`（BerriAI 官方） |
| 4 | 镜像 pinned | ✅ | tag v1.96.0 + digest `sha256:90d8de0e…f672`；`LITELLM_IMAGE` 可覆盖 |
| 5 | healthcheck | ✅ | `/health/liveliness`（python urllib，不探 /health，§12/§128-8） |
| 6 | 独立持久 DB | ✅ | `litellm-db`（postgres:15-alpine，独立库 litellm） |
| 7 | .env.example 完整 | ✅ | LITELLM_GATEWAY_URL/API_KEY/MASTER_KEY/DB_PASSWORD/IMAGE + 别名部署 env |
| 8–10 | API/Worker-default/Worker-heavy 收 URL+Key | ✅ | 三者注入 `LITELLM_GATEWAY_URL`/`LITELLM_API_KEY`/`TEXT_V3_ROUTER_ENABLED`/`LITELLM_LOGICAL_MODELS` |
| 11 | Gateway URL path 规范统一 | ✅ | `/v1/chat/completions`（client normalize，§19–§21） |
| 12 | 无三次 blind retry | ✅ | 单次 POST；`test_litellm_adapter_single_attempt_on_gateway_503`（§117） |
| 13 | Router 负责 retry | ✅ | config `router_settings.num_retries`；DramaForge 不重试 |
| 14 | 业务幂等 | ✅ | CreationService agent 级 attempt + NodeRun idempotency（未改动） |
| 15 | SUBMIT_UNKNOWN | ✅ | read timeout after submit → `GenerationStatus.SUBMIT_UNKNOWN` + op `unknown_submission` |
| 16 | HTTP 抽成 Client | ✅ | `LiteLLMGatewayClient`（§66–§70） |
| 17–19 | Client readiness/list_models/chat_completion | ✅ | client.py |
| 20 | /v1/models 可读 | ✅ | `list_models()` + TTL cache（§35/§36） |
| 21 | ≥1 逻辑别名 | ✅ | script-quality / script-fast / legacy-text |
| 22 | 别名可对多个 deployments | ✅ | 集成 config 两个 script-quality deployment，Router 接受（§115） |
| 23 | Profile 可选逻辑 model | ✅ | `litellm/script-quality` 静态注册；`binding_reads` 显示 configured |
| 24–26 | Brief/Script/Storyboard 走 LiteLLM | ✅ | `TEXT_V3_ROUTER_ENABLED=true` 时 resolver→router→adapter；E2E 证明 brief |
| 27 | 成本 Header 可读 | ✅ | `x-litellm-response-cost(-original)` → provider_metadata → op.provider_cost |
| 28 | retry/fallback metadata 可读 | ✅ | allowlist headers（§47/§48） |
| 29 | Secret 不进日志 | ✅ | allowlist 不含 authorization；`test_litellm_adapter_records_allowlisted_metadata` |
| 30 | BYOK 迁移文档 | ✅ | `docs/dev/litellm-byok-decision.md` |
| 31 | Legacy 路径在 flag 后 | ✅ | `TEXT_V3_ROUTER_ENABLED` 默认 false；legacy 未删 |
| 32 | Real Proxy integration test | ✅ | `tests/integration/test_litellm_real_proxy.py` 6 项本地全过 + CI job |
| 33 | Real LLM Smoke Test | ❌ 无 Key | 未做（mock 已证明运行时链路；无 Key 不宣称真实 E2E） |
| 34 | 无 Key 时明确报告 | ✅ | 本报告 §6 |

---

## 3. 版本与官方核对（spec §132）

| 项 | 值 |
|---|---|
| GitHub release | `BerriAI/litellm` `v1.96.0`（2026-08-10） |
| Docker image | `ghcr.io/berriai/litellm:v1.96.0` |
| digest | `sha256:90d8de0ea6fbb3cad145d1019d00a0149ae400b1e18e2011a60f1988f143f672` |
| 核对日期 | 2026-08-11（`infra/litellm/compatibility.md` 记录实测行为） |
| 版本 tag 约定 | 新版为 `vX.Y.Z`（旧 `main-vX.Y.Z` 不存在） |

## 4. 改动清单

**基建 / 配置**
- `docker-compose.yml`：`litellm-db` + `litellm` services、volume `litellm_db_data`、
  api/worker-default/worker-heavy 注入 Gateway env、`NO_PROXY` 加 litellm/litellm-db。
- `infra/litellm/config.yaml`（逻辑别名 + router_settings + general_settings）、`README.md`、`compatibility.md`。
- `.env.example`：LiteLLM 全量配置（§24）。

**后端**
- `app/config.py`：`litellm_text_gateway_model`（解耦 TEXT_LLM_MODEL）、`litellm_logical_models`、
  `litellm_discovery_startup`。
- `app/providers/litellm_gateway/`（新）：`client.py`（GatewayClient + GatewayResponse + URL normalize）、
  `errors.py`（分类）、`metadata.py`（allowlist）、`model_catalog.py`（逻辑别名 manifest + discovery sync）。
- `app/providers/litellm_adapter.py`：改走 GatewayClient、单次 POST、SUBMIT_UNKNOWN、成本/元数据。
- `app/providers/bootstrap.py`：transport path `/v1/chat/completions`；text-llm bootstrap bridge
  （legacy_compat）；默认注册 script-quality/script-fast。
- `app/providers/selector.py`：system default 优先 bootstrap bridge。
- `app/creation/service.py`：错误分类 + `unknown_submission` 持久化 + 真实成本。
- `app/main.py`：`/health` 增加 `dependencies.litellm`（不因 LiteLLM down 变 unhealthy）。

**测试**
- `tests/unit/test_litellm_gateway_client.py`（新，19 项）：URL normalize / chat 单次 /
  错误分类 / SUBMIT_UNKNOWN / cost metadata / list_models TTL / 逻辑别名 / bootstrap bridge /
  catalog sync / no-SDK。
- `tests/unit/test_litellm_text_bridge.py`：路径 `/v1`、去 retry、加分类与元数据测试。
- `tests/unit/test_v3_registry.py`：逻辑别名 adapter 断言。
- `tests/integration/test_litellm_real_proxy.py`（新，6 项）：真实容器全链 + F14 brief E2E。
- `.github/workflows/ci.yml`：新增 `litellm-integration` job（预拉镜像 + REQUIRED=1）。

## 5. Model List / Router Settings

```yaml
model_list:
  - script-quality  → openai/script-quality-deployment（api_base/key 或 mock_response 由 env 注入）
  - script-fast     → openai/script-fast-deployment
  - legacy-text     → openai/legacy-text-deployment（litellm/text-llm bridge 目标）
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  request_timeout: 120
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  drop_params: false          # strict（§62）
  enable_response_cost_headers: true
```

## 6. BYOK 状态

Phase 1（本轮）：LiteLLM 用 `os.environ/<KEY>` 管 Provider Key（系统默认模型）；DramaForge
用 Virtual/Master Key 调 Gateway。DramaForge Credential Store 仍是 BYOK source of truth。
Phase 2（workspace clientside credentials）未实现——`docs/dev/litellm-byok-decision.md` 明确路线与
「不静默忽略旧 BYOK」约束。旧 `TEXT_LLM_*` 文本 BYOK 在 `TEXT_V3_ROUTER_ENABLED=false`（默认）下
仍是生产路径。

## 7. Real Proxy Integration 结果（本地实测 2026-08-11）

```
tests/integration/test_litellm_real_proxy.py 6 passed
  - proxy readiness（/health/liveliness + /health/readiness 200）
  - /v1/models 含 script-quality / script-fast
  - /v1/chat/completions 返回 mock + usage + x-litellm headers
  - DramaForge adapter → Real Proxy → Router → mock deployment（SUCCEEDED + cost metadata）
  - 未知 model → gateway 400 → adapter model_unavailable
  - F14：TEXT_V3_ROUTER_ENABLED=true 下 CreationService brief 经真实 Proxy 生成成功
```

## 8. 质量证据

- backend unit：**537 passed** / 0 failed。
- backend integration：**20 passed**（PG 迁移链 + 真实 Proxy 6 项）。
- ruff：app + tests 全绿；mypy：**154 源码无错**。
- `docker compose config`：通过。
- frontend：本轮未改动（模型选择器经 /api/v1/models 自动获得逻辑别名，无前端代码变更）。

## 9. Remaining risks / 未做项

1. **真实 Provider E2E 未跑**（无 Key）：mock_response 证明 Proxy 运行时链路；有 Key 后按 spec §111
   执行 `DramaForge → LiteLLM → 实际 LLM` 低成本请求并记录 cost/headers。
2. **media 未进 LiteLLM**：MiniMax/Volcengine Image/Video 仍走 native A+B；等 LiteLLM Fork provider
   module 完成后接入（spec §7/§124/§125），DramaForge 只扩 `api_mode`。
3. **Virtual Key / workspace attribution**（spec §57/§58）为 P1；compose 用 master key 可运行。
4. **`LITELLM_DISCOVERY_STARTUP` 默认 false**：生产接线需开启或显式调用 `LiteLLMModelCatalogSyncService`。
5. **legacy 文本路径**待 flag 翻转 + 生产文本稳定后删除（F15，spec §113）。

## 10. LEGACY_COMPAT 清单

| 遗留项 | 现状 | 解除条件 |
|---|---|---|
| `creation/service.py` legacy 文本路径 | `TEXT_V3_ROUTER_ENABLED=false` 时走 `get_openai_adapter_for_workspace` | flag 翻转 + 生产文本稳定后删除 |
| `litellm/text-llm` bootstrap bridge | `gateway_model=litellm_text_gateway_model`（默认 legacy-text），标 `legacy_compat`+`bootstrap_bridge` | 新 Profile 改用 `litellm/script-quality` 等逻辑别名后退役 |
| Workspace 文本 BYOK（TEXT_LLM_*） | flag 开时走 Gateway Virtual Key，workspace 级 Key 不生效 | Phase 2 clientside credentials（BYOK-2） |
| media 选择 | 仍由 A+B `ModelSelectionService` 权威 | LiteLLM 媒体接入 |
