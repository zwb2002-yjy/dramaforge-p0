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

type ProviderConnectionPanelProps = {
  workspaceId: string | null;
  projects: ProjectRead[];
};

const CAPABILITIES = [
  ["auth_models", "Auth / Model catalog"],
  ["image_t2i", "Image text-to-image"],
  ["image_i2i", "Image character conditioning"],
  ["video_i2v", "Video image-to-video"],
  ["video_poll_download", "Video poll / download"],
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
      if (!workspaceId || !apiKey.trim()) throw new Error("Enter an API key");
      if (connection) return updateProviderConnectionCredential(workspaceId, connection.id, apiKey);
      return createProviderConnection(workspaceId, apiKey);
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setApiKey("");
      setMessage("Credential stored encrypted. The key is not readable from this UI.");
      await refresh();
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const probeMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("Create the Agnes connection first");
      const paid = capability === "image_t2i" || capability === "image_i2i" || capability === "video_i2v";
      if (paid && Number(budget) <= 0) throw new Error("Paid Probe requires an explicit positive budget");
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
      setMessage(`Probe ${result.capability}: ${result.status} · evidence=${result.evidence_level}`);
      await queryClient.invalidateQueries({ queryKey: ["provider-probes", workspaceId, connection?.id] });
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId, connection?.id] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const bindingMutation = useMutation({
    mutationFn: async (input: { media_type: "image" | "video"; model_id: string; purpose: "keyframe" | "video" }) => {
      if (!workspaceId || !connection) throw new Error("Create the Agnes connection first");
      return createProviderModelBinding(workspaceId, connection.id, input);
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      setMessage(`${result.purpose} model binding created: ${result.model_id}`);
      await queryClient.invalidateQueries({ queryKey: ["provider-bindings", workspaceId, connection?.id] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const projectBindingMutation = useMutation({
    mutationFn: async (input: { purpose: "keyframe" | "video"; modelBindingId: string }) => {
      if (!selectedProjectId) throw new Error("Select a project first");
      return bindProjectProvider(selectedProjectId, input.purpose, input.modelBindingId);
    },
    onMutate: resetFeedback,
    onSuccess: (result) => setMessage(`${result.purpose} project binding saved with fallback=none`),
    onError: (cause: Error) => setError(cause.message),
  });

  const qualityEvidenceMutation = useMutation({
    mutationFn: async (input: { binding: ProviderModelBindingRead; nodeRunId: string; artifactId: string }) => {
      if (!workspaceId || !connection) throw new Error("Create the Agnes connection first");
      if (!input.nodeRunId.trim() || !input.artifactId.trim()) {
        throw new Error("NodeRun ID and Artifact ID are required");
      }
      return recordProviderQualityEvidence(workspaceId, connection.id, input.binding.id, {
        node_run_id: input.nodeRunId.trim(),
        artifact_id: input.artifactId.trim(),
      });
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setMessage("Quality evidence recorded. The binding can now be used by a project.");
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
    return <section className="panel" data-testid="provider-config"><h3>Agnes 中国站 Connection</h3><p className="muted">Select or create a Workspace before configuring Provider access.</p></section>;
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
          <h2>Agnes 中国站 Connection</h2>
          <p className="muted">Workspace-scoped BYOK, capability evidence, and project model gates.</p>
        </div>
        <span className={connection?.verification_status === "verified" ? "status-ok" : "status-pending"}>
          {connection?.verification_status ?? "not configured"}
        </span>
      </div>

      <div className="provider-fixed-fields">
        <div><span className="status-label">Host</span><code>https://api.agnes-ai.cn</code></div>
        <div><span className="status-label">Profile</span><code>agnes_cn_v1</code></div>
        <div><span className="status-label">Credential</span><strong>{connection?.credential_configured ? "configured · write-only" : "missing"}</strong></div>
        <div><span className="status-label">Key version</span><code>{connection?.credential_key_version ?? "-"}</code></div>
      </div>

      <form className="provider-key-form" onSubmit={submitCredential}>
        <label>
          {connection ? "Rotate API key" : "Add API key"}
          <input
            aria-label="Agnes API key"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="Write once; never returned"
            autoComplete="new-password"
          />
        </label>
        <button className="primary" type="submit" disabled={credentialMutation.isPending || !apiKey.trim()}>
          {credentialMutation.isPending ? "Saving…" : connection ? "Rotate key" : "Save encrypted key"}
        </button>
      </form>

      {connection && (
        <div className="provider-grid">
          <div>
            <h3>Capability Probe</h3>
            <form className="form-grid" onSubmit={(event) => { event.preventDefault(); probeMutation.mutate(); }}>
              <label>Capability<select value={capability} onChange={(event) => setCapability(event.target.value as typeof capability)}>{CAPABILITIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              {paidProbe && <label>Explicit budget authorization<input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>}
              {(capability === "image_i2i" || capability === "video_i2v") && <label>Reference Artifact ID<input value={referenceArtifactId} onChange={(event) => setReferenceArtifactId(event.target.value)} placeholder="Required for reference Probe" /></label>}
              {capability === "video_poll_download" && <><label>Remote task ID<input value={remoteTaskId} onChange={(event) => setRemoteTaskId(event.target.value)} /></label><label>Query kind<select value={remoteQueryKind} onChange={(event) => setRemoteQueryKind(event.target.value)}><option value="video_id">video_id → /agnesapi</option><option value="task_id">task_id → /v1/videos/{"{id}"}</option></select></label></>}
              <button type="submit" disabled={probeMutation.isPending}>{probeMutation.isPending ? "Probing…" : paidProbe ? "Authorize and run paid Probe" : "Run Probe"}</button>
            </form>
            <ul className="dense provider-evidence-list" data-testid="provider-probes">
              {(probes.data ?? []).slice(0, 6).map((probe) => <li key={probe.probe_id}><span>{probe.capability}</span><strong className={probe.status === "passed" ? "status-ok" : probe.status === "failed" ? "status-bad" : "status-pending"}>{probe.status}</strong><span className="muted">{probe.evidence_level}</span></li>)}
              {!probes.data?.length && <li className="muted">No capability evidence yet.</li>}
            </ul>
          </div>

          <div>
            <h3>Model and project binding</h3>
            <div className="toolbar">
              <button type="button" disabled={bindingMutation.isPending || Boolean(imageBinding)} onClick={() => bindingMutation.mutate({ media_type: "image", model_id: "agnes-image-2.1-flash", purpose: "keyframe" })}>Add keyframe model</button>
              <button type="button" disabled={bindingMutation.isPending || Boolean(videoBinding)} onClick={() => bindingMutation.mutate({ media_type: "video", model_id: "agnes-video-v2.0", purpose: "video" })}>Add video model</button>
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
                            {state}: {passed ? "pass" : "pending"}
                          </span>
                        ))}
                      </div>
                      {!binding.quality_gated && binding.account_verified && (
                        <div className="quality-evidence-form">
                          <input
                            aria-label={`${binding.purpose} quality NodeRun ID`}
                            placeholder="Face/Drift NodeRun ID"
                            value={qualityRunIds[binding.id] ?? ""}
                            onChange={(event) => setQualityRunIds((current) => ({ ...current, [binding.id]: event.target.value }))}
                          />
                          <input
                            aria-label={`${binding.purpose} quality Artifact ID`}
                            placeholder="Quality Artifact ID"
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
                            Record quality evidence
                          </button>
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      disabled={!binding.quality_gated || !selectedProjectId || projectBindingMutation.isPending}
                      onClick={() => projectBindingMutation.mutate({ purpose: binding.purpose as "keyframe" | "video", modelBindingId: binding.id })}
                    >
                      Bind selected project
                    </button>
                  </div>
                );
              })}
              {!bindings.data?.length && <p className="muted">Create the fixed contract bindings after Contract, account, and quality evidence.</p>}
            </div>
            <label>Project<select aria-label="Project provider binding" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select project</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
            {selectedProject && <p className="muted">fallback policy: none · {selectedProject.name}</p>}
          </div>
        </div>
      )}

      {(message || error) && <div className={error ? "flash err" : "flash ok"} data-testid="provider-config-message">{error ?? message}</div>}
    </section>
  );
}
