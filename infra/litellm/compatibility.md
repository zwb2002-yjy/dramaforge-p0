# LiteLLM compatibility — 当前配置合同

本文件说明 DramaForge 的配置与可重复验证合同，不保留
单次容器实测流水。模型/凭证权威见 [MODEL_PROVIDER.md](../../docs/MODEL_PROVIDER.md)。

## 版本来源

默认 Compose 与质量拓扑采用 `ghcr.io/berriai/litellm:v1.96.0`；默认部署镜像可由
`LITELLM_IMAGE` 显式覆盖，质量拓扑的镜像由 `docker-compose.quality.yml` 固定。
该版本是项目采用的基线，不表示上游最新版本。默认与质量拓扑均锁定 digest
`sha256:90d8de0ea6fbb3cad145d1019d00a0149ae400b1e18e2011a60f1988f143f672`；
显式覆盖镜像时须重新完成兼容验证，不能沿用默认镜像的证据。

升级应核对 Compose、配置语法及下列回归，不因外部最新版本自动替换已验证依赖。

## HTTP 与消息合同

- `LITELLM_GATEWAY_URL` 是运维指定的内部 Proxy Base URL；客户端按当前规范化规则拼接
  `/v1/chat/completions` 与 `/v1/models`，源码见
  [client.py](../../backend/app/providers/litellm_gateway/client.py)。
- 默认 Compose 在内部网络访问 `http://litellm:4000`，不发布宿主 4000；
  历史外部端点不再进入新文本执行。受管引用同时冻结别名、部署与凭据版本，失配在发送前阻断。
- `LITELLM_API_KEY` 是应用调用服务的 Key；`LITELLM_MASTER_KEY` 仅属于 Proxy 服务。
- 文本参数、schema repair 与工具消息支持以
  [LiteLLMModelAdapter](../../backend/app/providers/litellm_adapter.py) 和共享文本合同为准。
  能发送 `tools` 不表示 Agent tool-call / tool-result 闭环已经实现。
- 允许保存的成本、耗时、请求和模型响应头由客户端 allowlist 定义；不保存任意响应头
  或认证内容。成本头缺失时保持未知，不从模型名称推断价格。

## 配置与验证

`config.yaml` 用 `os.environ/<KEY>` 注入 Secret，`drop_params: false` 避免静默丢参。
新业务使用 Proxy DB 的单部署受管别名，旧 YAML 别名不与 DB 部署混合。
别名只有在上游或明确的 mock 配置可用时才可调用；目录存在不证明凭据、能力或质量。
`quality-config.yaml` 的 `mock_response` 用于隔离测试，绝不当作真实账号验证。

可重复兼容证明由
[test_litellm_real_proxy.py](../../backend/tests/integration/test_litellm_real_proxy.py) 与
[test_litellm_proxy_policy.py](../../backend/tests/integration/test_litellm_proxy_policy.py) 维护：
实际固定 Proxy 进程、认证、目录/逻辑别名、Chat 请求和响应元数据均在隔离容器内验证。
运行命令与正式 Gate 边界见 [DEVELOPMENT.md](../../docs/DEVELOPMENT.md)。真实模型输出、
供应商能力与作品质量另行验收；早期测试计数、响应状态快照和版本调研只通过 Git 追溯。
