import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useMemo, useState } from "react";

import {
  ApiError,
  createProviderConnection,
  runProviderProbe,
  updateProviderConnection,
  updateProviderConnectionCredential,
  type ProviderConnectionRead,
  type ProviderPluginRead,
  type ProviderProbeRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Dialog, Field, Input, Select } from "../ui";
import { ModelPicker } from "./ModelPicker";
import { GatewayModelEditor } from "./GatewayModelEditor";
import { bindingBatchMessage, createBindings } from "./providerBindings";
import {
  catalogFailureText,
  probeErrorText,
  providerLabel,
  pluginKey,
  type ModelChoice,
} from "./providerSetup";

type Phase = "connect" | "models";

/**
 * Enter name / URL / Key for the selected connection, read
 * the account's model catalog (a free, read-only check), then tick the models
 * to use. Text gateways expose discovered models directly; media vendors bind
 * each ticked model to its catalog contract. Nothing generates media here.
 */
export function AddProviderDialog(props: Parameters<typeof MediaProviderDialog>[0]) {
  const installed = props.plugins.filter((plugin) => plugin.implemented);
  if (installed.length && installed.every((plugin) => plugin.kind === "text"))
    return (
      <GatewayModelEditor
        defaultName={props.custom ? "" : undefined}
        workspaceId={props.workspaceId}
        inline={props.inline}
        onClose={props.onClose}
        onConnectionCreated={props.onConnectionCreated}
        onBusyChange={props.onBusyChange}
      />
    );
  return (
    <MediaProviderDialog
      {...props}
      plugins={props.plugins.filter((plugin) => plugin.kind !== "text")}
    />
  );
}

function MediaProviderDialog({
  workspaceId,
  plugins,
  inline = false,
  custom = false,
  onConnectionCreated,
  onBusyChange,
  onClose,
}: {
  workspaceId: string;
  plugins: ProviderPluginRead[];
  inline?: boolean;
  custom?: boolean;
  onConnectionCreated?: (connection: ProviderConnectionRead) => void;
  onBusyChange?: (busy: boolean) => void;
  onClose: (connectionId?: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const queryClient = useQueryClient();
  const ordered = useMemo(
    () =>
      [...plugins]
        .filter((plugin) => plugin.implemented)
        .sort((left, right) => (left.kind === right.kind ? 0 : left.kind === "media" ? -1 : 1)),
    [plugins],
  );
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null);
  const plugin = ordered.find((item) => pluginKey(item) === selectedProfile) ?? ordered[0] ?? null;
  const [name, setName] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [requestedAuth, setRequestedAuth] = useState<"bearer" | "none">("bearer");
  const [unknownSave, setUnknownSave] = useState(false);
  const [connection, setConnection] = useState<ProviderConnectionRead | null>(null);
  const [catalog, setCatalog] = useState<ProviderProbeRead | null>(null);
  const [phase, setPhase] = useState<Phase>("connect");
  const [choices, setChoices] = useState<Map<string, ModelChoice>>(new Map());
  const [error, setError] = useState<string | null>(null);

  const nameValue =
    name ?? connection?.display_name ?? (custom ? "" : plugin ? providerLabel(plugin) : "");
  const urlValue =
    url ??
    connection?.base_url ??
    (custom || plugin?.kind === "text" ? "" : plugin?.default_base_url) ??
    "";
  const authMode = connection?.auth_mode ?? requestedAuth;
  const finish = () => (inline ? onClose(connection?.id) : setOpen(false));

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.connections(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.probesRoot(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.provider.bindingsRoot(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.model.catalog() }),
    ]);
  };

  const connect = useMutation({
    retry: false,
    mutationFn: async (manual: boolean) => {
      if (!plugin) throw new Error("请选择供应商");
      if (!urlValue.trim()) throw new Error("请填写服务地址");
      let saved = connection;
      if (!saved) {
        if (unknownSave) throw new Error("保存结果待核验，请关闭并刷新连接列表。");
        if (authMode === "bearer" && !apiKey.trim()) throw new Error("请填写 API Key");
        setUnknownSave(true);
        try {
          saved = await createProviderConnection(
            workspaceId,
            authMode === "none" ? undefined : apiKey,
            {
              provider_type: plugin.provider_type,
              protocol_profile: plugin.protocol_profile,
              display_name: nameValue.trim() || plugin.display_name,
              base_url: urlValue.trim(),
              auth_mode: authMode,
            },
          );
          setUnknownSave(false);
        } catch (cause) {
          if (
            cause instanceof ApiError &&
            cause.status >= 400 &&
            cause.status < 500 &&
            cause.status !== 408
          ) {
            setUnknownSave(false);
            throw cause;
          }
          throw new Error("连接保存结果未知，请关闭并刷新连接列表核对后再操作。");
        }
        onConnectionCreated?.(saved);
      } else {
        const patch: { display_name?: string; base_url?: string } = {};
        if (nameValue.trim() && nameValue.trim() !== saved.display_name) {
          patch.display_name = nameValue.trim();
        }
        if (urlValue.trim() !== saved.base_url) patch.base_url = urlValue.trim();
        if (Object.keys(patch).length) {
          saved = await updateProviderConnection(workspaceId, saved.id, patch);
        }
        if (apiKey.trim()) {
          saved = await updateProviderConnectionCredential(workspaceId, saved.id, apiKey);
        }
      }
      setConnection(saved);
      setApiKey("");
      setName(null);
      setUrl(null);
      return manual ? null : runProviderProbe(workspaceId, saved.id, { capability: "auth_models" });
    },
    onMutate: () => {
      setError(null);
      onBusyChange?.(true);
    },
    onSettled: () => onBusyChange?.(false),
    onSuccess: async (probe) => {
      await refresh();
      if (probe === null) {
        setCatalog(null);
        setPhase("models");
      } else if (probe.status === "passed") {
        setCatalog(probe);
        setPhase("models");
      } else {
        setError(catalogFailureText(probe));
      }
    },
    onError: async (cause) => {
      setError(probeErrorText(cause));
      await refresh();
    },
  });

  const addModels = useMutation({
    retry: false,
    mutationFn: () => createBindings(workspaceId, connection!.id, [...choices.values()]),
    onMutate: () => {
      setError(null);
      onBusyChange?.(true);
    },
    onSettled: () => onBusyChange?.(false),
    onSuccess: async (result) => {
      await refresh();
      const failure = bindingBatchMessage(result);
      if (failure) {
        setError(failure);
        setChoices(
          new Map(
            result.failed.map((item) => [
              `${item.choice.mediaType}:${item.choice.modelId}`,
              item.choice,
            ]),
          ),
        );
        return;
      }
      finish();
    },
    onError: (cause) => setError(cause instanceof Error ? cause.message : "添加失败"),
  });

  const busy = connect.isPending || addModels.isPending;
  const canConnect =
    !busy &&
    !unknownSave &&
    !!plugin &&
    !!urlValue.trim() &&
    (!!connection || authMode === "none" || !!apiKey.trim());
  const isText = plugin?.kind === "text";
  const discoveredIds = catalog?.discovered_model_ids ?? [];

  const actions =
    phase === "connect" ? (
      <>
        {!inline && (
          <Button tone="ghost" onClick={finish}>
            取消
          </Button>
        )}
        <Button
          tone="primary"
          data-testid="add-provider-connect"
          title="只读取模型列表，不产生生成费用"
          disabled={!canConnect}
          onClick={() => connect.mutate(false)}
        >
          {connect.isPending ? "正在连接…" : "连接并读取模型"}
        </Button>
        {plugin?.manual_model_ids && (
          <Button disabled={!canConnect} onClick={() => connect.mutate(true)}>
            保存并手填模型
          </Button>
        )}
      </>
    ) : isText ? (
      <Button tone="primary" onClick={finish}>
        完成
      </Button>
    ) : (
      <>
        <Button tone="ghost" onClick={finish} disabled={busy}>
          稍后再选
        </Button>
        <Button
          tone="primary"
          data-testid="add-provider-models"
          disabled={busy || choices.size === 0}
          onClick={() => addModels.mutate()}
        >
          {addModels.isPending ? "正在添加…" : `添加 ${choices.size} 个模型`}
        </Button>
      </>
    );

  const content = (
    <>
      {phase === "connect" ? (
        <div className={inline ? "df-manage-section" : "df-add-provider-form"}>
          {plugin ? (
            <div
              className="df-add-provider-form"
              onKeyDown={(event) => {
                if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
                event.preventDefault();
                if (canConnect) connect.mutate(false);
              }}
            >
              {inline && (
                <header>
                  <h3>连接配置</h3>
                </header>
              )}
              {ordered.length > 1 && (
                <Field>
                  调用协议
                  <Select
                    aria-label="调用协议"
                    value={pluginKey(plugin)}
                    disabled={busy || !!connection || unknownSave}
                    onChange={(value) => {
                      setSelectedProfile(value);
                      setRequestedAuth("bearer");
                      setApiKey("");
                      setUrl(null);
                      setChoices(new Map());
                    }}
                  >
                    {ordered.map((item) => (
                      <option key={pluginKey(item)} value={pluginKey(item)}>
                        {item.display_name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
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
                  placeholder={
                    isText ? "兼容文本服务或 LiteLLM 代理地址" : "https://api.example.com"
                  }
                  onChange={(event) => setUrl(event.target.value)}
                />
              </Field>
              {(plugin.auth_modes ?? ["bearer"]).includes("none") && (
                <Field>
                  认证方式
                  <Select
                    aria-label="认证方式"
                    value={authMode}
                    disabled={busy || !!connection || unknownSave}
                    onChange={(value) => {
                      setRequestedAuth(value as "bearer" | "none");
                      setApiKey("");
                    }}
                  >
                    {(plugin.auth_modes ?? ["bearer"]).map((mode) => (
                      <option key={mode} value={mode}>
                        {mode === "none" ? "无需 Key" : "Bearer Key"}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {authMode === "none" ? (
                <p className="muted">无需 Key。目录读取不证明生成能力。</p>
              ) : (
                <Field>
                  API Key
                  <Input
                    aria-label="API Key"
                    type="password"
                    autoComplete="new-password"
                    value={apiKey}
                    disabled={busy}
                    placeholder={connection ? "已保存，留空不更换" : "粘贴密钥"}
                    onChange={(event) => setApiKey(event.target.value)}
                  />
                </Field>
              )}
            </div>
          ) : (
            <p className="muted">当前没有可添加的供应商。</p>
          )}
        </div>
      ) : isText ? (
        <div className="df-text-models">
          <p className="df-status ok">已发现 {discoveredIds.length} 个文本模型</p>
          <ul>
            {discoveredIds.map((id) => (
              <li key={id}>
                <Check size={14} aria-hidden="true" />
                <code>{id}</code>
              </li>
            ))}
          </ul>
          <p className="muted">保存后，点击模型旁的「启用」切换。</p>
        </div>
      ) : plugin ? (
        <ModelPicker
          plugin={plugin}
          discoveredIds={discoveredIds}
          existingKeys={new Set()}
          value={choices}
          onChange={setChoices}
          disabled={busy}
        />
      ) : null}
      {error && (
        <p className="df-dialog-error" role="alert">
          {error}
        </p>
      )}
    </>
  );

  if (inline && plugin)
    return (
      <section
        className="df-provider-detail"
        aria-label={`配置 ${providerLabel(plugin)}`}
        data-testid="provider-detail"
      >
        <header className="df-provider-detail-heading">
          <h3>{providerLabel(plugin)}</h3>
          <span className="df-provider-kind">{isText ? "文本服务" : "图片 / 视频服务"}</span>
        </header>
        <span className={`df-status ${catalog?.status === "passed" ? "ok" : "idle"}`}>
          {catalog?.status === "passed" ? "已连接" : connection ? "待验证" : "未配置"}
        </span>
        {content}
        <div className="df-manage-row-actions">{actions}</div>
      </section>
    );
  return (
    <Dialog
      open={open}
      afterClose={() => onClose(connection?.id)}
      title={
        phase === "connect"
          ? custom && isText
            ? "添加 LLM 配置"
            : "添加供应商"
          : isText
            ? "已连接"
            : "选择要使用的模型"
      }
      kicker={phase === "models" ? (connection?.display_name ?? undefined) : undefined}
      onClose={finish}
      size="wide"
      testId="add-provider-dialog"
      actions={actions}
    >
      {content}
    </Dialog>
  );
}
