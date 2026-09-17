export function TextGatewaySettings() {
  return (
    <section className="df-settings-card" data-testid="text-gateway-settings">
      <div className="panel-header">
        <div>
          <h2>文本模型 · 实例级网关配置</h2>
          <p className="muted">
            文本导演与剧本生成使用实例统一的 LiteLLM 网关，不使用工作空间文本 Key。
          </p>
        </div>
      </div>
      <p>
        请由实例管理员在部署环境配置 LITELLM_GATEWAY_URL 与 LITELLM_API_KEY，并在 LiteLLM
        中配置上游模型与凭证。
      </p>
      <p className="muted">
        此处不保存密钥，也不表示网关已配置或可用。历史工作空间文本凭证不再用于执行；媒体凭证仍通过模型供应商连接管理。
      </p>
    </section>
  );
}
