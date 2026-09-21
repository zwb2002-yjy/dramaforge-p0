import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { Button, Disclosure, Field, Input, Select } from "../ui";
import { queryKeys } from "../../lib/queryKeys";

import {
  bindProjectProvider,
  createProviderConnection,
  createProviderModelBinding,
  listProjectProviderBindings,
  listProviderConnections,
  listProviderPlugins,
  listProviderModelBindings,
  listProviderProbes,
  recordProviderQualityEvidence,
  runProviderProbe,
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
  initialProjectId?: string;
};

const CAPABILITY_LABELS: Record<string, string> = {
  auth_models: "认证 / 模型目录",
  image_t2i: "图像文生图",
  image_i2i: "图像角色约束",
  video_i2v: "视频图生视频",
  video_poll_download: "视频轮询 / 下载",
};

export function ProviderConnectionPanel(props: ProviderConnectionPanelProps) {
  const [selectedPluginKey, setSelectedPluginKey] = useState<string | null>(null);
  const plugins = useQuery({
    queryKey: queryKeys.provider.plugins(),
    queryFn: listProviderPlugins,
    staleTime: 60_000,
    retry: false,
  });
  useEffect(() => {
    if (selectedPluginKey === null && plugins.isSuccess && plugins.data[0]) {
      const first = plugins.data[0];
      setSelectedPluginKey(`${first.provider_type}/${first.protocol_profile}`);
    }
  }, [plugins.data, plugins.isSuccess, selectedPluginKey]);
  // Only the initial choice is catalog-driven. Never substitute a disappeared
  // explicit choice or carry its unsaved credential into another provider.
  const selectedPlugin =
    selectedPluginKey === null
      ? plugins.data?.[0]
      : plugins.data?.find(
          (plugin) => `${plugin.provider_type}/${plugin.protocol_profile}` === selectedPluginKey,
        );
  if (!props.workspaceId)
    return (
      <section className="panel" data-testid="provider-config">
        <h2>图像与视频</h2>
        <p className="muted">配置供应商前请先选择或创建空间。</p>
      </section>
    );
  return (
    <section className="panel provider-config" data-testid="provider-config">
      <h2>图像与视频</h2>
      <p className="muted">连接供应商后，在「默认模型」中选择生成模型。密钥仅保存，不回显。</p>
      {plugins.isPending && <p role="status">正在读取供应商插件…</p>}
      {plugins.isError && (
        <p role="alert">
          供应商插件读取失败，不能确认可配置范围。
          <Button onClick={() => void plugins.refetch()}>重新读取插件</Button>
        </p>
      )}
      {plugins.isSuccess && !plugins.data.length && (
        <p role="status">当前没有可配置的供应商插件。</p>
      )}
      <Field>
        供应商
        <Select
          aria-label="供应商"
          value={
            selectedPlugin
              ? `${selectedPlugin.provider_type}/${selectedPlugin.protocol_profile}`
              : (selectedPluginKey ?? "")
          }
          disabled={!plugins.isSuccess || !plugins.data.length}
          onChange={(event) => setSelectedPluginKey(event.target.value)}
        >
          {!selectedPlugin && <option value={selectedPluginKey ?? ""}>请选择可用插件</option>}
          {(plugins.data ?? []).map((plugin) => (
            <option
              key={`${plugin.provider_type}/${plugin.protocol_profile}`}
              value={`${plugin.provider_type}/${plugin.protocol_profile}`}
            >
              {plugin.display_name}
            </option>
          ))}
        </Select>
      </Field>
      {selectedPluginKey && !selectedPlugin && plugins.isSuccess && (
        <p role="alert">所选插件已不在目录中，请显式重新选择；没有自动切换供应商。</p>
      )}
      {selectedPlugin && (
        <ProviderConnectionEditor
          key={`${props.workspaceId}/${selectedPlugin.provider_type}/${selectedPlugin.protocol_profile}`}
          {...props}
          selectedPlugin={selectedPlugin}
          catalogReady={plugins.isSuccess}
        />
      )}
    </section>
  );
}

function ProviderConnectionEditor({
  workspaceId,
  projects,
  initialProjectId,
  selectedPlugin,
  catalogReady,
}: ProviderConnectionPanelProps & {
  selectedPlugin: ProviderPluginRead;
  catalogReady: boolean;
}) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  // null means untouched, not an intentionally emptied draft.
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [capability, setCapability] = useState("auth_models");
  const [probeBindingId, setProbeBindingId] = useState("");
  const [imageModelId, setImageModelId] = useState("");
  const [videoModelId, setVideoModelId] = useState("");
  const [imageContractId, setImageContractId] = useState("");
  const [videoContractId, setVideoContractId] = useState("");
  const [referenceArtifactId, setReferenceArtifactId] = useState("");
  const [remoteTaskId, setRemoteTaskId] = useState("");
  const [remoteQueryKind, setRemoteQueryKind] = useState("video_id");
  const [projectChoice, setProjectChoice] = useState<string | null>(null);
  const selectedProjectId =
    projects.find((project) => project.id === (projectChoice ?? initialProjectId))?.id ?? "";
  const [qualityRunIds, setQualityRunIds] = useState<Record<string, string>>({});
  const [qualityArtifactIds, setQualityArtifactIds] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const connections = useQuery({
    queryKey: queryKeys.provider.connections(workspaceId),
    queryFn: () => listProviderConnections(workspaceId!),
    enabled: Boolean(workspaceId),
    retry: false,
  });
  const connection =
    connections.data?.find(
      (item) =>
        item.provider_type === selectedPlugin.provider_type &&
        item.protocol_profile === selectedPlugin.protocol_profile,
    ) ?? null;
  const connectionLoadError = connections.isError;
  const savedBaseUrl = connection?.base_url ?? selectedPlugin.default_base_url;
  const addressValue = baseUrl ?? savedBaseUrl;
  const addressDirty = baseUrl !== null && baseUrl.trim() !== savedBaseUrl;
  const readsReady = catalogReady && connections.isSuccess;
  const probes = useQuery({
    queryKey: queryKeys.provider.probes(workspaceId, connection?.id),
    queryFn: () => listProviderProbes(workspaceId!, connection!.id),
    enabled: Boolean(workspaceId && connection),
    retry: false,
  });
  const bindings = useQuery({
    queryKey: queryKeys.provider.bindings(workspaceId, connection?.id),
    queryFn: () => listProviderModelBindings(workspaceId!, connection!.id),
    enabled: Boolean(workspaceId && connection),
    retry: false,
  });

  const resetFeedback = () => {
    setMessage(null);
    setError(null);
  };

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.provider.connections(workspaceId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.provider.probesRoot(workspaceId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.provider.bindingsRoot(workspaceId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.model.catalog() });
    for (const project of projects) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.projectBindings(project.id),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.model.effectiveBindings(project.id),
      });
    }
  };

  const credentialMutation = useMutation({
    mutationFn: async () => {
      if (!readsReady || !addressValue.trim()) throw new Error("请先读取连接并填写服务地址");
      if (!workspaceId || !apiKey.trim()) throw new Error("请输入 API Key");
      if (connection) return updateProviderConnectionCredential(workspaceId, connection.id, apiKey);
      if (!selectedPlugin) throw new Error("正在加载供应商插件契约");
      return createProviderConnection(workspaceId, apiKey, {
        provider_type: selectedPlugin.provider_type,
        display_name: selectedPlugin.display_name,
        protocol_profile: selectedPlugin.protocol_profile,
        // Honour an address typed before the connection existed instead of
        // silently replacing it with the plugin default.
        base_url: addressValue.trim(),
      });
    },
    onMutate: resetFeedback,
    retry: false,
    onSuccess: async (saved) => {
      queryClient.setQueryData(
        queryKeys.provider.connections(workspaceId),
        (current: typeof connections.data) => [
          ...(current ?? []).filter((item) => item.id !== saved.id),
          saved,
        ],
      );
      setApiKey("");
      if (!connection) setBaseUrl(null);
      setMessage(
        "凭证已加密存储，本界面不可读取该 Key。保存不等于认证通过，也不保存已有连接的地址草稿。",
      );
      await refresh();
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const connectionMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("请先创建供应商连接");
      if (!readsReady || !addressValue.trim()) throw new Error("请先读取状态并填写服务地址");
      return updateProviderConnection(workspaceId, connection.id, {
        base_url: addressValue.trim(),
      });
    },
    onMutate: resetFeedback,
    retry: false,
    onSuccess: async (saved) => {
      queryClient.setQueryData(
        queryKeys.provider.connections(workspaceId),
        (current: typeof connections.data) =>
          (current ?? []).map((item) => (item.id === saved.id ? saved : item)),
      );
      setBaseUrl(null);
      setMessage("供应商连接地址已保存；尚未重新验证。已有探测记录不证明新地址可用。");
      await refresh();
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const probeMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      if (probeBlockedReason) throw new Error(probeBlockedReason);
      const probeBinding =
        capability === "auth_models"
          ? null
          : bindings.data?.find((binding) => binding.id === probeBindingId);
      return runProviderProbe(workspaceId, connection.id, {
        capability,
        ...(probeBinding ? { model_binding_id: probeBinding.id } : {}),
        paid_request_confirmed: false,
        ...(referenceArtifactId.trim()
          ? { reference_artifact_id: referenceArtifactId.trim() }
          : {}),
        ...(remoteTaskId.trim() ? { remote_task_id: remoteTaskId.trim() } : {}),
        ...(capability === "video_poll_download" ? { remote_query_kind: remoteQueryKind } : {}),
      });
    },
    onMutate: resetFeedback,
    retry: false,
    onSuccess: async (result) => {
      if (result.status === "passed")
        setMessage(
          `${CAPABILITY_LABELS[result.capability] ?? "能力"}检查通过，仅代表该次检查；不代表全部模型可用或质量合格。`,
        );
      else
        setError(
          result.status === "failed"
            ? "本次检查失败，请核对账号权限、已保存地址与模型目录。不会自动重试或更换模型。"
            : "本次检查尚未确认成功，请先核对结果；不会自动重试。",
        );
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.connections(workspaceId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.probes(workspaceId, connection?.id),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.bindings(workspaceId, connection?.id),
      });
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const bindingMutation = useMutation({
    retry: false,
    mutationFn: async (input: {
      media_type: "image" | "video";
      model_id: string;
      purpose: "keyframe" | "video";
      capability_contract_id: string;
    }) => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      if (!bindingReady) throw new Error("请先确认连接与绑定状态");
      return createProviderModelBinding(workspaceId, connection.id, input);
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      setImageModelId("");
      setVideoModelId("");
      setImageContractId("");
      setVideoContractId("");
      setMessage(`模型绑定已创建：${result.model_id}；尚未绑定项目。`);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.bindings(workspaceId, connection?.id),
      });
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const projectBindingMutation = useMutation({
    retry: false,
    mutationFn: async (input: { purpose: "keyframe" | "video"; modelBindingId: string }) => {
      if (!selectedProjectId || !projectBindings.isSuccess || !bindingReady)
        throw new Error("请先读取并选择项目");
      return bindProjectProvider(selectedProjectId, input.purpose, input.modelBindingId);
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      setMessage(
        `${result.purpose === "keyframe" ? "关键帧" : "视频"}项目绑定已保存；不静默回退。若模型方案另有覆盖，应以方案解析结果和正式执行身份为准。`,
      );
      await queryClient.invalidateQueries({
        queryKey: queryKeys.model.effectiveBindings(selectedProjectId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.projectBindings(selectedProjectId),
      });
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  // Read-only project bindings: the settings page answers "which model serves this
  // purpose?" after a refresh instead of printing a raw binding id (#9).
  const projectBindings = useQuery({
    queryKey: queryKeys.provider.projectBindings(selectedProjectId),
    queryFn: () => listProjectProviderBindings(selectedProjectId),
    enabled: Boolean(selectedProjectId),
    retry: false,
  });

  const connectionEnabledMutation = useMutation({
    retry: false,
    mutationFn: async (enabled: boolean) => {
      if (!workspaceId || !connection) throw new Error("请先创建供应商连接");
      return updateProviderConnection(workspaceId, connection.id, { enabled });
    },
    onMutate: resetFeedback,
    onSuccess: async (_result, enabled) => {
      setMessage(enabled ? "供应商连接已启用。" : "供应商连接已停用；已停用的连接不会参与生成。");
      await refresh();
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const qualityEvidenceMutation = useMutation({
    retry: false,
    mutationFn: async (input: {
      binding: ProviderModelBindingRead;
      nodeRunId: string;
      artifactId: string;
    }) => {
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
      setMessage("人工验收质量证据已记录。它不替代账号验证，也不是首次生成的门槛。");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.provider.bindingsRoot(workspaceId),
      });
    },
    onError: () =>
      setError("操作结果未确认，草稿已保留。请先重新读取状态，核对是否已保存；不要盲目重复提交。"),
  });

  const pluginCapabilities = selectedPlugin?.capabilities ?? ["auth_models"];
  const pluginModels = selectedPlugin?.models ?? [];
  const discoveredModelIds = useMemo(() => {
    if (connection?.verification_status !== "verified" || !probes.isSuccess) return null;
    const latestSuccessfulCatalog = probes.data.find(
      (probe) => probe.capability === "auth_models" && probe.status === "passed",
    );
    const ids = latestSuccessfulCatalog?.discovered_model_ids ?? [];
    // Pre-0074 evidence was backfilled with an empty list. Treat it as unknown
    // so an existing verified installation does not lose all choices merely
    // because its historical proof predates persisted discovery.
    return ids.length ? new Set(ids) : null;
  }, [connection?.verification_status, probes.data, probes.isSuccess]);
  const supportedModelIds = new Set(pluginModels.map((model) => model.model_id));
  const unsupportedDiscoveredModels = discoveredModelIds
    ? [...discoveredModelIds].filter((modelId) => !supportedModelIds.has(modelId)).sort()
    : [];
  const imageContracts = pluginModels.filter((model) => model.media_type === "image");
  const videoContracts = pluginModels.filter((model) => model.media_type === "video");
  const selectableModelIds = discoveredModelIds
    ? [...discoveredModelIds].sort()
    : pluginModels.map((model) => model.model_id);
  const activeModelsByContract = useMemo(
    () =>
      new Map(
        (selectedPlugin?.models ?? []).map((model) => [
          `${model.catalog_entry_id}:${model.capability_manifest_hash}`,
          model,
        ]),
      ),
    [selectedPlugin?.models],
  );
  const activeModelFor = (binding: ProviderModelBindingRead) =>
    activeModelsByContract.get(`${binding.catalog_entry_id}:${binding.capability_manifest_hash}`) ??
    null;
  // Match the backend's read-only allowlist. Missing pricing metadata must not
  // make a generation probe appear free or authorized.
  const paidProbe =
    !["auth_models", "video_poll_download"].includes(capability) ||
    selectedPlugin.paid_capabilities.includes(capability);
  const busy =
    credentialMutation.isPending ||
    connectionMutation.isPending ||
    probeMutation.isPending ||
    bindingMutation.isPending ||
    projectBindingMutation.isPending ||
    connectionEnabledMutation.isPending ||
    qualityEvidenceMutation.isPending;
  // Probe history can include a late response for an old credential/endpoint.
  // Only the backend's revision-checked current projection can revoke access.
  const authenticationRejected = connection?.verification_status === "failed";
  const bindingReady =
    readsReady &&
    Boolean(connection?.enabled && connection?.credential_configured) &&
    !authenticationRejected &&
    bindings.isSuccess;
  const canManageBindings = bindingReady && !busy;
  const probeCandidates = (bindings.data ?? []).filter(
    (binding) =>
      binding.enabled &&
      activeModelFor(binding) &&
      binding.purpose === (capability.startsWith("image_") ? "keyframe" : "video"),
  );
  const probeBlockedReason = !readsReady
    ? "请先重新读取连接与插件状态。"
    : !connection?.enabled
      ? "连接已停用，请先启用。"
      : !connection.credential_configured
        ? "尚未配置凭证。"
        : addressDirty || apiKey.length > 0
          ? "有未保存的地址或凭证，请先保存或放弃草稿；探测只使用已保存配置。"
          : !selectedPlugin.implemented
            ? "该插件目前仅提供目录，尚未实现调用。"
            : paidProbe
              ? "付费探测暂不可用：当前接口不能提交单次正数预算与 Owner 授权，不能用勾选确认代替授权。"
              : capability !== "auth_models" &&
                  (!bindings.isSuccess ||
                    !probeCandidates.some((binding) => binding.id === probeBindingId))
                ? "请先读取并明确选择本次探测的模型绑定。"
                : ["image_i2i", "video_i2v"].includes(capability) && !referenceArtifactId.trim()
                  ? "请提供参考产物 ID。"
                  : capability === "video_poll_download" && !remoteTaskId.trim()
                    ? "请提供远端任务 ID。"
                    : null;

  if (!workspaceId) {
    return (
      <section className="panel" data-testid="provider-config">
        <h3>图像与视频</h3>
        <p className="muted">配置供应商前请先选择或创建空间。</p>
      </section>
    );
  }

  function submitCredential(event: FormEvent) {
    event.preventDefault();
    if (!busy && readsReady && addressValue.trim() && apiKey.trim()) credentialMutation.mutate();
  }

  const selectedProject = projects.find((project) => project.id === selectedProjectId);

  return (
    <div className="provider-connection-editor">
      <div className="panel-header">
        <span
          data-testid="provider-connection-status"
          className={
            connectionLoadError
              ? "status-bad"
              : !catalogReady
                ? "status-pending"
                : authenticationRejected
                  ? "status-bad"
                  : "status-pending"
          }
        >
          {connectionLoadError
            ? "读取失败"
            : !catalogReady
              ? "插件状态未确认"
              : connections.isPending
                ? "读取中…"
                : connection && !connection.enabled
                  ? "已停用"
                  : authenticationRejected
                    ? "当前认证被拒绝；请重新核对连接与账号"
                    : connection?.verification_status === "verified"
                      ? "曾通过认证（不代表当前可用）"
                      : connection
                        ? "待验证"
                        : "未配置"}
        </span>
        {connection && (
          <Button
            type="button"
            tone="ghost"
            data-testid="provider-connection-toggle"
            disabled={busy || !readsReady}
            onClick={() => connectionEnabledMutation.mutate(!connection.enabled)}
          >
            {connection.enabled ? "停用连接" : "启用连接"}
          </Button>
        )}
        {connection && !connection.enabled && (
          <span className="status-pending" data-testid="provider-connection-disabled-note">
            已停用：不会参与生成
          </span>
        )}
      </div>

      {connectionLoadError && (
        <p className="flash err" role="alert">
          连接列表加载失败；状态未知，不能当作未配置。
        </p>
      )}
      <Button type="button" tone="ghost" disabled={busy} onClick={() => void refresh()}>
        重新读取连接状态
      </Button>

      <div className="provider-plugin-selector">
        <Field>
          <span className="status-label">服务地址</span>
          <Input
            aria-label="供应商服务地址"
            value={addressValue}
            disabled={busy || !readsReady}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              resetFeedback();
            }}
            placeholder="供应商 Base URL，不可留空"
          />
        </Field>
        {connection && (
          <Button
            type="button"
            onClick={() => connectionMutation.mutate()}
            disabled={busy || !readsReady || !addressDirty || !addressValue.trim()}
          >
            保存连接地址
          </Button>
        )}
      </div>

      {apiKey && (
        <p role="status">
          有未保存的密钥，仅保留在当前表单；切换供应商或工作空间会清除，不会自动保存。
        </p>
      )}
      {addressDirty && <p role="status">服务地址有未保存修改。轮换 Key 不会保存此地址。</p>}
      {!addressValue.trim() && (
        <p role="alert">服务地址不可为空；不会自动替换成旧地址或默认地址。</p>
      )}
      {(addressDirty || apiKey) && (
        <Button
          type="button"
          tone="ghost"
          disabled={busy}
          onClick={() => {
            setBaseUrl(null);
            setApiKey("");
            resetFeedback();
          }}
        >
          放弃连接草稿
        </Button>
      )}
      <p className="provider-credential-status">
        密钥：
        {connections.isPending || connectionLoadError || !catalogReady
          ? "状态未知"
          : connection?.credential_configured
            ? "已保存（不回显）"
            : "未配置"}
      </p>
      <form className="provider-key-form" onSubmit={submitCredential}>
        <Field>
          {connection
            ? `轮换 ${selectedPlugin?.display_name ?? "供应商"} API Key`
            : `添加 ${selectedPlugin?.display_name ?? "供应商"} API Key`}
          <Input
            aria-label={`${selectedPlugin?.display_name ?? "供应商"} API Key`}
            type="password"
            disabled={busy || !readsReady}
            value={apiKey}
            onChange={(event) => {
              setApiKey(event.target.value);
              resetFeedback();
            }}
            placeholder={
              connection?.credential_configured ? "已保存；输入新密钥以更换" : "输入 API Key"
            }
            autoComplete="new-password"
          />
        </Field>
        <Button
          tone="primary"
          type="submit"
          disabled={busy || !readsReady || !apiKey.trim() || !addressValue.trim()}
        >
          {credentialMutation.isPending ? "保存中…" : connection ? "轮换 Key" : "保存加密 Key"}
        </Button>
      </form>

      <Disclosure title="连接详情与诊断" testId="provider-diagnostics-disclosure">
        <div className="provider-fixed-fields">
          <div>
            <span className="status-label">当前连接</span>
            <code>{connection?.display_name ?? "尚未配置"}</code>
          </div>
          <div>
            <span className="status-label">协议</span>
            <code>{selectedPlugin?.protocol_profile ?? "-"}</code>
          </div>
          <div>
            <span className="status-label">凭证</span>
            <strong>{connection?.credential_configured ? "已配置 · 仅写入" : "缺失"}</strong>
          </div>
          <div>
            <span className="status-label">密钥版本</span>
            <code>{connection?.credential_key_version ?? "-"}</code>
          </div>
        </div>

        <div className="provider-plugin-facts">
          <div>
            <span className="status-label">模型数</span>
            <strong>{pluginModels.length}</strong>
          </div>
          <div>
            <span className="status-label">插件状态</span>
            <strong>{selectedPlugin?.implemented ? "已实现" : "仅目录"}</strong>
          </div>
        </div>
        {connection && (
          <div className="provider-grid">
            <div>
              <h3>能力探测</h3>
              <form
                className="form-grid"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!busy && !probeBlockedReason) probeMutation.mutate();
                }}
              >
                <Field>
                  能力
                  <Select
                    value={capability}
                    aria-label="探测能力"
                    disabled={busy}
                    onChange={(event) => {
                      setCapability(event.target.value);
                      setProbeBindingId("");
                      resetFeedback();
                    }}
                  >
                    {pluginCapabilities.map((value) => (
                      <option value={value} key={value}>
                        {CAPABILITY_LABELS[value] ?? value}
                      </option>
                    ))}
                  </Select>
                </Field>
                {capability !== "auth_models" && (
                  <Field>
                    本次探测的模型绑定
                    <Select
                      aria-label="探测模型绑定"
                      value={probeBindingId}
                      disabled={busy || !bindings.isSuccess}
                      onChange={(event) => setProbeBindingId(event.target.value)}
                    >
                      <option value="">请选择精确模型，不自动代选</option>
                      {probeCandidates.map((binding) => (
                        <option key={binding.id} value={binding.id}>
                          {binding.model_id} · {binding.id}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                <p className="muted">
                  认证 /
                  模型目录检查会访问供应商，但不会生成媒体；只有显式点击才会运行。历史通过记录不等于当前地址、凭证和所有模型均可用。
                </p>
                {probeBlockedReason && <p role="status">{probeBlockedReason}</p>}
                {(capability === "image_i2i" || capability === "video_i2v") && (
                  <Field>
                    参考产物 ID
                    <Input
                      value={referenceArtifactId}
                      onChange={(event) => setReferenceArtifactId(event.target.value)}
                      placeholder="参考探测必填"
                    />
                  </Field>
                )}
                {capability === "video_poll_download" && (
                  <>
                    <Field>
                      远端任务 ID
                      <Input
                        value={remoteTaskId}
                        onChange={(event) => setRemoteTaskId(event.target.value)}
                      />
                    </Field>
                    <Field>
                      查询类型
                      <Select
                        value={remoteQueryKind}
                        onChange={(event) => setRemoteQueryKind(event.target.value)}
                      >
                        <option value="video_id">视频 ID（video_id）</option>
                        <option value="task_id">任务 ID（task_id）</option>
                      </Select>
                    </Field>
                  </>
                )}
                <Button type="submit" disabled={busy || Boolean(probeBlockedReason)}>
                  {probeMutation.isPending
                    ? "探测中…"
                    : paidProbe
                      ? "付费探测暂不可用"
                      : "运行探测"}
                </Button>
              </form>
              <p className="muted">
                以下是历史探测记录，可能来自旧凭证或旧地址；不按记录时间推断当前配置已认证。当前认证状态由后端核对连接版本后更新。
              </p>
              <ul className="dense provider-evidence-list" data-testid="provider-probes">
                {(probes.isSuccess ? probes.data : []).slice(0, 6).map((probe) => (
                  <li key={probe.probe_id}>
                    <span>{CAPABILITY_LABELS[probe.capability] ?? "其他能力"}</span>
                    <strong
                      className={
                        probe.status === "passed"
                          ? "status-ok"
                          : probe.status === "failed"
                            ? "status-bad"
                            : "status-pending"
                      }
                    >
                      {probe.status === "passed"
                        ? "通过"
                        : probe.status === "failed"
                          ? "失败"
                          : "待定"}
                    </strong>
                    <span className="muted">
                      {probe.evidence_level} · {probe.tested_at}
                    </span>
                    {probe.error_code && (
                      <span className="status-bad">错误代码：{probe.error_code}</span>
                    )}
                  </li>
                ))}
                {probes.isPending && <li role="status">正在读取能力证据…</li>}
                {probes.isError && (
                  <li role="alert">
                    能力证据读取失败，不能判断是否已有结果。
                    <Button onClick={() => void probes.refetch()}>重新读取证据</Button>
                  </li>
                )}
                {probes.isSuccess && !probes.data.length && (
                  <li className="muted">暂无能力证据。</li>
                )}
              </ul>
            </div>

            <div>
              <h3>模型与项目绑定</h3>
              <p className="muted">
                认证后只列出当前地址与账号实际返回、且已有执行合同的模型。创建绑定不代表质量已通过；每个模型的证据独立。
              </p>
              {discoveredModelIds && (
                <div data-testid="provider-discovered-models">
                  <p className="muted">
                    账号发现 {discoveredModelIds.size} 个模型。选择模型后，再为其指定能力插件合同。
                  </p>
                  {unsupportedDiscoveredModels.length > 0 && (
                    <p className="status-pending">
                      尚未匹配能力插件：{unsupportedDiscoveredModels.join("、")}
                    </p>
                  )}
                </div>
              )}
              <div className="toolbar">
                {(["image", "video"] as const).map((mediaType) => {
                  const purpose = mediaType === "image" ? "keyframe" : "video";
                  const value = mediaType === "image" ? imageModelId : videoModelId;
                  const contractId = mediaType === "image" ? imageContractId : videoContractId;
                  const contracts = mediaType === "image" ? imageContracts : videoContracts;
                  const available = selectableModelIds.filter(
                    (modelId) =>
                      !(bindings.data ?? []).some(
                        (binding) =>
                          binding.purpose === purpose && binding.model_id === modelId,
                      ),
                  );
                  return (
                    <div key={mediaType}>
                      <Select
                        aria-label={mediaType === "image" ? "关键帧模型" : "视频模型"}
                        value={value}
                        disabled={!canManageBindings || !available.length}
                        onChange={(event) => {
                          const modelId = event.target.value;
                          (mediaType === "image" ? setImageModelId : setVideoModelId)(modelId);
                          const exact = contracts.find((contract) => contract.model_id === modelId);
                          (mediaType === "image" ? setImageContractId : setVideoContractId)(
                            exact?.catalog_entry_id ??
                              (contracts.length === 1 ? contracts[0].catalog_entry_id : ""),
                          );
                          resetFeedback();
                        }}
                      >
                        <option value="">
                          {available.length ? "选择探测到的模型…" : "没有可新增模型"}
                        </option>
                        {available.map((modelId) => (
                          <option key={modelId} value={modelId}>
                            {pluginModels.find((model) => model.model_id === modelId)?.display_name ??
                              modelId}
                            {supportedModelIds.has(modelId) ? ` · ${modelId}` : " · 探测发现"}
                          </option>
                        ))}
                      </Select>
                      <Select
                        aria-label={
                          mediaType === "image" ? "关键帧能力插件" : "视频能力插件"
                        }
                        value={contractId}
                        disabled={!canManageBindings || !value || !contracts.length}
                        onChange={(event) =>
                          (mediaType === "image" ? setImageContractId : setVideoContractId)(
                            event.target.value,
                          )
                        }
                      >
                        <option value="">选择能力插件合同…</option>
                        {contracts.map((contract) => (
                          <option key={contract.catalog_entry_id} value={contract.catalog_entry_id}>
                            {contract.display_name} · {contract.capabilities.join(" / ")}
                          </option>
                        ))}
                      </Select>
                      <Button
                        type="button"
                        disabled={
                          !canManageBindings || !available.includes(value) || !contractId
                        }
                        onClick={() =>
                          bindingMutation.mutate({
                            media_type: mediaType,
                            purpose,
                            model_id: value,
                            capability_contract_id: contractId,
                          })
                        }
                      >
                        添加{mediaType === "image" ? "关键帧" : "视频"}模型绑定
                      </Button>
                    </div>
                  );
                })}
              </div>
              <div className="provider-binding-list">
                {(bindings.isSuccess ? bindings.data : []).map((binding) => {
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
                        <span className="muted">
                          {binding.purpose} ·{" "}
                          {activeModel ? activeModel.model_revision : "历史合同"}
                        </span>
                        {!binding.enabled && (
                          <p className="status-pending">绑定已停用，不可用于新绑定。</p>
                        )}
                        {!activeModel && (
                          <p className="status-pending">历史合同仅供核对，不会自动替换为新模型。</p>
                        )}
                        <div
                          className="provider-binding-states"
                          data-testid={`binding-states-${binding.purpose}`}
                        >
                          {states.map(([state, passed]) => (
                            <span
                              key={state}
                              className={
                                passed ? "evidence-state passed" : "evidence-state pending"
                              }
                              data-testid={`binding-${binding.purpose}-${state}`}
                            >
                              {state === "quality_gated" ? "人工质量认证" : zhEvidenceState(state)}
                              ：{passed ? "通过" : "尚无通过证据"}
                            </span>
                          ))}
                        </div>
                        {!binding.quality_gated && binding.account_verified && (
                          <div className="quality-evidence-form">
                            <Input
                              aria-label={`${binding.purpose} 质量 NodeRun ID`}
                              placeholder="人物/时序复核 NodeRun ID"
                              value={qualityRunIds[binding.id] ?? ""}
                              onChange={(event) =>
                                setQualityRunIds((current) => ({
                                  ...current,
                                  [binding.id]: event.target.value,
                                }))
                              }
                            />
                            <Input
                              aria-label={`${binding.purpose} 质量产物 ID`}
                              placeholder="质量产物 ID"
                              value={qualityArtifactIds[binding.id] ?? ""}
                              onChange={(event) =>
                                setQualityArtifactIds((current) => ({
                                  ...current,
                                  [binding.id]: event.target.value,
                                }))
                              }
                            />
                            <Button
                              type="button"
                              disabled={
                                !canManageBindings ||
                                !qualityRunIds[binding.id]?.trim() ||
                                !qualityArtifactIds[binding.id]?.trim()
                              }
                              onClick={() =>
                                qualityEvidenceMutation.mutate({
                                  binding,
                                  nodeRunId: qualityRunIds[binding.id] ?? "",
                                  artifactId: qualityArtifactIds[binding.id] ?? "",
                                })
                              }
                            >
                              记录质量证据
                            </Button>
                          </div>
                        )}
                      </div>
                      <Button
                        type="button"
                        disabled={
                          !canManageBindings ||
                          !activeModel ||
                          !binding.enabled ||
                          !binding.documented ||
                          !binding.contract_tested ||
                          !binding.account_verified ||
                          !selectedProjectId ||
                          !projectBindings.isSuccess ||
                          !["keyframe", "video"].includes(binding.purpose)
                        }
                        onClick={() =>
                          projectBindingMutation.mutate({
                            purpose: binding.purpose as "keyframe" | "video",
                            modelBindingId: binding.id,
                          })
                        }
                      >
                        绑定所选项目
                      </Button>
                    </div>
                  );
                })}
                {bindings.isPending && <p role="status">正在读取模型绑定…</p>}
                {bindings.isError && (
                  <p role="alert">
                    模型绑定读取失败；不会当作没有绑定。
                    <Button onClick={() => void bindings.refetch()}>重新读取模型绑定</Button>
                  </p>
                )}
                {bindings.isSuccess && !bindings.data.length && (
                  <p className="muted">
                    尚无模型绑定。可先添加目录中的模型；人工质量认证不是首次生成的前置条件。
                  </p>
                )}
              </div>
              <Field>
                项目
                <Select
                  aria-label="项目 Provider 绑定"
                  value={selectedProjectId}
                  disabled={busy}
                  onChange={(event) => {
                    setProjectChoice(event.target.value);
                    resetFeedback();
                  }}
                >
                  <option value="">选择项目</option>
                  {projects.map((project) => (
                    <option value={project.id} key={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
              {selectedProject && (
                <div className="provider-project-bindings" data-testid="project-provider-bindings">
                  <p className="muted">
                    已保存的项目供应商绑定 · {selectedProject.name}
                    。这是方案未覆盖时的指定来源，不代表已实际运行；不会在所选模型失败时自动替换。
                  </p>
                  {projectBindings.isPending && <p role="status">正在读取项目绑定…</p>}
                  {projectBindings.isSuccess &&
                    (projectBindings.data.length ? (
                      <ul className="dense">
                        {projectBindings.data.map((row) => (
                          <li key={row.id}>
                            <span>
                              {row.purpose === "keyframe" ? "关键帧" : "视频"}：
                              {row.display_name ?? row.model_id ?? "未知模型"}
                              {row.provider_type ? `（${row.provider_type}）` : ""}
                              <code>{row.model_id ?? "模型身份未返回"}</code>
                            </span>
                            {row.model_binding_enabled === false && (
                              <small className="status-pending">绑定已停用</small>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">该项目尚未绑定关键帧或视频模型。</p>
                    ))}
                  {projectBindings.isError && (
                    <p className="status-bad" role="alert">
                      当前绑定读取失败。
                      <Button onClick={() => void projectBindings.refetch()}>
                        重新读取项目绑定
                      </Button>
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </Disclosure>

      {message && (connections.isError || bindings.isError || probes.isError) && (
        <p role="status">
          操作已收到回执，但部分状态重新读取失败；请复核，不能把旧证据当成当前可用性。
        </p>
      )}
      {(message || error) && (
        <div
          role={error ? "alert" : "status"}
          className={error ? "flash err" : "flash ok"}
          data-testid="provider-config-message"
        >
          {error ?? message}
        </div>
      )}
    </div>
  );
}
