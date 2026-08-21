import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";

import {
  bindProjectProvider,
  createProviderConnection,
  createProviderModelBinding,
  listProviderConnections,
  listProviderPlugins,
  listProviderModelBindings,
  listProviderProbes,
  recordProviderQualityEvidence,
  runProviderProbe,
  setProviderModelBindingPricing,
  updateProviderConnectionCredential,
  updateProviderConnection,
  type ProjectRead,
  type ProviderPluginRead,
  type ProviderModelBindingRead,
} from "../../lib/api";
import { zhEvidenceState } from "../../lib/zh";

type ProviderConnectionPanelProps = {
  workspaceId: string | null;
  projects: ProjectRead[];
};

const CAPABILITY_LABELS: Record<string, string> = {
  auth_models: "认证 / 模型目录",
  image_t2i: "图像文生图",
  image_i2i: "图像角色约束",
  video_i2v: "视频图生视频",
  video_poll_download: "视频轮询 / 下载",
};

export function ProviderConnectionPanel({
  workspaceId,
  projects,
}: ProviderConnectionPanelProps) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [selectedPluginKey, setSelectedPluginKey] = useState("agnes/agnes_cn_v1");
  const [capability, setCapability] = useState("auth_models");
  const [budget, setBudget] = useState("0");
  const [referenceArtifactId, setReferenceArtifactId] = useState("");
  const [remoteTaskId, setRemoteTaskId] = useState("");
  const [remoteQueryKind, setRemoteQueryKind] = useState("video_id");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [qualityRunIds, setQualityRunIds] = useState<Record<string, string>>({});
  const [qualityArtifactIds, setQualityArtifactIds] = useState<Record<string, string>>({});
  const [pricingAmounts, setPricingAmounts] = useState<Record<string, string>>({});
  const [pricingCurrency, setPricingCurrency] = useState("USD");
  const [pricingConfirmed, setPricingConfirmed] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connections = useQuery({
    queryKey: ["provider-connections", workspaceId],
    queryFn: () => listProviderConnections(workspaceId!),
    enabled: Boolean(workspaceId),
  });
  const connectionLoadError = connections.error instanceof Error
    ? connections.error.message
    : connections.isError
      ? "未知错误"
      : null;
  const plugins = useQuery({
    queryKey: ["provider-plugins"],
    queryFn: listProviderPlugins,
    staleTime: 60_000,
  });
  const selectedPlugin: ProviderPluginRead | null = useMemo(() => {
    const found = (plugins.data ?? []).find(
      (plugin) => `${plugin.provider_type}/${plugin.protocol_profile}` === selectedPluginKey,
    );
    return found ?? plugins.data?.[0] ?? null;
  }, [plugins.data, selectedPluginKey]);
  const connection = connections.data?.find((item) => item.provider_type === selectedPlugin?.provider_type
      && item.protocol_profile === selectedPlugin?.protocol_profile)
    ?? null;
  const probes = useQuery({
    queryKey: ["provider-probes", workspaceId, connection?.id],
    queryFn: () => listProviderProbes(workspaceId!, connection!.id),
    enabled: Boolean(workspaceId && connection),
  });
  const bindings = useQuery({
    queryKey: ["provider-bindings", workspaceId, connection?.id],
    queryFn: () => listProviderModelBindings(workspaceId!, connection!.id),
    enabled: Boolean(workspaceId && connection),
  });

  const resetFeedback = () => {
    setMessage(null);
    setError(null);
  };

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["provider-connections", workspaceId] });
    await queryClient.invalidateQueries({ queryKey: ["provider-probes", workspaceId] });
    await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId] });
  };

  const credentialMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !apiKey.trim()) throw new Error("请输入 API Key");
      if (connection) return updateProviderConnectionCredential(workspaceId, connection.id, apiKey);
      if (!selectedPlugin) throw new Error("正在加载供应商插件契约");
      return createProviderConnection(workspaceId, apiKey, {
        provider_type: selectedPlugin.provider_type,
        display_name: selectedPlugin.display_name,
        protocol_profile: selectedPlugin.protocol_profile,
        base_url: selectedPlugin.default_base_url,
      });
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setApiKey("");
      setMessage("凭证已加密存储，本界面不可读取该 Key。");
      await refresh();
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const connectionMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("请先创建供应商连接");
      if (!baseUrl.trim()) throw new Error("请输入供应商 Base URL");
      return updateProviderConnection(workspaceId, connection.id, { base_url: baseUrl.trim() });
    },
    onMutate: resetFeedback,
    onSuccess: async () => { setMessage("供应商连接地址已保存，下次探测将使用新地址。"); await refresh(); },
    onError: (cause: Error) => setError(cause.message),
  });

  const probeMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      const paid = Boolean(selectedPlugin?.paid_capabilities.includes(capability));
      if (paid && Number(budget) <= 0) throw new Error("付费探测需要明确的正预算");
      const probeBinding = capability === "video_i2v" ? videoBinding : capability.startsWith("image_") ? imageBinding : null;
      if (capability !== "auth_models" && !probeBinding) {
        throw new Error("请先添加与当前能力对应的模型绑定");
      }
      return runProviderProbe(workspaceId, connection.id, {
        capability,
        ...(probeBinding ? { model_binding_id: probeBinding.id } : {}),
        budget_authorized: paid ? budget : "0",
        ...(referenceArtifactId.trim() ? { reference_artifact_id: referenceArtifactId.trim() } : {}),
        ...(remoteTaskId.trim() ? { remote_task_id: remoteTaskId.trim() } : {}),
        ...(capability === "video_poll_download" ? { remote_query_kind: remoteQueryKind } : {}),
      });
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      setMessage(`探测 ${result.capability}：${result.status} · 证据=${result.evidence_level}`);
      await queryClient.invalidateQueries({ queryKey: ["provider-probes", workspaceId, connection?.id] });
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId, connection?.id] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const bindingMutation = useMutation({
    mutationFn: async (input: { media_type: "image" | "video"; model_id: string; purpose: "keyframe" | "video" }) => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      return createProviderModelBinding(workspaceId, connection.id, input);
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      setMessage(`${result.purpose} 模型绑定已创建：${result.model_id}`);
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId, connection?.id] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const projectBindingMutation = useMutation({
    mutationFn: async (input: { purpose: "keyframe" | "video"; modelBindingId: string }) => {
      if (!selectedProjectId) throw new Error("请先选择项目");
      return bindProjectProvider(selectedProjectId, input.purpose, input.modelBindingId);
    },
    onMutate: resetFeedback,
    onSuccess: (result) => setMessage(`${result.purpose} 项目绑定已保存（fallback=none）`),
    onError: (cause: Error) => setError(cause.message),
  });

  const qualityEvidenceMutation = useMutation({
    mutationFn: async (input: { binding: ProviderModelBindingRead; nodeRunId: string; artifactId: string }) => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      if (!input.nodeRunId.trim() || !input.artifactId.trim()) {
        throw new Error("需要 NodeRun ID 与产物 ID");
      }
      return recordProviderQualityEvidence(workspaceId, connection.id, input.binding.id, {
        node_run_id: input.nodeRunId.trim(),
        artifact_id: input.artifactId.trim(),
      });
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setMessage("质量证据已记录，绑定现可被项目使用。");
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const pricingMutation = useMutation({
    mutationFn: async (binding: ProviderModelBindingRead) => {
      if (!workspaceId || !connection) throw new Error("请先配置生成服务");
      const amount = pricingAmounts[binding.id]?.trim();
      if (!amount || Number(amount) < 0) throw new Error("请输入非负单次估算价格");
      if (!pricingConfirmed[binding.id]) throw new Error("请确认这是本次调用的保守估算上限");
      return setProviderModelBindingPricing(workspaceId, connection.id, binding.id, {
        unit_amount: amount,
        currency: pricingCurrency,
        billing_unit: binding.media_type === "video" ? "per_generated_clip" : "per_generated_image",
        source_note: "由工作区所有者填写的单次调用保守估算上限；实际账单以供应商为准",
        owner_verified: true,
      });
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setMessage("保守成本快照已记录。重新生成拍摄方案后会按此估算并冻结预算。");
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId, connection?.id] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const pluginCapabilities = selectedPlugin?.capabilities ?? ["auth_models"];
  const pluginModels = selectedPlugin?.models ?? [];
  const imageModels = pluginModels.filter((model) => model.media_type === "image");
  const videoModels = pluginModels.filter((model) => model.media_type === "video");
  const activeModelsByContract = useMemo(
    () => new Map(
      (selectedPlugin?.models ?? []).map((model) => [
        `${model.catalog_entry_id}:${model.capability_manifest_hash}`,
        model,
      ]),
    ),
    [selectedPlugin?.models],
  );
  const activeModelFor = (binding: ProviderModelBindingRead) => activeModelsByContract.get(
    `${binding.catalog_entry_id}:${binding.capability_manifest_hash}`,
  ) ?? null;
  const imageBinding = useMemo(
    () => bindings.data?.find((binding) => (
      binding.purpose === "keyframe"
      && activeModelsByContract.has(
        `${binding.catalog_entry_id}:${binding.capability_manifest_hash}`,
      )
    )) ?? null,
    [activeModelsByContract, bindings.data],
  );
  const videoBinding = useMemo(
    () => bindings.data?.find((binding) => (
      binding.purpose === "video"
      && activeModelsByContract.has(
        `${binding.catalog_entry_id}:${binding.capability_manifest_hash}`,
      )
    )) ?? null,
    [activeModelsByContract, bindings.data],
  );

  if (!workspaceId) {
    return <section className="panel" data-testid="provider-config"><h3>模型供应商插件</h3><p className="muted">配置供应商前请先选择或创建空间。</p></section>;
  }

  function submitCredential(event: FormEvent) {
    event.preventDefault();
    credentialMutation.mutate();
  }

  const selectedProject = projects.find((project) => project.id === selectedProjectId);
  const paidProbe = Boolean(selectedPlugin?.paid_capabilities.includes(capability));

  return (
    <section className="panel provider-config" data-testid="provider-config">
      <div className="panel-header">
        <div>
          <h2>模型供应商插件</h2>
          <p className="muted">插件契约驱动的连接、能力探测、模型绑定与质量门禁。</p>
        </div>
        <span className={connectionLoadError ? "status-bad" : connection?.verification_status === "verified" ? "status-ok" : "status-pending"}>
          {connectionLoadError ? "读取失败" : connection?.verification_status === "verified" ? "已验证" : "未配置"}
        </span>
      </div>

      {connectionLoadError && <p className="flash err">连接列表加载失败：{connectionLoadError}</p>}

      <div className="provider-plugin-selector">
        <label>供应商插件
          <select aria-label="供应商插件" value={selectedPlugin ? `${selectedPlugin.provider_type}/${selectedPlugin.protocol_profile}` : selectedPluginKey} onChange={(event) => {
            setSelectedPluginKey(event.target.value);
            setBaseUrl("");
            setCapability("auth_models");
          }}>
            {(plugins.data ?? []).map((plugin) => <option key={`${plugin.provider_type}/${plugin.protocol_profile}`} value={`${plugin.provider_type}/${plugin.protocol_profile}`}>{plugin.display_name} · {plugin.protocol_profile}</option>)}
          </select>
        </label>
        <label><span className="status-label">Base URL</span><input aria-label="供应商 Base URL" value={baseUrl || connection?.base_url || selectedPlugin?.default_base_url || ""} onChange={(event) => setBaseUrl(event.target.value)} /></label>
        {connection && <button type="button" onClick={() => connectionMutation.mutate()} disabled={connectionMutation.isPending}>保存连接地址</button>}
        <div><span className="status-label">模型数</span><strong>{pluginModels.length}</strong></div>
        <div><span className="status-label">插件状态</span><strong>{selectedPlugin?.implemented ? "已实现" : "仅目录"}</strong></div>
      </div>
      <div className="provider-fixed-fields">
        <div><span className="status-label">当前连接</span><code>{connection?.display_name ?? "尚未配置"}</code></div>
        <div><span className="status-label">协议</span><code>{selectedPlugin?.protocol_profile ?? "-"}</code></div>
        <div><span className="status-label">凭证</span><strong>{connection?.credential_configured ? "已配置 · 仅写入" : "缺失"}</strong></div>
        <div><span className="status-label">密钥版本</span><code>{connection?.credential_key_version ?? "-"}</code></div>
      </div>

      <form className="provider-key-form" onSubmit={submitCredential}>
        <label>
          {connection ? `轮换 ${selectedPlugin?.display_name ?? "供应商"} API Key` : `添加 ${selectedPlugin?.display_name ?? "供应商"} API Key`}
          <input
            aria-label={`${selectedPlugin?.display_name ?? "供应商"} API Key`}
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="只写入一次；永不回读"
            autoComplete="new-password"
          />
        </label>
        <button className="primary" type="submit" disabled={credentialMutation.isPending || !apiKey.trim()}>
          {credentialMutation.isPending ? "保存中…" : connection ? "轮换 Key" : "保存加密 Key"}
        </button>
      </form>

      {connection && (
        <div className="provider-grid">
          <div>
            <h3>能力探测</h3>
            <form className="form-grid" onSubmit={(event) => { event.preventDefault(); probeMutation.mutate(); }}>
              <label>能力<select value={capability} onChange={(event) => setCapability(event.target.value)}>{pluginCapabilities.map((value) => <option value={value} key={value}>{CAPABILITY_LABELS[value] ?? value}</option>)}</select></label>
              {paidProbe && <label>预算授权金额<input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>}
              {(capability === "image_i2i" || capability === "video_i2v") && <label>参考产物 ID<input value={referenceArtifactId} onChange={(event) => setReferenceArtifactId(event.target.value)} placeholder="参考探测必填" /></label>}
              {capability === "video_poll_download" && <><label>远端任务 ID<input value={remoteTaskId} onChange={(event) => setRemoteTaskId(event.target.value)} /></label><label>查询类型<select value={remoteQueryKind} onChange={(event) => setRemoteQueryKind(event.target.value)}><option value="video_id">video_id → /agnesapi</option><option value="task_id">task_id → /v1/videos/{"{id}"}</option></select></label></>}
              <button type="submit" disabled={probeMutation.isPending || !selectedPlugin?.implemented}>{probeMutation.isPending ? "探测中…" : paidProbe ? "授权并运行付费探测" : "运行探测"}</button>
            </form>
            <ul className="dense provider-evidence-list" data-testid="provider-probes">
              {(probes.data ?? []).slice(0, 6).map((probe) => <li key={probe.probe_id}><span>{probe.capability}</span><strong className={probe.status === "passed" ? "status-ok" : probe.status === "failed" ? "status-bad" : "status-pending"}>{probe.status === "passed" ? "通过" : probe.status === "failed" ? "失败" : "待定"}</strong><span className="muted">{probe.evidence_level}</span></li>)}
              {!probes.data?.length && <li className="muted">暂无能力证据。</li>}
            </ul>
          </div>

          <div>
            <h3>模型与项目绑定</h3>
            <div className="toolbar">
              <select aria-label="关键帧模型" defaultValue="" onChange={(event) => { const model = imageModels.find((item) => item.model_id === event.target.value); if (model) bindingMutation.mutate({ media_type: "image", model_id: model.model_id, purpose: "keyframe" }); }} disabled={bindingMutation.isPending || !imageModels.length || Boolean(imageBinding)}>
                <option value="">添加关键帧模型…</option>
                {imageModels.map((model) => <option key={model.model_id} value={model.model_id}>{model.display_name} · {model.model_id}</option>)}
              </select>
              <select aria-label="视频模型" defaultValue="" onChange={(event) => { const model = videoModels.find((item) => item.model_id === event.target.value); if (model) bindingMutation.mutate({ media_type: "video", model_id: model.model_id, purpose: "video" }); }} disabled={bindingMutation.isPending || !videoModels.length || Boolean(videoBinding)}>
                <option value="">添加视频模型…</option>
                {videoModels.map((model) => <option key={model.model_id} value={model.model_id}>{model.display_name} · {model.model_id}</option>)}
              </select>
            </div>
            <div className="provider-binding-list">
              {(bindings.data ?? []).map((binding) => {
                const activeModel = activeModelFor(binding);
                const states = [
                  ["documented", binding.documented],
                  ["contract_tested", binding.contract_tested],
                  ["account_verified", binding.account_verified],
                  ["quality_gated", binding.quality_gated],
                ] as const;
                return (
                  <div className="provider-binding" key={binding.id}>
                    <div>
                      <strong>{binding.model_id}</strong>
                      <span className="muted">{binding.purpose} · {activeModel ? activeModel.model_revision : "历史合同"}</span>
                      <div className="provider-binding-states" data-testid={`binding-states-${binding.purpose}`}>
                        {states.map(([state, passed]) => (
                          <span
                            key={state}
                            className={passed ? "evidence-state passed" : "evidence-state pending"}
                            data-testid={`binding-${binding.purpose}-${state}`}
                          >
                            {zhEvidenceState(state)}：{passed ? "通过" : "待定"}
                          </span>
                        ))}
                      </div>
                      {!binding.quality_gated && binding.account_verified && (
                        <div className="quality-evidence-form">
                          <input
                            aria-label={`${binding.purpose} 质量 NodeRun ID`}
                            placeholder="人物/时序复核 NodeRun ID"
                            value={qualityRunIds[binding.id] ?? ""}
                            onChange={(event) => setQualityRunIds((current) => ({ ...current, [binding.id]: event.target.value }))}
                          />
                          <input
                            aria-label={`${binding.purpose} 质量产物 ID`}
                            placeholder="质量产物 ID"
                            value={qualityArtifactIds[binding.id] ?? ""}
                            onChange={(event) => setQualityArtifactIds((current) => ({ ...current, [binding.id]: event.target.value }))}
                          />
                          <button
                            type="button"
                            disabled={qualityEvidenceMutation.isPending}
                            onClick={() => qualityEvidenceMutation.mutate({
                              binding,
                              nodeRunId: qualityRunIds[binding.id] ?? "",
                              artifactId: qualityArtifactIds[binding.id] ?? "",
                            })}
                          >
                            记录质量证据
                          </button>
                        </div>
                      )}
                      <div className="quality-evidence-form">
                        <input
                          aria-label={`${binding.purpose} 单次价格`}
                          type="number"
                          min="0"
                          step="0.000001"
                          placeholder="单次估算价格"
                          value={pricingAmounts[binding.id] ?? String(binding.pricing_snapshot.unit_amount ?? "")}
                          onChange={(event) => setPricingAmounts((current) => ({ ...current, [binding.id]: event.target.value }))}
                        />
                        <select aria-label="价格币种" value={pricingCurrency} onChange={(event) => setPricingCurrency(event.target.value)}>
                          <option value="USD">USD</option><option value="CNY">CNY</option>
                        </select>
                        <label>
                          <input
                            type="checkbox"
                            checked={Boolean(pricingConfirmed[binding.id])}
                            onChange={(event) => setPricingConfirmed((current) => ({ ...current, [binding.id]: event.target.checked }))}
                          />
                          我确认这是单次调用的保守估算上限，实际账单以供应商为准
                        </label>
                        <button type="button" disabled={pricingMutation.isPending} onClick={() => pricingMutation.mutate(binding)}>保存价格快照</button>
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={!activeModel || !binding.account_verified || !selectedProjectId || projectBindingMutation.isPending}
                      onClick={() => projectBindingMutation.mutate({ purpose: binding.purpose as "keyframe" | "video", modelBindingId: binding.id })}
                    >
                      绑定所选项目
                    </button>
                  </div>
                );
              })}
              {!bindings.data?.length && <p className="muted">完成合同、账号与质量证据后创建固定合同绑定。</p>}
            </div>
            <label>项目<select aria-label="项目 Provider 绑定" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">选择项目</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
            {selectedProject && <p className="muted">降级策略：无 · {selectedProject.name}</p>}
          </div>
        </div>
      )}

      {(message || error) && <div className={error ? "flash err" : "flash ok"} data-testid="provider-config-message">{error ?? message}</div>}
    </section>
  );
}
