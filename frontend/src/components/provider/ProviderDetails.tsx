import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image as ImageIcon, MessageSquareText, Plus, Power, RefreshCw, Video } from "lucide-react";
import { useState } from "react";

import {
  listProviderModelBindings,
  listProviderProbes,
  runProviderProbe,
  updateProviderConnection,
  updateProviderConnectionCredential,
  type ProviderConnectionRead,
  type ProviderModelBindingRead,
  type ProviderPluginRead,
  type ProviderProbeRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Disclosure, Field, Input } from "../ui";
import { ModelPicker } from "./ModelPicker";
import { useModelActivation } from "./useModelActivation";
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
  const usage = useModelActivation(workspaceId);

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
  const catalog = latestCatalogRead(
    [...(lastRead ? [lastRead] : []), ...(probes.data ?? [])],
    connection,
  );
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
    onSuccess: async (saved) => {
      if (saved.connection_revision_id !== connection.connection_revision_id) {
        setLastRead(null);
        setChoices(new Map());
        setPicking(false);
      }
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
      setLastRead(null);
      setChoices(new Map());
      setPicking(false);
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
        setChoices(new Map());
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
    addModels.isPending ||
    usage.activate.isPending;
  const enabledBindings = (bindings.data ?? []).filter((binding) => binding.enabled !== false);
  const existingKeys = new Set(enabledBindings.map(bindingChoiceKey));
  const discoveredIds = catalog?.discovered_model_ids ?? [];
  const activationButton = (role: "llm" | "image" | "video", modelId: string, label: string) => {
    const active = usage.isActive(role, modelId);
    return (
      <Button
        tone={active ? "ghost" : "default"}
        aria-label={`${active ? "已启用" : "启用"} ${label}`}
        disabled={busy || active || !connection.enabled || !usage.canActivate(role, modelId)}
        onClick={() => usage.activate.mutate({ role, modelId })}
      >
        {active ? "已启用" : "启用"}
      </Button>
    );
  };

  return (
    <section
      className="df-provider-detail"
      aria-label={`配置 ${connection.display_name}`}
      data-testid="provider-detail"
    >
      <header className="df-provider-detail-heading">
        <div>
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
            {connection.enabled ? "停用连接" : "恢复连接"}
          </Button>
        </div>

        {picking && plugin && catalog ? (
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
              {isText && <p className="muted">保留多个配置，点击模型旁的「启用」切换。</p>}
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
                    placeholder={connection.credential_configured ? "已保存" : "输入 API Key"}
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
                    {isText ? discoveredIds.length : enabledBindings.length}
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
                        {activationButton("llm", `litellm/${connection.id}/${id}`, id)}
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
              ) : enabledBindings.length ? (
                <ul className="df-model-list">
                  {enabledBindings.map((binding) => {
                    const state = bindingStatus(binding, plugin);
                    const Icon = binding.media_type === "image" ? ImageIcon : Video;
                    return (
                      <li key={binding.id} data-testid={`provider-model-${binding.id}`}>
                        <Icon size={16} aria-hidden="true" />
                        <span className="df-model-name">
                          <strong>{binding.model_id}</strong>
                        </span>
                        <span className={`df-status ${state.tone}`}>{state.label}</span>
                        {activationButton(
                          binding.media_type === "image" ? "image" : "video",
                          `binding:${binding.id}`,
                          binding.model_id,
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted">{bindings.isPending ? "正在读取…" : "还没有添加模型。"}</p>
              )}
            </section>

            <ProviderHistory probes={probes.data ?? []} probesFailed={probes.isError} />
          </>
        )}
        {message && !error && (
          <p className="df-status ok" role="status">
            {message}
          </p>
        )}
        {usage.activate.isSuccess && (
          <p className="df-status ok" role="status">
            已启用，后续任务使用这个模型。
          </p>
        )}
        {(usage.loadError || usage.activate.isError) && (
          <p role="alert">
            {usage.loadError
              ? "无法读取当前启用的模型。"
              : usage.activate.error instanceof Error
                ? usage.activate.error.message
                : "启用失败。"}
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

/** Saved connection checks are available without exposing runtime internals. */
function ProviderHistory({
  probes,
  probesFailed,
}: {
  probes: Awaited<ReturnType<typeof listProviderProbes>>;
  probesFailed: boolean;
}) {
  return (
    <Disclosure title="连接记录" testId="provider-diagnostics-disclosure">
      <ul className="df-manage-probes" data-testid="provider-probes">
        {probes.slice(0, 6).map((probe) => (
          <li key={probe.probe_id}>
            <span>{PROBE_LABEL[probe.capability] ?? "连接检查"}</span>
            <span className={`df-status ${probe.status === "passed" ? "ok" : "err"}`}>
              {probe.status === "passed" ? "通过" : "失败"}
            </span>
            <time dateTime={probe.tested_at}>{new Date(probe.tested_at).toLocaleString()}</time>
          </li>
        ))}
        {probesFailed ? (
          <li role="alert">检查记录读取失败。</li>
        ) : (
          !probes.length && <li className="muted">暂无检查记录。</li>
        )}
      </ul>
    </Disclosure>
  );
}
