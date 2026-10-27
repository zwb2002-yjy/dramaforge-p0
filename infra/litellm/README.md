# infra/litellm — DramaForge 文本 Proxy 配置

当前模型与凭证权威见 [MODEL_PROVIDER.md](../../docs/MODEL_PROVIDER.md)，部署边界见
[DEPLOYMENT.md](../../docs/DEPLOYMENT.md)。本目录维护可选的官方 LiteLLM Proxy 配置，
不是第三个产品 Runtime。DramaForge 不安装 `litellm` SDK，通过 OpenAI-compatible
Chat HTTP 合同访问 Proxy 或用户明确配置的兼容文本端点；配置外部 URL 不自动经过本地 Proxy。

## 配置与身份

| 文件 | 作用 |
|---|---|
| `config.yaml` | 待迁移的 `script-quality` / `script-fast` 别名、DB 与禁止自动重放的策略 |
| `proxy_policy.py` | 在锁定 Proxy 内执行的单部署、零自动重试及 HTTPX 禁止重定向策略 |
| `quality-config.yaml` | 隔离集成测试的确定性 `mock_response`，不调用外部 Provider |
| [compatibility.md](compatibility.md) | 当前项目采用的 HTTP 合同、验证入口与限制 |

Proxy 的上游部署、重试和路由由其配置决定；DramaForge 记录所选逻辑模型和可见响应身份。
Key 只通过 `os.environ/<KEY>` 引用，不提交真实凭据。应用调用 Key 为 `LITELLM_API_KEY`；
Proxy 管理 Key 为 `LITELLM_MASTER_KEY`，后者不透传到 API / Worker。

`LITELLM_SALT_KEY` 为独立持久密钥，新安装由环境初始化器生成。已有 Proxy DB 若原来
使用 Master 作为加密盐，升级前必须在备份副本核验并保留原有效盐，不能直接生成新值。
备份必须成对保留 DB、盐、原 Master 与镜像版本，恢复成功前不得覆盖旧密钥。

## Proxy 出站边界

`litellm-network` 复用后端镜像，只负责自己的 Linux 网络 namespace 防火墙，不持有
上游凭据或 Master。Proxy 共享该 namespace，移除所有 capabilities；只有 guard 有
NET_ADMIN，不能修改宿主机或业务 Worker 的防火墙。

`LITELLM_EGRESS_ALLOWED_ORIGINS` 是网络授权的 JSON origin 列表；私网及明文 HTTP
另须 `LITELLM_EGRESS_TRUSTED_NETWORKS` 的精确 CIDR 授权。它们不登记模型、协议或 Key，
不替代 Proxy DB 的模型配置。默认无上游出站授权；元数据、回环和共享保留地址不能被授权。
DNS 的全部答案在启动时检查，规则固定 IP/端口；DNS 改变后失败关闭，须重建 guard 与
Proxy namespace 来核验新地址。仅数据库、Docker DNS、存活检查有必要的控制面例外。

Proxy 的 HTTPX/requests/aiohttp 发送禁止跟随重定向，回调强制当前请求 retries=0、无 fallback，并拒绝
同一 alias 下的多个部署。未证明安全的 SDK/Router 重试保持关闭；有限 pre-send 重试
只允许后续在明确的发送边界实现。未知结果不能因 429/503/408 而自动重发。

锁定 Prisma 0.11.0 的本地查询引擎固定使用 4001 控制端口，避免随机开放回环端口。
Proxy 固定单 worker；创建模型在原授权依赖之后串行检查 YAML/DB alias 冲突，拒绝
silent_model 和用户请求级目标/凭据覆盖。它不是完整 G2 管理入口，也不重写旧历史。

管理 API 和受限管理凭据的业务集成属于后续 Gate；本阶段不把 Master 放入应用，
也不将 DB 中的可变部署 UUID 宣称为不可变模型版本。媒体执行不依赖该 guard/Proxy。

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
