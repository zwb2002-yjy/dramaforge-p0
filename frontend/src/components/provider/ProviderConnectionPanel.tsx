import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";

import {
  bindProjectProvider,
  createProviderConnection,
  createProviderModelBinding,
  listProviderConnections,
  listProviderModelBindings,
  listProviderProbes,
  recordProviderQualityEvidence,
  runProviderProbe,
  updateProviderConnectionCredential,
  type ProjectRead,
  type ProviderModelBindingRead,
} from "../../lib/api";
import { zhEvidenceState } from "../../lib/zh";

type ProviderConnectionPanelProps = {
  workspaceId: string | null;
  projects: ProjectRead[];
};

const CAPABILITIES = [
  ["auth_models", "认证 / 模型目录"],
  ["image_t2i", "图像文生图"],
  ["image_i2i", "图像角色约束"],
  ["video_i2v", "视频图生视频"],
  ["video_poll_download", "视频轮询 / 下载"],
] as const;

export function ProviderConnectionPanel({
  workspaceId,
  projects,
}: ProviderConnectionPanelProps) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [capability, setCapability] = useState<(typeof CAPABILITIES)[number][0]>("auth_models");
  const [budget, setBudget] = useState("0");
  const [referenceArtifactId, setReferenceArtifactId] = useState("");
  const [remoteTaskId, setRemoteTaskId] = useState("");
  const [remoteQueryKind, setRemoteQueryKind] = useState("video_id");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [qualityRunIds, setQualityRunIds] = useState<Record<string, string>>({});
  const [qualityArtifactIds, setQualityArtifactIds] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connections = useQuery({
    queryKey: ["provider-connections", workspaceId],
    queryFn: () => listProviderConnections(workspaceId!),
    enabled: Boolean(workspaceId),
  });
  const connection = connections.data?.[0] ?? null;
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
      return createProviderConnection(workspaceId, apiKey);
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setApiKey("");
      setMessage("凭证已加密存储，本界面不可读取该 Key。");
      await refresh();
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const probeMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("请先创建 Agnes 连接");
      const paid = capability === "image_t2i" || capability === "image_i2i" || capability === "video_i2v";
      if (paid && Number(budget) <= 0) throw new Error("付费探测需要明确的正预算");
      return runProviderProbe(workspaceId, connection.id, {
        capability,
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
      if (!workspaceId || !connection) throw new Error("请先创建 Agnes 连接");
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
      if (!workspaceId || !connection) throw new Error("请先创建 Agnes 连接");
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

  const imageBinding = useMemo(
    () => bindings.data?.find((binding) => binding.purpose === "keyframe") ?? null,
    [bindings.data],
  );
  const videoBinding = useMemo(
    () => bindings.data?.find((binding) => binding.purpose === "video") ?? null,
    [bindings.data],
  );

  if (!workspaceId) {
    return <section className="panel" data-testid="provider-config"><h3>Agnes 中国站连接</h3><p className="muted">配置 Provider 前请先选择或创建空间。</p></section>;
  }

  function submitCredential(event: FormEvent) {
    event.preventDefault();
    credentialMutation.mutate();
  }

  const selectedProject = projects.find((project) => project.id === selectedProjectId);
  const paidProbe = capability === "image_t2i" || capability === "image_i2i" || capability === "video_i2v";

  return (
    <section className="panel provider-config" data-testid="provider-config">
      <div className="panel-header">
        <div>
          <h2>Agnes 中国站连接</h2>
          <p className="muted">空间级 BYOK、能力证据与项目模型门禁。</p>
        </div>
        <span className={connection?.verification_status === "verified" ? "status-ok" : "status-pending"}>
          {connection?.verification_status === "verified" ? "已验证" : "未配置"}
        </span>
      </div>

      <div className="provider-fixed-fields">
        <div><span className="status-label">主机</span><code>https://api.agnes-ai.cn</code></div>
        <div><span className="status-label">协议</span><code>agnes_cn_v1</code></div>
        <div><span className="status-label">凭证</span><strong>{connection?.credential_configured ? "已配置 · 仅写入" : "缺失"}</strong></div>
        <div><span className="status-label">密钥版本</span><code>{connection?.credential_key_version ?? "-"}</code></div>
      </div>

      <form className="provider-key-form" onSubmit={submitCredential}>
        <label>
          {connection ? "轮换 API Key" : "添加 API Key"}
          <input
            aria-label="Agnes API Key"
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
              <label>能力<select value={capability} onChange={(event) => setCapability(event.target.value as typeof capability)}>{CAPABILITIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              {paidProbe && <label>预算授权金额<input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>}
              {(capability === "image_i2i" || capability === "video_i2v") && <label>参考产物 ID<input value={referenceArtifactId} onChange={(event) => setReferenceArtifactId(event.target.value)} placeholder="参考探测必填" /></label>}
              {capability === "video_poll_download" && <><label>远端任务 ID<input value={remoteTaskId} onChange={(event) => setRemoteTaskId(event.target.value)} /></label><label>查询类型<select value={remoteQueryKind} onChange={(event) => setRemoteQueryKind(event.target.value)}><option value="video_id">video_id → /agnesapi</option><option value="task_id">task_id → /v1/videos/{"{id}"}</option></select></label></>}
              <button type="submit" disabled={probeMutation.isPending}>{probeMutation.isPending ? "探测中…" : paidProbe ? "授权并运行付费探测" : "运行探测"}</button>
            </form>
            <ul className="dense provider-evidence-list" data-testid="provider-probes">
              {(probes.data ?? []).slice(0, 6).map((probe) => <li key={probe.probe_id}><span>{probe.capability}</span><strong className={probe.status === "passed" ? "status-ok" : probe.status === "failed" ? "status-bad" : "status-pending"}>{probe.status === "passed" ? "通过" : probe.status === "failed" ? "失败" : "待定"}</strong><span className="muted">{probe.evidence_level}</span></li>)}
              {!probes.data?.length && <li className="muted">暂无能力证据。</li>}
            </ul>
          </div>

          <div>
            <h3>模型与项目绑定</h3>
            <div className="toolbar">
              <button type="button" disabled={bindingMutation.isPending || Boolean(imageBinding)} onClick={() => bindingMutation.mutate({ media_type: "image", model_id: "agnes-image-2.1-flash", purpose: "keyframe" })}>添加关键帧模型</button>
              <button type="button" disabled={bindingMutation.isPending || Boolean(videoBinding)} onClick={() => bindingMutation.mutate({ media_type: "video", model_id: "agnes-video-v2.0", purpose: "video" })}>添加视频模型</button>
            </div>
            <div className="provider-binding-list">
              {(bindings.data ?? []).map((binding) => {
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
                      <span className="muted">{binding.purpose}</span>
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
                            placeholder="人脸/漂移 NodeRun ID"
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
                    </div>
                    <button
                      type="button"
                      disabled={!binding.quality_gated || !selectedProjectId || projectBindingMutation.isPending}
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
