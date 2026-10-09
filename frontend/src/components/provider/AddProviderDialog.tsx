import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useMemo, useState } from "react";

import {
  createProviderConnection,
  runProviderProbe,
  updateProviderConnection,
  updateProviderConnectionCredential,
  type ProviderConnectionRead,
  type ProviderPluginRead,
  type ProviderProbeRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Dialog, Field, Input } from "../ui";
import { ModelPicker } from "./ModelPicker";
import { bindingBatchMessage, createBindings } from "./providerBindings";
import {
  catalogFailureText,
  probeErrorText,
  providerLabel,
  isLocalServiceUrl,
  type ModelChoice,
} from "./providerSetup";

type Phase = "connect" | "models";

/**
 * Enter name / URL / Key for the selected connection, read
 * the account's model catalog (a free, read-only check), then tick the models
 * to use. Text gateways expose discovered models directly; media vendors bind
 * each ticked model to its catalog contract. Nothing generates media here.
 */
export function AddProviderDialog({
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
  const queryClient = useQueryClient();
  const ordered = useMemo(
    () =>
      [...plugins]
        .filter((plugin) => plugin.implemented)
        .sort((left, right) => (left.kind === right.kind ? 0 : left.kind === "media" ? -1 : 1)),
    [plugins],
  );
  const plugin = ordered[0] ?? null;
  const [name, setName] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
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
  const localMiniMax = plugin?.provider_type === "minimax" && isLocalServiceUrl(urlValue);
  const finish = () => onClose(connection?.id);

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
    mutationFn: async () => {
      if (!plugin) throw new Error("请选择供应商");
      if (localMiniMax) throw new Error("本地 MiniMax 请使用 OpenAI 兼容服务。");
      if (!urlValue.trim()) throw new Error("请填写服务地址");
      let saved = connection;
      if (!saved) {
        if (!apiKey.trim()) throw new Error("请填写 API Key");
        saved = await createProviderConnection(workspaceId, apiKey, {
          provider_type: plugin.provider_type,
          protocol_profile: plugin.protocol_profile,
          display_name: nameValue.trim() || plugin.display_name,
          base_url: urlValue.trim(),
        });
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
      return runProviderProbe(workspaceId, saved.id, { capability: "auth_models" });
    },
    onMutate: () => {
      setError(null);
      onBusyChange?.(true);
    },
    onSettled: () => onBusyChange?.(false),
    onSuccess: async (probe) => {
      await refresh();
      if (probe.status === "passed") {
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
          disabled={
            busy || !plugin || localMiniMax || !urlValue.trim() || (!connection && !apiKey.trim())
          }
          onClick={() => connect.mutate()}
        >
          {connect.isPending ? "正在连接…" : "连接并读取模型"}
        </Button>
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
                if (!busy && !localMiniMax && urlValue.trim() && (connection || apiKey.trim()))
                  connect.mutate();
              }}
            >
              {inline && (
                <header>
                  <h3>连接配置</h3>
                </header>
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
              {localMiniMax && <p role="alert">本地 MiniMax 请使用 OpenAI 兼容服务。</p>}
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
