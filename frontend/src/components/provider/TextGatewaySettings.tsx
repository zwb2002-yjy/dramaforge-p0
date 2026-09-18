export function TextGatewaySettings() {
  return (
    <section className="df-settings-card" data-testid="text-gateway-settings">
      <h2>文本服务</h2>
      <p>作用于整个实例，由部署环境管理。此页面不检测连接状态。</p>
      <p className="muted">
        配置 LITELLM_GATEWAY_URL 与 LITELLM_API_KEY，并在 LiteLLM 中设置上游模型；此处不保存密钥。
      </p>
    </section>
  );
}
