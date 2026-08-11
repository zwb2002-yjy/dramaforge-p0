# LiteLLM Proxy 当前 dev 集成缺口分析（F0）

> 来源：`DramaForge_LiteLLM_Proxy_Current_Dev_Fix_Spec_for_DS.md`（§85/§86）。
> 审计日期：2026-08-11。分支 `dev`，HEAD `72cbf41`。
> 执行对象：DSV4 Flash / Coding Agent。

---

## 1. 结论

当前 dev 的设计方向（`LiteLLMModelAdapter → HTTP → LITELLM_GATEWAY_URL`）正确，且没有把
`litellm` SDK 装进 backend（pyproject 无该依赖）。但集成**未闭环**：缺少真实 LiteLLM Proxy
Runtime、Compose env wiring、`.env.example`、统一 `/v1` 路径、Gateway Client 拆分、单层 retry、
成本 Header、错误分类/SUBMIT_UNKNOWN、logical model alias 与真实 Proxy Integration Test。

按规范 §127，BLOCKER 为 B1（Compose 无 litellm service）、B2（Compose env wiring）、
B3（.env.example）、B4（真实 Proxy integration test）。

---

## 2. 逐项确认（规范 §86 的 12 项）

| # | 检查项 | 现状 | 缺口 |
|---|---|---|---|
| 1 | `LiteLLMModelAdapter` 当前路径 | `backend/app/providers/litellm_adapter.py`（Generic adapter，httpx 直连） | 全部 HTTP 逻辑混在 adapter；`_chat_url()` 拼 `/chat/completions` 而非 `/v1/chat/completions`；内置 `_MAX_ATTEMPTS = 3` blind retry（对 408/429/500/502/503/504 + network/timeout） |
| 2 | pyproject 是否有 `litellm` dependency | ✅ 无（`backend/pyproject.toml` 无 litellm） | 无 |
| 3 | docker-compose 是否有 litellm service | ❌ 无 `litellm` / `litellm-db` | **BLOCKER-1**：`LITELLM_GATEWAY_URL` 默认无真实目标 |
| 4 | `.env.example` 是否有 LiteLLM env | ❌ 无 `LITELLM_*` 条目 | **BLOCKER-3** |
| 5 | Settings 中 LiteLLM 字段 | ✅ `litellm_gateway_url`、`litellm_api_key`、`text_v3_router_enabled`（`config.py` §131–§140） | `gateway_url` description 仍是 `https://gateway.example` 风格；需补充 logical model 配置与 Gateway 相关字段 |
| 6 | Text V3 flag | ✅ `TEXT_V3_ROUTER_ENABLED` 默认 False（合理迁移策略，spec §3.4） | 保持；本轮在 dev/test 验证 True 时全链路由（F14） |
| 7 | 当前 LiteLLM text manifest | `bootstrap.py`：`LITELLM_TEXT_MODEL_ID = "litellm/text-llm"`；`litellm_text_manifest()` 暴露 `text.generate`，`transport_profile_id="litellm-chat-v1"` | 未标记 bootstrap bridge / LEGACY_COMPAT；无 logical alias（script-quality / script-fast） |
| 8 | 当前 `gateway_model` 来源 | `gateway_model = settings.text_llm_model`（`litellm_text_manifest()`） | **H5**：长期把 gateway_model 绑定 `TEXT_LLM_MODEL` 违背 spec §33/§104（logical alias 是核心价值） |
| 9 | 当前 retry count | `_MAX_ATTEMPTS = 3`，`_RETRYABLE_STATUSES = {408,429,500,502,503,504}` + network/timeout，指数退避 | **H1**：DramaForge retry × LiteLLM Router retry 形成请求放大；spec §5/§96 要求一次 POST |
| 10 | 当前 cost handling | `fetch_cost()` 返回 `amount=None`；`_text_call_cost` 对 V3 路径 amount=0 | **H3**：未读 `x-litellm-response-cost`；成本应来自 Gateway 响应 Header（spec §43–§46） |
| 11 | 当前 Workspace BYOK | DramaForge Credential Store（Fernet 加密）+ `ProviderConnection`；LiteLLM 尚未参与 | 无 `litellm-byok-decision.md`；未明确 Phase 1 Gateway-managed / Phase 2 clientside 路线（spec §49–§55，F11） |
| 12 | 当前 Agent Brief/Plan migration | `creation/service.py::_run_text_llm_attempt` 按 flag 分支：V3 路径 resolver→router→adapter，legacy 走 OpenAI adapter；Brief/Plan 均可走 LiteLLM（flag 开时） | 非 SUCCEEDED 一律 RuntimeError→op failed；需映射 `error_code` 与 SUBMIT_UNKNOWN（spec §63–§65，F6） |

---

## 3. 额外确认（规范 §19/§20/§21/§77/§86 延伸）

| 项 | 现状 |
|---|---|
| TransportProfile `litellm-chat-v1` | `bootstrap.py` §176–§184：`path_template="/chat/completions"`。若统一 `/v1` 规范，须改为 `/v1/chat/completions`，且 adapter 与 transport 保持一致（spec §21） |
| `/health` | `app/main.py` §50–§79：仅 DB 探活，无 `dependencies.litellm` detail。spec §77/§122：LiteLLM down 不应使 API unhealthy；需新增依赖 detail |
| Model availability | `binding_reads`（`model_profiles/service.py` §520–§528）对 provider=`litellm` 用 gateway settings 判定 configured（已有）；spec §78/§79：P0 只要求 URL+Key configured |
| ModelDiscovery | 无 `LiteLLMGatewayClient.list_models()`；无 TTL cache；无 catalog sync（spec §35–§40，F8） |
| Profile 对接 logical alias | `ProductionModelProfile` 已能绑定任意 registry model_id（`planning.brief/script/storyboard`），但 registry 目前只有 `litellm/text-llm` 一个文本模型（spec §41/§42，F10） |
| 媒体 | 本轮不动 MiniMax/Volcengine Image/Video（spec §84/§125）；`ModelBackendBinding.api_mode` 预留 image/video gateway modes（models.py §71–§90） |

---

## 4. 需修复/新增清单（对应规范 F1–F15）

1. **F1** `docker-compose.yml`：新增 `litellm-db`（postgres 独立库）+ `litellm`（官方 pinned image + healthcheck `/health/liveliness`）；api/worker 不硬依赖 litellm（spec §13）。
2. **F2** `infra/litellm/config.yaml`：`model_list`（`script-quality` / `script-fast` logical alias）+ `router_settings` + `general_settings.master_key=os.environ/LITELLM_MASTER_KEY`；`infra/litellm/README.md` + `compatibility.md`。
3. **F3** `.env.example` 补全 `LITELLM_GATEWAY_URL` / `LITELLM_API_KEY` / `LITELLM_MASTER_KEY` / `LITELLM_DB_PASSWORD` / `LITELLM_IMAGE`；compose `api`/`worker-default`/`worker-heavy` 注入 Gateway URL/Key；`NO_PROXY` 加 `litellm,litellm-db`。
4. **F4** 抽取 `backend/app/providers/litellm_gateway/`：`client.py`（readiness/list_models/chat_completion + GatewayResponse）、`errors.py`（错误分类）、`metadata.py`（allowlisted headers）、`model_catalog.py`（discovery + TTL + registry sync）。Adapter 不再直接 httpx.post。
5. **F5** 删除 `_MAX_ATTEMPTS = 3` 通用 blind retry；一次 POST（P0）。
6. **F6** 错误分类：connect→gateway unavailable；401/403→auth_failed；404→model_unavailable；429→rate_limited；5xx→provider/gateway_unavailable；read timeout after submit→SUBMIT_UNKNOWN；`_run_text_llm_attempt` 把 `unknown_submission` 写入 op.status。
7. **F7** 解析 `x-litellm-response-cost` / `-attempted-retries` / `-attempted-fallbacks` / `-response-duration-ms` / `-overhead-duration-ms`（allowlist，无 secret）进 provider_metadata；`_text_call_cost` 从 metadata 取真实成本。
8. **F8/F9/F10** `list_models()` + TTL cache；`litellm/text-llm` 标记 bootstrap bridge（LEGACY_COMPAT）；支持 `litellm/script-fast`、`litellm/script-quality` logical alias（静态注册 + discovery sync）；Profile `planning.script → litellm/script-quality` 全链走 CapabilityRouter。
9. **F11** `docs/dev/litellm-byok-decision.md`：Phase 1 Gateway-managed（DramaForge Credential Store 仍是 BYOK source of truth，LiteLLM 仅 execution gateway）+ Phase 2 clientside credentials。
10. **F12** 真实 LiteLLM Proxy container integration test（`DramaForge → Real Proxy → Mock/OpenAI-compatible fixture`）。
11. **F14/F15** dev/test 验证 `TEXT_V3_ROUTER_ENABLED=true`；legacy 路径保留在 flag 后（不删 `TEXT_LLM_*`）。

## 5. DoD 对齐（规范 §129，34 项）

未达成项：#2（Compose 无 Proxy）、#3/#4（image 未 pin）、#5/#6（healthcheck/独立 DB）、#7/#8/#9/#10（env.example + API/Worker 注入）、#11（path 规范）、#12/#16（blind retry / client 拆分）、#17/#18/#19（client 方法）、#20/#21/#22（/v1/models、logical alias、多 deployment）、#23/#24/#25/#26（Profile 选 logical model + Brief/Script/Storyboard 走 LiteLLM）、#27/#28（cost/retry metadata）、#30（BYOK 文档）、#32（真实 Proxy integration test）。

已达成：#1（无 litellm SDK）、#13（Router 负责 retry）、#14/#15（业务幂等 + SUBMIT_UNKNOWN 状态模型已存在）、#29（secret 不进日志——需保持）、#31（legacy 在 flag 后）、#34（无 Key 时明确报告）。

---

**End of Gap Analysis**
