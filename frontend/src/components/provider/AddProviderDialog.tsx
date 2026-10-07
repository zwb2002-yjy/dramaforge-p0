import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Image as ImageIcon, MessageSquareText } from "lucide-react";
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
import { catalogFailureText, pluginKey, probeErrorText, type ModelChoice } from "./providerSetup";

type Phase = "connect" | "models";

/**
 * Toonflow/ArcReel-style setup: pick a vendor, enter name / URL / Key, read
 * the account's model catalog (a free, read-only check), then tick the models
 * to use. Text gateways expose discovered models directly; media vendors bind
 * each ticked model to its catalog contract. Nothing generates media here.
 */
export function AddProviderDialog({
  workspaceId,
  plugins,
  onClose,
}: {
  workspaceId: string;
  plugins: ProviderPluginRead[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const ordered = useMemo(
    () =>
      [...plugins]
        .filter((plugin) => plugin.implemented)
        .sort((left, right) => (left.kind === right.kind ? 0 : left.kind === "media" ? -1 : 1)),
    [plugins],
  );
  const [selectedKey, setSelectedKey] = useState(() => (ordered[0] ? pluginKey(ordered[0]) : ""));
  const plugin = ordered.find((item) => pluginKey(item) === selectedKey) ?? null;
  const [name, setName] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [connection, setConnection] = useState<ProviderConnectionRead | null>(null);
  const [catalog, setCatalog] = useState<ProviderProbeRead | null>(null);
  const [phase, setPhase] = useState<Phase>("connect");
  const [choices, setChoices] = useState<Map<string, ModelChoice>>(new Map());
  const [error, setError] = useState<string | null>(null);

  const nameValue = name ?? connection?.display_name ?? plugin?.display_name ?? "";
  const urlValue = url ?? connection?.base_url ?? plugin?.default_base_url ?? "";

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
    onMutate: () => setError(null),
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
    onMutate: () => setError(null),
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
      onClose();
    },
    onError: (cause) => setError(cause instanceof Error ? cause.message : "添加失败"),
  });

  const busy = connect.isPending || addModels.isPending;
  const isText = plugin?.kind === "text";
  const discoveredIds = catalog?.discovered_model_ids ?? [];

  const actions =
    phase === "connect" ? (
      <>
        <Button tone="ghost" onClick={onClose}>
          取消
        </Button>
        <Button
          tone="primary"
          data-testid="add-provider-connect"
          disabled={busy || !plugin || !urlValue.trim() || (!connection && !apiKey.trim())}
          onClick={() => connect.mutate()}
        >
          {connect.isPending ? "正在连接…" : "连接并读取模型"}
        </Button>
      </>
    ) : isText ? (
      <Button tone="primary" onClick={onClose}>
        完成
      </Button>
    ) : (
      <>
        <Button tone="ghost" onClick={onClose} disabled={busy}>
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

  return (
    <Dialog
      title={phase === "connect" ? "添加供应商" : isText ? "已连接" : "选择要使用的模型"}
      kicker={phase === "models" ? (connection?.display_name ?? undefined) : undefined}
      onClose={onClose}
      size="wide"
      testId="add-provider-dialog"
      actions={actions}
    >
      {phase === "connect" ? (
        <div className="df-add-provider">
          <nav className="df-vendor-rail" aria-label="选择供应商">
            {ordered.map((item) => {
              const key = pluginKey(item);
              const Icon = item.kind === "text" ? MessageSquareText : ImageIcon;
              return (
                <Button
                  tone="ghost"
                  key={key}
                  className={key === selectedKey ? "df-vendor-option active" : "df-vendor-option"}
                  aria-pressed={key === selectedKey}
                  disabled={busy || Boolean(connection)}
                  onClick={() => {
                    setSelectedKey(key);
                    setName(null);
                    setUrl(null);
                    setError(null);
                  }}
                >
                  <Icon size={16} aria-hidden="true" />
                  <span>{item.display_name}</span>
                  <small>{item.kind === "text" ? "文本" : "图片 · 视频"}</small>
                </Button>
              );
            })}
          </nav>
          {plugin ? (
            <div
              className="df-add-provider-form"
              onKeyDown={(event) => {
                if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
                event.preventDefault();
                if (!busy && urlValue.trim() && (connection || apiKey.trim())) connect.mutate();
              }}
            >
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
                  placeholder="https://api.example.com"
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
              <p className="df-add-provider-hint">
                {isText
                  ? "支持 LiteLLM 或任意 OpenAI 兼容 Chat 接口。"
                  : "支持官方地址或局域网服务地址。"}
                只读取模型列表，不会产生生成费用。
              </p>
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
          <p className="muted">在「默认模型」中选择用于剧本与分镜的模型。</p>
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
    </Dialog>
  );
}
