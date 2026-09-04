# LiteLLM compatibility notes（fix spec §132）

> 核对日期：2026-08-11。升级前重新核对官方文档，不要长期固定此版本。

## 镜像与版本

| 项 | 值 |
|---|---|
| 官方仓库 | `github.com/BerriAI/litellm` |
| GitHub release | `v1.96.0`（2026-08-10 发布） |
| Docker image | `ghcr.io/berriai/litellm:v1.96.0` |
| image digest | `sha256:90d8de0ea6fbb3cad145d1019d00a0149ae400b1e18e2011a60f1988f143f672` |
| 滚动 tag（生产禁用） | `main-stable` / `latest` / `main-latest` |
| 容器 entrypoint | `/app/.venv/bin/litellm`（CLI）；`--config /app/config.yaml --port 4000` |

版本化 tag 约定已从旧 `main-vX.Y.Z` 改为 `vX.Y.Z`（2026-08 实测 `main-v1.89.0` 不存在）。

## 实测行为（2026-08-11，v1.96.0 容器）

| 端点 | 行为 |
|---|---|
| `GET /health/liveliness` | 200（compose healthcheck 只用这个） |
| `GET /health/readiness` | 200 |
| `GET /v1/models`（需 auth） | `{"data":[{"id":"script-quality"},...]}`；无 auth → 401 |
| `POST /v1/chat/completions` | OpenAI-compatible；`mock_response` 生效时直接返回 mock 文本 + usage |
| 未知 model | 400 + `Invalid model name passed in model=...` |
| 错误 Master Key（无 DB） | 400 + `No connected db`（master key 校验依赖 DB；配 litellm-db 后为正常 401） |

## 响应头 allowlist（已实测，fix spec §47/§48）

- `x-litellm-response-cost` / `x-litellm-response-cost-original`
- `x-litellm-attempted-retries` / `x-litellm-attempted-fallbacks`
- `x-litellm-response-duration-ms` / `x-litellm-overhead-duration-ms`
- `x-litellm-call-id`（request id）/ `x-litellm-model-id` / `x-litellm-model-name`
  / `x-litellm-model-group`（逻辑别名）/ `x-litellm-version`

## 配置语法

- Secret 替换：`os.environ/<KEY>`；空值合法（config 加载成功，别名仅在配置齐备后可调用）。
- `mock_response`：设置后 Proxy 不调用上游，直接返回该字符串（用于集成测试/本地 demo）。
- `general_settings.enable_response_cost_headers: true`：输出 cost header。
- `general_settings.drop_params: false`：严格模式（spec §62），不静默丢参。

## DramaForge 约定

- 路径规范：`LITELLM_GATEWAY_URL` 是 base（dev 默认 `http://litellm:4000`），客户端统一拼
  `/v1/chat/completions`（spec §19/§20/§21）。
- `LITELLM_API_KEY` = DramaForge 调用 Gateway 的 Virtual/Master Key（spec §22/§57）。
- `LITELLM_MASTER_KEY` = Gateway 管理员 Key，只进 litellm service，不进 api/worker（spec §23）。
