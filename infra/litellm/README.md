# infra/litellm — DramaForge 文本 Proxy 配置

当前模型与凭证权威见 [MODEL_PROVIDER.md](../../docs/MODEL_PROVIDER.md)，部署边界见
[DEPLOYMENT.md](../../docs/DEPLOYMENT.md)。本目录维护可选的官方 LiteLLM Proxy 配置，
不是第三个产品 Runtime。DramaForge 不安装 `litellm` SDK，通过 OpenAI-compatible
Chat HTTP 合同访问 Proxy 或用户明确配置的兼容文本端点；配置外部 URL 不自动经过本地 Proxy。

## 配置与身份

| 文件 | 作用 |
|---|---|
| `config.yaml` | 默认部署的 `script-quality` / `script-fast` / `legacy-text` 逻辑别名、Router 和 Secret 引用 |
| `quality-config.yaml` | 隔离集成测试的确定性 `mock_response`，不调用外部 Provider |
| [compatibility.md](compatibility.md) | 当前项目采用的 HTTP 合同、验证入口与限制 |

Proxy 的上游部署、重试和路由由其配置决定；DramaForge 记录所选逻辑模型和可见响应身份。
Key 只通过 `os.environ/<KEY>` 引用，不提交真实凭据。应用调用 Key 为 `LITELLM_API_KEY`；
Proxy 管理 Key 为 `LITELLM_MASTER_KEY`，后者不透传到 API / Worker。

## 启动与检查

从仓库根执行；必须先按部署文档配置已有实例和凭据：

```bash
docker compose up -d litellm-db litellm
docker compose ps litellm-db litellm
docker compose logs --tail 100 litellm
```

默认发布拓扑不把 4000 暴露到宿主机。存活检查在服务容器内执行：

```bash
docker compose exec litellm python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness').status)"
```

`/health/liveliness` 只证明进程存活；目录 `/v1/models` 需认证。不要将存活、发现或
配置读取当作上游模型能力/账号质量认证；不要把可能对上游产生调用的 `/health` 当免费探测。

## 离线协议验证

仓库完整质量门启动固定 Proxy 镜像并使用 `quality-config.yaml`，见
[DEVELOPMENT.md](../../docs/DEVELOPMENT.md) 和
[test_litellm_real_proxy.py](../../backend/tests/integration/test_litellm_real_proxy.py)。
此处的 “real proxy” 表示实际 Proxy 进程，模型响应仍为 mock；不证明真实上游可用。
本目录不提供可绕过测试隔离的真实 Chat 试调用步骤，实际模型调用遵守逐操作预算与授权。

## 产品边界

图像/视频由 `backend/app/providers/` 的统一 Compiler 与 Provider Runtime 执行，
不是 LiteLLM 媒体 Fork 的待接入路径。静态文本别名、工作空间文本连接和媒体 Binding
的来源/修订分别冻结，不以兼容协议或相同名称推断它们是同一个模型。
