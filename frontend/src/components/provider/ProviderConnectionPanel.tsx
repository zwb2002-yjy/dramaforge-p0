import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, Power, RefreshCw, Save, X } from "lucide-react";
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
import { ProviderModelRow } from "./ProviderModelRow";
import { providerConnectionCopy as copy } from "./providerConnectionCopy";

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
  const selectionKey = `dramaforge.providerConnection.${props.workspaceId ?? "none"}`;
  const [selectedPluginKey, setSelectedPluginKey] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(selectionKey);
    } catch {
      return null;
    }
  });
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
    <section className="provider-config" data-testid="provider-config">
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
      <div className="provider-setup-heading">
        <h2>{copy.connection}</h2>
        <Field className="provider-type-selector">
          {copy.provider}
          <Select
            aria-label="供应商"
            value={
              selectedPlugin
                ? `${selectedPlugin.provider_type}/${selectedPlugin.protocol_profile}`
                : (selectedPluginKey ?? "")
            }
            disabled={!plugins.isSuccess || !plugins.data.length}
            onChange={(event) => {
              setSelectedPluginKey(event.target.value);
              try {
                window.localStorage.setItem(selectionKey, event.target.value);
              } catch {
                // The current page selection still works when storage is unavailable.
              }
            }}
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
      </div>
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
  const [bindingFormOpen, setBindingFormOpen] = useState(false);
  const [bindingMediaType, setBindingMediaType] = useState<"image" | "video">("image");
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

  const probeMutation = useMutation<Awaited<ReturnType<typeof runProviderProbe>>, unknown, boolean>({
    mutationFn: async (catalogOnly) => {
      if (!workspaceId || !connection) throw new Error("请先创建当前供应商连接");
      const requestedCapability = catalogOnly ? "auth_models" : capability;
      const blocked = catalogOnly ? catalogBlockedReason : probeBlockedReason;
      if (blocked) throw new Error(blocked);
      const probeBinding =
        requestedCapability === "auth_models"
          ? null
          : bindings.data?.find((binding) => binding.id === probeBindingId);
      return runProviderProbe(workspaceId, connection.id, {
        capability: requestedCapability,
        ...(probeBinding ? { model_binding_id: probeBinding.id } : {}),
        paid_request_confirmed: false,
        ...(!catalogOnly && referenceArtifactId.trim()
          ? { reference_artifact_id: referenceArtifactId.trim() }
          : {}),
        ...(!catalogOnly && remoteTaskId.trim() ? { remote_task_id: remoteTaskId.trim() } : {}),
        ...(requestedCapability === "video_poll_download"
          ? { remote_query_kind: remoteQueryKind }
          : {}),
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
      setBindingFormOpen(false);
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
  const latestModels = useMemo(() => {
    const revisions = new Intl.Collator(undefined, { numeric: true });
    const current = new Map<string, ProviderPluginRead["models"][number]>();
    for (const model of pluginModels) {
      const previous = current.get(model.model_id);
      if (!previous || revisions.compare(model.model_revision, previous.model_revision) > 0) {
        current.set(model.model_id, model);
      }
    }
    return [...current.values()];
  }, [pluginModels]);
  const imageContracts = latestModels.filter((model) => model.media_type === "image");
  const videoContracts = latestModels.filter((model) => model.media_type === "video");
  const selectableModelIds = discoveredModelIds
    ? [...discoveredModelIds].sort()
    : [...new Set(latestModels.map((model) => model.model_id))];
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
  const catalogBlockedReason = !readsReady
    ? "请先重新读取连接与插件状态。"
    : !connection?.enabled
      ? "连接已停用，请先启用。"
      : !connection.credential_configured
        ? "尚未配置凭证。"
        : addressDirty || apiKey.length > 0
          ? "有未保存的地址或凭证，请先保存或放弃草稿；探测只使用已保存配置。"
          : !selectedPlugin.implemented
            ? "该插件目前仅提供目录，尚未实现调用。"
            : null;
  const probeBlockedReason =
    catalogBlockedReason ??
    (paidProbe
      ? "付费探测暂不可用：当前接口不能提交单次正数预算与 Owner 授权，不能用勾选确认代替授权。"
      : capability !== "auth_models" &&
          (!bindings.isSuccess || !probeCandidates.some((binding) => binding.id === probeBindingId))
        ? "请先读取并明确选择本次探测的模型绑定。"
        : ["image_i2i", "video_i2v"].includes(capability) && !referenceArtifactId.trim()
          ? "请提供参考产物 ID。"
          : capability === "video_poll_download" && !remoteTaskId.trim()
            ? "请提供远端任务 ID。"
            : null);

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

  const allBindings = bindings.isSuccess ? bindings.data : [];
  const latestContractIds = new Set(latestModels.map((model) => model.catalog_entry_id));
  const historical = (binding: ProviderModelBindingRead) =>
    !activeModelFor(binding) || !latestContractIds.has(binding.catalog_entry_id ?? "");
  const currentBindings = allBindings.filter((binding) => !historical(binding));
  const historicalBindings = allBindings.filter(historical);
  const modelValue = bindingMediaType === "image" ? imageModelId : videoModelId;
  const contractValue = bindingMediaType === "image" ? imageContractId : videoContractId;
  const contracts = bindingMediaType === "image" ? imageContracts : videoContracts;
  const setModelValue = bindingMediaType === "image" ? setImageModelId : setVideoModelId;
  const setContractValue = bindingMediaType === "image" ? setImageContractId : setVideoContractId;
  const modelPurpose = bindingMediaType === "image" ? "keyframe" : "video";
  const alreadyBound = allBindings.some(
    (binding) =>
      binding.purpose === modelPurpose &&
      binding.model_id === modelValue &&
      binding.catalog_entry_id === contractValue,
  );
  const connectionStatus = connectionLoadError
    ? "读取失败"
    : !catalogReady
      ? "状态未知"
      : connections.isPending
        ? "读取中…"
        : !connection
          ? "未配置"
          : !connection.enabled
            ? copy.disabled
            : authenticationRejected
              ? "认证失败"
              : connection.verification_status === "verified"
                ? "目录已验证"
                : copy.unverified;

  function renderModel(binding: ProviderModelBindingRead) {
    const activeModel = activeModelFor(binding);
    return (
      <ProviderModelRow
        key={binding.id}
        binding={binding}
        model={activeModel}
        action={
          <Button
            tone="ghost"
            className="provider-icon-button"
            aria-label="绑定所选项目"
            title={selectedProject ? "用于项目：" + selectedProject.name : "先选择项目"}
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
            <Link2 size={16} aria-hidden="true" />
          </Button>
        }
      >
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
      </ProviderModelRow>
    );
  }

  return (
    <div className="provider-connection-editor">
      <div className="provider-connection-toolbar">
        <span
          data-testid="provider-connection-status"
          className={connectionLoadError || authenticationRejected ? "status-bad" : "muted"}
          title="目录验证仅代表最近一次目录检查，生成能力需单独验证"
        >
          {connectionStatus}
        </span>
        <div className="provider-toolbar-actions">
          <Button
            tone="ghost"
            className="provider-icon-button"
            aria-label="重新读取连接状态"
            title="刷新状态"
            disabled={busy}
            onClick={() => void refresh()}
          >
            <RefreshCw size={16} aria-hidden="true" />
          </Button>
          {connection && (
            <Button
              tone="ghost"
              className="provider-icon-button"
              data-testid="provider-connection-toggle"
              aria-label={connection.enabled ? "停用连接" : "启用连接"}
              title={connection.enabled ? "停用连接" : "启用连接"}
              disabled={busy || !readsReady}
              onClick={() => connectionEnabledMutation.mutate(!connection.enabled)}
            >
              <Power size={16} aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>
      {connection && !connection.enabled && (
        <span className="status-pending" data-testid="provider-connection-disabled-note">
          已停用：不会参与生成
        </span>
      )}
      {connectionLoadError && (
        <p className="flash err" role="alert">
          连接列表加载失败；状态未知，不能当作未配置。
        </p>
      )}

      <div className="provider-connection-fields">
        <div className="provider-control-row">
          <Field>
            {copy.address}
            <Input
              aria-label="供应商服务地址"
              value={addressValue}
              disabled={busy || !readsReady}
              onChange={(event) => {
                setBaseUrl(event.target.value);
                resetFeedback();
              }}
              placeholder="https://api.example.com 或局域网服务地址"
            />
          </Field>
          {connection && (
            <Button
              className="provider-icon-button"
              aria-label="保存连接地址"
              title="保存地址"
              disabled={busy || !readsReady || !addressDirty || !addressValue.trim()}
              onClick={() => connectionMutation.mutate()}
            >
              <Save size={16} aria-hidden="true" />
            </Button>
          )}
        </div>
        <form className="provider-control-row" onSubmit={submitCredential}>
          <Field>
            {copy.key}
            <Input
              aria-label={selectedPlugin.display_name + " API Key"}
              type="password"
              disabled={busy || !readsReady}
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                resetFeedback();
              }}
              placeholder={connection?.credential_configured ? copy.savedKey : copy.newKey}
              autoComplete="new-password"
            />
          </Field>
          <Button
            tone="primary"
            type="submit"
            className="provider-icon-button"
            aria-label={connection ? "轮换 Key" : "保存加密 Key"}
            title={connection ? "更新密钥" : "保存连接"}
            disabled={busy || !readsReady || !apiKey.trim() || !addressValue.trim()}
          >
            <Save size={16} aria-hidden="true" />
          </Button>
        </form>
      </div>
      {(addressDirty || apiKey) && (
        <div className="provider-draft-status">
          <span role="status">
            {addressDirty ? "地址有未保存修改；更新密钥不会保存地址。" : "密钥尚未保存。"}
          </span>
          <Button
            tone="ghost"
            aria-label="放弃连接草稿"
            title="放弃草稿"
            className="provider-icon-button"
            disabled={busy}
            onClick={() => {
              setBaseUrl(null);
              setApiKey("");
              resetFeedback();
            }}
          >
            <X size={16} aria-hidden="true" />
          </Button>
        </div>
      )}
      {!addressValue.trim() && <p role="alert">地址不能为空，未自动替换为旧地址。</p>}

      <section className="provider-model-section" aria-label={copy.models}>
        <header className="provider-section-heading">
          <h3>
            {copy.models} <span className="muted">{allBindings.length}</span>
          </h3>
          <div className="provider-toolbar-actions">
            <Button
              tone="ghost"
              disabled={busy || Boolean(catalogBlockedReason)}
              title={catalogBlockedReason ?? undefined}
              data-testid="provider-read-models"
              onClick={() => probeMutation.mutate(true)}
            >
              <RefreshCw size={16} aria-hidden="true" />
              {copy.readModels}
            </Button>
            <Button
              tone="primary"
              aria-expanded={bindingFormOpen}
              onClick={() => setBindingFormOpen(!bindingFormOpen)}
            >
              <Plus size={16} aria-hidden="true" />
              {copy.addModel}
            </Button>
          </div>
        </header>
        {bindingFormOpen && (
          <form
            className="provider-add-model-form"
            data-testid="provider-add-model-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                canManageBindings &&
                selectableModelIds.includes(modelValue) &&
                contractValue &&
                !alreadyBound
              )
                bindingMutation.mutate({
                  media_type: bindingMediaType,
                  purpose: modelPurpose,
                  model_id: modelValue,
                  capability_contract_id: contractValue,
                });
            }}
          >
            <Field>
              类型
              <Select
                aria-label="模型类型"
                value={bindingMediaType}
                onChange={(event) => setBindingMediaType(event.target.value as "image" | "video")}
              >
                <option value="image">{copy.image}</option>
                <option value="video">{copy.video}</option>
              </Select>
            </Field>
            <Field>
              {copy.remoteModel}
              <Select
                aria-label={bindingMediaType === "image" ? "关键帧模型" : "视频模型"}
                value={modelValue}
                disabled={!canManageBindings || !selectableModelIds.length}
                onChange={(event) => {
                  const id = event.target.value;
                  setModelValue(id);
                  setContractValue(
                    contracts.find((model) => model.model_id === id)?.catalog_entry_id ??
                      (contracts.length === 1 ? contracts[0].catalog_entry_id : ""),
                  );
                  resetFeedback();
                }}
              >
                <option value="">选择模型</option>
                {selectableModelIds.map((id) => (
                  <option value={id} key={id}>
                    {latestModels.find((model) => model.model_id === id)?.display_name ?? id}
                  </option>
                ))}
              </Select>
            </Field>
            <Field>
              {copy.contract}
              <Select
                aria-label={bindingMediaType === "image" ? "关键帧能力插件" : "视频能力插件"}
                value={contractValue}
                disabled={!canManageBindings || !modelValue || !contracts.length}
                onChange={(event) => setContractValue(event.target.value)}
              >
                <option value="">选择方案</option>
                {contracts.map((model) => (
                  <option value={model.catalog_entry_id} key={model.catalog_entry_id}>
                    {model.display_name} · {model.model_revision}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="provider-add-model-actions">
              <Button
                tone="primary"
                type="submit"
                aria-label={
                  bindingMediaType === "image" ? "添加关键帧模型绑定" : "添加视频模型绑定"
                }
                disabled={
                  !canManageBindings ||
                  !selectableModelIds.includes(modelValue) ||
                  !contractValue ||
                  alreadyBound
                }
              >
                添加
              </Button>
              <Button
                tone="ghost"
                className="provider-icon-button"
                aria-label={copy.closeAdd}
                title={copy.closeAdd}
                onClick={() => setBindingFormOpen(false)}
              >
                <X size={16} aria-hidden="true" />
              </Button>
            </div>
            {discoveredModelIds && (
              <span className="muted" data-testid="provider-discovered-models">
                目录已读取 · {discoveredModelIds.size} 个模型
              </span>
            )}
          </form>
        )}
        <div className="provider-binding-list">{currentBindings.map(renderModel)}</div>
        {historicalBindings.length > 0 && (
          <Disclosure
            title={copy.historical + " · " + historicalBindings.length}
            testId="provider-history-disclosure"
          >
            <div className="provider-binding-list">{historicalBindings.map(renderModel)}</div>
          </Disclosure>
        )}
        {bindings.isPending && connection && <p role="status">正在读取模型…</p>}
        {bindings.isError && (
          <p role="alert">
            模型绑定读取失败。
            <Button tone="ghost" onClick={() => void bindings.refetch()}>
              重新读取模型绑定
            </Button>
          </p>
        )}
        {bindings.isSuccess && !allBindings.length && <p className="muted">{copy.emptyModels}</p>}
      </section>

      <Disclosure title={copy.project} testId="provider-project-disclosure">
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
            {projectBindings.isPending && <p role="status">正在读取项目绑定…</p>}
            {projectBindings.isSuccess &&
              (projectBindings.data.length ? (
                <ul className="dense">
                  {projectBindings.data.map((row) => (
                    <li key={row.id}>
                      <span>
                        {row.purpose === "keyframe" ? "关键帧" : "视频"}：
                        {row.display_name ?? row.model_id ?? "未知模型"}
                        {row.provider_type ? "（" + row.provider_type + "）" : ""}
                      </span>
                      {row.model_binding_enabled === false && (
                        <small className="status-pending">绑定已停用</small>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">该项目尚未指定模型。</p>
              ))}
            {projectBindings.isError && (
              <p role="alert">
                当前绑定读取失败。
                <Button onClick={() => void projectBindings.refetch()}>重新读取项目绑定</Button>
              </p>
            )}
          </div>
        )}
      </Disclosure>

      <Disclosure title={copy.diagnostics} testId="provider-diagnostics-disclosure">
        <dl className="provider-model-metadata">
          <dt>协议</dt>
          <dd>
            <code>{selectedPlugin.protocol_profile}</code>
          </dd>
          <dt>凭证版本</dt>
          <dd>
            <code>{connection?.credential_key_version ?? "未配置"}</code>
          </dd>
          <dt>插件</dt>
          <dd>{selectedPlugin.implemented ? "已实现" : "仅目录"}</dd>
        </dl>
        {connection && (
          <>
            <form
              className="provider-probe-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!busy && !probeBlockedReason) probeMutation.mutate(false);
              }}
            >
              <Field>
                检查项目
                <Select
                  aria-label="探测能力"
                  value={capability}
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
                  模型
                  <Select
                    aria-label="探测模型绑定"
                    value={probeBindingId}
                    disabled={busy || !bindings.isSuccess}
                    onChange={(event) => setProbeBindingId(event.target.value)}
                  >
                    <option value="">选择模型配置</option>
                    {probeCandidates.map((binding) => (
                      <option key={binding.id} value={binding.id}>
                        {activeModelFor(binding)?.display_name ?? binding.model_id} ·{" "}
                        {binding.model_id}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {(capability === "image_i2i" || capability === "video_i2v") && (
                <Field>
                  参考产物 ID
                  <Input
                    value={referenceArtifactId}
                    onChange={(event) => setReferenceArtifactId(event.target.value)}
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
                      <option value="video_id">视频 ID</option>
                      <option value="task_id">任务 ID</option>
                    </Select>
                  </Field>
                </>
              )}
              {probeBlockedReason && <p role="status">{probeBlockedReason}</p>}
              <Button type="submit" disabled={busy || Boolean(probeBlockedReason)}>
                {probeMutation.isPending ? "检查中…" : paidProbe ? "付费探测暂不可用" : "运行探测"}
              </Button>
            </form>
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
                  <time dateTime={probe.tested_at}>{probe.tested_at}</time>
                  {probe.error_code && (
                    <span className="status-bad">错误代码：{probe.error_code}</span>
                  )}
                </li>
              ))}
              {probes.isPending && <li role="status">正在读取能力证据…</li>}
              {probes.isError && (
                <li role="alert">
                  能力证据读取失败。
                  <Button onClick={() => void probes.refetch()}>重新读取证据</Button>
                </li>
              )}
              {probes.isSuccess && !probes.data.length && <li className="muted">暂无能力证据。</li>}
            </ul>
          </>
        )}
      </Disclosure>

      {message && (connections.isError || bindings.isError || probes.isError) && (
        <p role="status">操作已保存，部分状态读取失败，请刷新核对。</p>
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
