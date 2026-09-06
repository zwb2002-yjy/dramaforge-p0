# infra/litellm — DramaForge LiteLLM Proxy

DramaForge 不安装 `litellm` SDK。官方 LiteLLM Proxy 是独立 Runtime，DramaForge 通过
HTTP 调用其 OpenAI-compatible 表面（`/v1/chat/completions`）。Proxy 拥有 Router 的
负载均衡 / retry / fallback / cooldown / cost / virtual keys（fix spec §1/§2）。

## 组件

| 文件 | 作用 |
|---|---|
| `config.yaml` | 逻辑别名（script-quality / script-fast / legacy-text）+ router_settings + general_settings。Secret 一律 `os.environ/<KEY>` |
| `compatibility.md` | 已核对的官方版本/行为记录 |

## 启动

```bash
# 完整栈（含 litellm-db + litellm）
docker compose up -d
# 只起 LiteLLM
docker compose up -d litellm-db litellm
```

健康检查：

```bash
curl http://localhost:4000/health/liveliness   # liveness（compose 只探这个）
curl http://localhost:4000/health/readiness    # readiness
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

> 不要高频探 `/health`（可能实际 probe 每个模型并产生成本，fix spec §12/§128-8）。

## 本地 demo（无真实 Provider Key）

在 `.env` 给别名设 `mock_response`，Proxy 将直接返回该文本而不调用上游：

```ini
LITELLM_MASTER_KEY=sk-dev-change-me
LITELLM_SCRIPT_QUALITY_MOCK_RESPONSE=你好，这是 mock 的剧本质量模型输出。
```

然后：

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-dev-change-me" \
  -H "Content-Type: application/json" \
  -d '{"model":"script-quality","messages":[{"role":"user","content":"hi"}]}'
```

## 生产

- 镜像 pin 到具体版本（`LITELLM_IMAGE=ghcr.io/berriai/litellm:v1.96.0`），禁止 `latest`。
- Provider Key 放环境/Secret Manager，经 `LITELLM_*_API_BASE` / `LITELLM_*_API_KEY` 注入。
- DramaForge 使用 dedicated Virtual Key（`LITELLM_API_KEY`），不长期用 Master Key（spec §57）。
- 媒体（MiniMax/Volcengine Image/Video）等 LiteLLM Fork provider module 完成后再接入
  （spec §7/§125）；DramaForge 只扩 `ModelBackendBinding.api_mode`。
