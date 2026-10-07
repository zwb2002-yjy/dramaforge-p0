import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image as ImageIcon, MessageSquareText, Plus, Power, RefreshCw, Video } from "lucide-react";
import { useState } from "react";

import {
  listProviderModelBindings,
  listProviderProbes,
  recordProviderQualityEvidence,
  runProviderProbe,
  updateProviderConnection,
  updateProviderConnectionCredential,
  type ProviderConnectionRead,
  type ProviderModelBindingRead,
  type ProviderPluginRead,
  type ProviderProbeRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Disclosure, Field, Input, Select } from "../ui";
import { ModelPicker } from "./ModelPicker";
import { bindingBatchMessage, createBindings } from "./providerBindings";
import {
  bindingChoiceKey,
  catalogFailureText,
  connectionStatus,
  latestCatalogRead,
  probeErrorText,
  type ModelChoice,
} from "./providerSetup";

function bindingStatus(
  binding: ProviderModelBindingRead,
  plugin: ProviderPluginRead | undefined,
): { tone: string; label: string } {
  if (!binding.enabled) return { tone: "", label: "已停用" };
  const contract = plugin?.models.find(
    (model) => model.catalog_entry_id === binding.catalog_entry_id,
  );
  if (!contract || contract.lifecycle !== "active")
    return { tone: "warn", label: "调用方式待更新" };
  if (!binding.account_verified) return { tone: "warn", label: "待验证" };
  return { tone: "ok", label: "可用" };
}

function contractName(plugin: ProviderPluginRead | undefined, binding: ProviderModelBindingRead) {
  return (
    plugin?.models.find((model) => model.catalog_entry_id === binding.catalog_entry_id)
      ?.display_name ?? binding.model_id
  );
}

/** Configure the selected connection inline; discovery remains explicit. */
export function ProviderDetails({
  workspaceId,
  connection,
  plugin,
}: {
  workspaceId: string;
  connection: ProviderConnectionRead;
  plugin: ProviderPluginRead | undefined;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [picking, setPicking] = useState(false);
  const [choices, setChoices] = useState<Map<string, ModelChoice>>(new Map());
  // The read just performed here is the freshest catalog, even before the
  // probe history query has refetched.
  const [lastRead, setLastRead] = useState<ProviderProbeRead | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isText = plugin?.kind === "text";

  const probes = useQuery({
    queryKey: queryKeys.provider.probes(workspaceId, connection.id),
    queryFn: () => listProviderProbes(workspaceId, connection.id),
    retry: false,
  });
  const bindings = useQuery({
    queryKey: queryKeys.provider.bindings(workspaceId, connection.id),
    queryFn: () => listProviderModelBindings(workspaceId, connection.id),
    enabled: !isText,
    retry: false,
  });
  const catalog = latestCatalogRead(probes.data);
  const status = connectionStatus(connection);
  const nameValue = name ?? connection.display_name;
  const urlValue = url ?? connection.base_url;
  const detailsDirty =
    (name !== null && name.trim() !== connection.display_name) ||
    (url !== null && url.trim() !== connection.base_url);

  const feedback = () => {
    setMessage(null);
    setError(null);
  };
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.connections(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.probesRoot(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.bindingsRoot(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.model.catalog() }),
    ]);
  };

  const saveDetails = useMutation({
    retry: false,
    mutationFn: () =>
      updateProviderConnection(workspaceId, connection.id, {
        ...(name !== null && name.trim() ? { display_name: name.trim() } : {}),
        ...(url !== null && url.trim() ? { base_url: url.trim() } : {}),
      }),
    onMutate: feedback,
    onSuccess: async () => {
      setName(null);
      setUrl(null);
      setMessage("已保存。地址变化后请重新读取模型。");
      await refresh();
    },
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const rotateKey = useMutation({
    retry: false,
    mutationFn: () => updateProviderConnectionCredential(workspaceId, connection.id, apiKey),
    onMutate: feedback,
    onSuccess: async () => {
      setApiKey("");
      setMessage("Key 已更换，请重新读取模型以验证。");
      await refresh();
    },
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const toggle = useMutation({
    retry: false,
    mutationFn: () =>
      updateProviderConnection(workspaceId, connection.id, { enabled: !connection.enabled }),
    onMutate: feedback,
    onSuccess: refresh,
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const readCatalog = useMutation({
    retry: false,
    mutationFn: () => runProviderProbe(workspaceId, connection.id, { capability: "auth_models" }),
    onMutate: feedback,
    onSuccess: async (probe) => {
      await refresh();
      if (probe.status === "passed") {
        setLastRead(probe);
        if (!isText) setPicking(true);
        setMessage(`已读取 ${probe.discovered_model_ids.length} 个模型。`);
      } else {
        setError(catalogFailureText(probe));
      }
    },
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const addModels = useMutation({
    retry: false,
    mutationFn: () => createBindings(workspaceId, connection.id, [...choices.values()]),
    onMutate: feedback,
    onSuccess: async (result) => {
      await refresh();
      const failure = bindingBatchMessage(result);
      if (failure) {
        setError(failure);
        return;
      }
      setChoices(new Map());
      setPicking(false);
      setMessage(`已添加 ${result.created.length} 个模型。`);
    },
    onError: (cause) => setError(cause instanceof Error ? cause.message : "添加失败"),
  });

  const busy =
    saveDetails.isPending ||
    rotateKey.isPending ||
    toggle.isPending ||
    readCatalog.isPending ||
    addModels.isPending;
  const existingKeys = new Set((bindings.data ?? []).map(bindingChoiceKey));
  const discoveredIds = (lastRead ?? catalog)?.discovered_model_ids ?? [];

  return (
    <section
      className="df-provider-detail"
      aria-label={`配置 ${connection.display_name}`}
      data-testid="provider-detail"
    >
      <header className="df-provider-detail-heading">
        <div>
          <p className="kicker">{plugin?.display_name ?? connection.provider_type}</p>
          <h3>{connection.display_name}</h3>
        </div>
        <span className="df-provider-kind">{isText ? "文本服务" : "图片 / 视频服务"}</span>
      </header>
      <div className="df-manage-provider">
        <div className="df-manage-status">
          <span className={`df-status ${status.tone}`} data-testid="provider-connection-status">
            {status.label}
          </span>
          <Button
            tone="ghost"
            disabled={busy}
            data-testid="provider-connection-toggle"
            onClick={() => toggle.mutate()}
          >
            <Power size={16} aria-hidden="true" />
            {connection.enabled ? "停用" : "启用"}
          </Button>
        </div>

        {picking && plugin ? (
          <>
            <ModelPicker
              plugin={plugin}
              discoveredIds={discoveredIds}
              existingKeys={existingKeys}
              value={choices}
              onChange={setChoices}
              disabled={busy}
            />
            <div className="df-manage-row-actions">
              <Button tone="ghost" disabled={busy} onClick={() => setPicking(false)}>
                取消
              </Button>
              <Button
                tone="primary"
                disabled={busy || choices.size === 0}
                onClick={() => addModels.mutate()}
              >
                {addModels.isPending ? "正在添加…" : `添加 ${choices.size} 个模型`}
              </Button>
            </div>
          </>
        ) : (
          <>
            <section className="df-manage-section" aria-label="连接信息">
              <header>
                <h3>连接配置</h3>
                <span className="muted">密钥保存后不会回显</span>
              </header>
              <div className="df-manage-fields">
                <Field>
                  名称
                  <Input
                    aria-label="连接名称"
                    value={nameValue}
                    disabled={busy}
                    onChange={(event) => setName(event.target.value)}
                  />
                </Field>
                <Field>
                  服务地址
                  <Input
                    aria-label="服务地址"
                    value={urlValue}
                    disabled={busy}
                    onChange={(event) => setUrl(event.target.value)}
                  />
                </Field>
              </div>
              {detailsDirty && (
                <div className="df-manage-row-actions">
                  <Button
                    tone="ghost"
                    disabled={busy}
                    onClick={() => (setName(null), setUrl(null))}
                  >
                    放弃修改
                  </Button>
                  <Button disabled={busy || !urlValue.trim()} onClick={() => saveDetails.mutate()}>
                    保存
                  </Button>
                </div>
              )}
              <div className="df-manage-key">
                <Field>
                  API Key
                  <Input
                    aria-label="更换 API Key"
                    type="password"
                    autoComplete="new-password"
                    value={apiKey}
                    disabled={busy}
                    placeholder={
                      connection.credential_configured ? "已保存，输入新 Key 可更换" : "粘贴密钥"
                    }
                    onChange={(event) => setApiKey(event.target.value)}
                  />
                </Field>
                <Button disabled={busy || !apiKey.trim()} onClick={() => rotateKey.mutate()}>
                  更换 Key
                </Button>
              </div>
            </section>

            <section className="df-manage-section" aria-label="模型">
              <header>
                <h3>
                  模型{" "}
                  <span className="muted df-num">
                    {isText ? discoveredIds.length : (bindings.data?.length ?? 0)}
                  </span>
                </h3>
                <Button
                  tone={isText ? "ghost" : "default"}
                  disabled={busy || !connection.enabled}
                  data-testid="provider-read-models"
                  onClick={() => readCatalog.mutate()}
                >
                  {isText ? (
                    <RefreshCw size={16} aria-hidden="true" />
                  ) : (
                    <Plus size={16} aria-hidden="true" />
                  )}
                  {readCatalog.isPending ? "正在读取…" : isText ? "重新读取" : "添加模型"}
                </Button>
              </header>
              {isText ? (
                discoveredIds.length ? (
                  <ul className="df-model-list">
                    {discoveredIds.map((id) => (
                      <li key={id}>
                        <MessageSquareText size={16} aria-hidden="true" />
                        <span className="df-model-name">
                          <strong>{id}</strong>
                        </span>
                        <span className="df-status ok">可用</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">尚未读取到文本模型。</p>
                )
              ) : bindings.isError ? (
                <p role="alert">
                  模型读取失败。
                  <Button tone="ghost" onClick={() => void bindings.refetch()}>
                    重试
                  </Button>
                </p>
              ) : bindings.data?.length ? (
                <ul className="df-model-list">
                  {bindings.data.map((binding) => {
                    const state = bindingStatus(binding, plugin);
                    const Icon = binding.media_type === "image" ? ImageIcon : Video;
                    return (
                      <li key={binding.id} data-testid={`provider-model-${binding.id}`}>
                        <Icon size={16} aria-hidden="true" />
                        <span className="df-model-name">
                          <strong>{contractName(plugin, binding)}</strong>
                          <code>{binding.model_id}</code>
                        </span>
                        <span className={`df-status ${state.tone}`}>{state.label}</span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted">{bindings.isPending ? "正在读取…" : "还没有添加模型。"}</p>
              )}
            </section>

            <ProviderDiagnostics
              workspaceId={workspaceId}
              connection={connection}
              plugin={plugin}
              bindings={bindings.data ?? []}
              probes={probes.data ?? []}
              probesFailed={probes.isError}
              busy={busy}
              onDone={refresh}
            />
          </>
        )}
        {message && !error && (
          <p className="df-status ok" role="status">
            {message}
          </p>
        )}
        {error && (
          <p className="df-dialog-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}

const PROBE_LABEL: Record<string, string> = {
  auth_models: "读取模型",
  video_poll_download: "查询已有任务",
};

/** Technical facts and read-only checks; collapsed so setup never needs them. */
function ProviderDiagnostics({
  workspaceId,
  connection,
  plugin,
  bindings,
  probes,
  probesFailed,
  busy,
  onDone,
}: {
  workspaceId: string;
  connection: ProviderConnectionRead;
  plugin: ProviderPluginRead | undefined;
  bindings: ProviderModelBindingRead[];
  probes: Awaited<ReturnType<typeof listProviderProbes>>;
  probesFailed: boolean;
  busy: boolean;
  onDone: () => Promise<void>;
}) {
  const [bindingId, setBindingId] = useState("");
  const [remoteTaskId, setRemoteTaskId] = useState("");
  const [queryKind, setQueryKind] = useState("video_id");
  const [runId, setRunId] = useState("");
  const [artifactId, setArtifactId] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const videoBindings = bindings.filter((binding) => binding.media_type === "video");
  const poll = useMutation({
    retry: false,
    mutationFn: () =>
      runProviderProbe(workspaceId, connection.id, {
        capability: "video_poll_download",
        model_binding_id: bindingId,
        remote_task_id: remoteTaskId.trim(),
        remote_query_kind: queryKind,
      }),
    onSuccess: async (probe) => {
      setNote(probe.status === "passed" ? "任务查询成功。" : "任务查询失败。");
      await onDone();
    },
    onError: (cause) => setNote(probeErrorText(cause)),
  });
  const quality = useMutation({
    retry: false,
    mutationFn: () =>
      recordProviderQualityEvidence(workspaceId, connection.id, bindingId, {
        node_run_id: runId.trim(),
        artifact_id: artifactId.trim(),
      }),
    onSuccess: async () => {
      setNote("质量证据已记录。");
      setRunId("");
      setArtifactId("");
      await onDone();
    },
    onError: (cause) => setNote(probeErrorText(cause)),
  });
  const disabled = busy || poll.isPending || quality.isPending;

  return (
    <Disclosure title="诊断与验证" testId="provider-diagnostics-disclosure">
      <dl className="df-manage-facts">
        <dt>协议</dt>
        <dd>
          <code>{connection.protocol_profile}</code>
        </dd>
        <dt>凭证版本</dt>
        <dd>
          <code>{connection.credential_key_version ?? "未配置"}</code>
        </dd>
        <dt>插件</dt>
        <dd>{plugin?.implemented ? "已实现" : "仅目录"}</dd>
      </dl>
      <ul className="df-manage-probes" data-testid="provider-probes">
        {probes.slice(0, 6).map((probe) => (
          <li key={probe.probe_id}>
            <span>{PROBE_LABEL[probe.capability] ?? probe.capability}</span>
            <span className={`df-status ${probe.status === "passed" ? "ok" : "err"}`}>
              {probe.status === "passed" ? "通过" : "失败"}
            </span>
            <time dateTime={probe.tested_at}>{new Date(probe.tested_at).toLocaleString()}</time>
            {probe.error_code && <code>{probe.error_code}</code>}
          </li>
        ))}
        {probesFailed ? (
          <li role="alert">检查记录读取失败。</li>
        ) : (
          !probes.length && <li className="muted">暂无检查记录。</li>
        )}
      </ul>
      {bindings.length > 0 && (
        <div className="df-manage-diagnostic-forms">
          <Field>
            模型
            <Select
              aria-label="诊断模型"
              value={bindingId}
              disabled={disabled}
              onChange={(event) => setBindingId(event.target.value)}
            >
              <option value="">选择模型</option>
              {bindings.map((binding) => (
                <option key={binding.id} value={binding.id}>
                  {contractName(plugin, binding)} · {binding.model_id}
                </option>
              ))}
            </Select>
          </Field>
          {videoBindings.some((binding) => binding.id === bindingId) && (
            <div className="df-manage-fields">
              <Field>
                远端任务 ID
                <Input
                  value={remoteTaskId}
                  onChange={(event) => setRemoteTaskId(event.target.value)}
                />
              </Field>
              <Field>
                查询类型
                <Select value={queryKind} onChange={(event) => setQueryKind(event.target.value)}>
                  <option value="video_id">视频 ID</option>
                  <option value="task_id">任务 ID</option>
                </Select>
              </Field>
              <Button disabled={disabled || !remoteTaskId.trim()} onClick={() => poll.mutate()}>
                查询已有任务
              </Button>
            </div>
          )}
          {bindingId && (
            <div className="df-manage-fields">
              <Field>
                NodeRun ID
                <Input value={runId} onChange={(event) => setRunId(event.target.value)} />
              </Field>
              <Field>
                产物 ID
                <Input value={artifactId} onChange={(event) => setArtifactId(event.target.value)} />
              </Field>
              <Button
                disabled={disabled || !runId.trim() || !artifactId.trim()}
                onClick={() => quality.mutate()}
              >
                记录质量证据
              </Button>
            </div>
          )}
        </div>
      )}
      <p className="muted">生成类检查暂不提供：尚无独立的 Owner 付费探测授权合同。</p>
      {note && <p role="status">{note}</p>}
    </Disclosure>
  );
}
