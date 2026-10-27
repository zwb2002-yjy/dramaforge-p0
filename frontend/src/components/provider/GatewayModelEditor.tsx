import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getGatewayConfiguration,
  reconcileGatewayModel,
  rotateGatewayCredential,
  saveGatewayModel,
  updateProviderConnection,
  type ProviderConnectionRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Dialog, Field, Input } from "../ui";
import { probeErrorText } from "./providerSetup";
import { useModelActivation } from "./useModelActivation";

/** The same form creates and edits LLM references; upstream secrets never read back. */
export function GatewayModelEditor({
  workspaceId,
  connection,
  inline = false,
  onClose,
  onConnectionCreated,
  onBusyChange,
  defaultName = "文本服务",
}: {
  workspaceId: string;
  connection?: ProviderConnectionRead;
  inline?: boolean;
  onClose?: (connectionId?: string) => void;
  onConnectionCreated?: (connection: ProviderConnectionRead) => void;
  onBusyChange?: (busy: boolean) => void;
  defaultName?: string;
}) {
  const cache = useQueryClient();
  const usage = useModelActivation(workspaceId);
  const [row, setRow] = useState(connection);
  const [name, setName] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [modelId, setModelId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [requestId, setRequestId] = useState(() => globalThis.crypto.randomUUID());
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (connection) setRow(connection);
  }, [connection]);
  const config = useQuery({
    queryKey: queryKeys.provider.gateway(workspaceId, row?.id, row?.connection_revision_id),
    queryFn: () => getGatewayConfiguration(workspaceId, row!.id),
    enabled: Boolean(row?.gateway_ref?.state === "ready"),
    retry: false,
  });
  const nameValue = name ?? row?.display_name ?? defaultName;
  const urlValue = url ?? config.data?.base_url ?? "";
  const modelValue = modelId ?? row?.gateway_ref?.remote_model_id ?? "";
  const pending = row?.gateway_ref?.state !== "ready" && Boolean(row);
  const uncertain = pending && row?.gateway_ref?.state !== "reserved";
  const refresh = async () => {
    await Promise.all([
      cache.invalidateQueries({ queryKey: queryKeys.provider.connections(workspaceId) }),
      cache.invalidateQueries({ queryKey: ["provider-gateway", workspaceId] }),
      cache.invalidateQueries({ queryKey: queryKeys.model.catalog(workspaceId) }),
    ]);
  };
  const accept = async (saved: ProviderConnectionRead) => {
    setRow(saved);
    setApiKey("");
    setError(null);
    if (saved.gateway_ref?.state === "ready") {
      setName(null);
      setUrl(null);
      setModelId(null);
      setRequestId(globalThis.crypto.randomUUID());
      setMessage("配置已核验，上游生成尚未验证。");
      onConnectionCreated?.(saved);
    } else {
      setMessage("配置待核验，请先核验状态，不要重复添加。");
    }
    await refresh();
  };
  const save = useMutation({
    retry: false,
    mutationFn: async () => {
      if (!nameValue.trim()) throw new Error("请填写连接名称");
      const targetChanged =
        !row ||
        pending ||
        urlValue.trim() !== config.data?.base_url ||
        modelValue.trim() !== row.gateway_ref?.remote_model_id;
      if (targetChanged) {
        if (!urlValue.trim() || !modelValue.trim() || !apiKey.trim())
          throw new Error("请填写服务地址、真实模型 ID 和 Key；更换目标时需重新填写 Key。");
        return saveGatewayModel(
          workspaceId,
          {
            request_id: pending ? row!.gateway_ref!.request_id : requestId,
            display_name: nameValue.trim(),
            base_url: urlValue.trim(),
            model_id: modelValue.trim(),
            api_key: apiKey,
            contract_profile: "chat_text_v1",
          },
          row?.id,
        );
      }
      let saved = row!;
      if (apiKey.trim())
        saved = await rotateGatewayCredential(workspaceId, row!.id, requestId, apiKey);
      if (nameValue.trim() !== saved.display_name)
        saved = await updateProviderConnection(workspaceId, saved.id, {
          display_name: nameValue.trim(),
        });
      return saved;
    },
    onMutate: () => {
      setError(null);
      onBusyChange?.(true);
    },
    onSettled: () => onBusyChange?.(false),
    onSuccess: accept,
    onError: async (cause) => {
      setError(probeErrorText(cause));
      await refresh();
    },
  });
  const reconcile = useMutation({
    retry: false,
    mutationFn: () => reconcileGatewayModel(workspaceId, row!.id),
    onSuccess: accept,
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const toggle = useMutation({
    retry: false,
    mutationFn: () => updateProviderConnection(workspaceId, row!.id, { enabled: !row!.enabled }),
    onSuccess: async (saved) => {
      setRow(saved);
      await refresh();
    },
    onError: (cause) => setError(probeErrorText(cause)),
  });
  const busy =
    save.isPending || reconcile.isPending || toggle.isPending || usage.activate.isPending;
  const logicalModelId = row?.gateway_ref
    ? `litellm/${row.id}/${row.gateway_ref.remote_model_id}`
    : "";
  const active = usage.isActive("llm", logicalModelId);
  const actions = (
    <>
      {row && (
        <Button
          aria-label={`${active ? "已启用" : "启用"} ${row.gateway_ref?.remote_model_id ?? row.display_name}`}
          disabled={busy || active || !row.enabled || !usage.canActivate("llm", logicalModelId)}
          onClick={() => usage.activate.mutate({ role: "llm", modelId: logicalModelId })}
        >
          {active ? "已启用" : "启用"}
        </Button>
      )}
      {row && (
        <Button disabled={busy} onClick={() => reconcile.mutate()}>
          核验配置
        </Button>
      )}
      {row && (
        <Button disabled={busy} onClick={() => toggle.mutate()}>
          {row.enabled ? "停用连接" : "启用连接"}
        </Button>
      )}
      {onClose && (
        <Button tone="ghost" disabled={busy} onClick={() => onClose(row?.id)}>
          {pending ? "关闭" : row ? "完成" : "取消"}
        </Button>
      )}
      <Button
        tone="primary"
        data-testid="add-provider-connect"
        disabled={busy || Boolean(pending && row?.gateway_ref?.state !== "reserved")}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "正在保存…" : "保存 LLM 配置"}
      </Button>
    </>
  );
  const content = (
    <div className="df-add-provider-form">
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
          disabled={busy || uncertain}
          placeholder="兼容文本服务地址"
          onChange={(event) => setUrl(event.target.value)}
        />
      </Field>
      <Field>
        真实模型 ID
        <Input
          aria-label="真实模型 ID"
          value={modelValue}
          disabled={busy || uncertain}
          onChange={(event) => setModelId(event.target.value)}
        />
      </Field>
      <Field>
        API Key
        <Input
          aria-label="API Key"
          type="password"
          autoComplete="new-password"
          value={apiKey}
          disabled={busy || uncertain}
          placeholder={row ? "已保存，留空不更换" : "粘贴密钥"}
          onChange={(event) => setApiKey(event.target.value)}
        />
      </Field>
      <p className="muted">
        保存和核验配置不会生成内容。更换地址或模型会创建新版本，保留旧执行记录。
      </p>
      {row?.gateway_ref && <code>{row.gateway_ref.remote_model_id}</code>}
      {config.isError && <p role="alert">配置读取失败，请核验连接。</p>}
      {message && <p role="status">{message}</p>}
      {error && (
        <p role="alert" className="df-dialog-error">
          {error}
        </p>
      )}
    </div>
  );
  if (inline || connection)
    return (
      <section className="df-provider-detail" data-testid="provider-detail" aria-label="LLM 配置">
        <header className="df-provider-detail-heading">
          <h3>{row?.display_name ?? "LLM 配置"}</h3>
        </header>
        <span className="df-status warn">
          {row?.gateway_ref?.state === "ready" ? "配置已核验" : row ? "配置待核验" : "未配置"}
        </span>
        {content}
        <div className="df-manage-row-actions">{actions}</div>
      </section>
    );
  return (
    <Dialog
      open
      title="添加 LLM 配置"
      onClose={() => {
        if (!busy) onClose?.(row?.id);
      }}
      testId="add-provider-dialog"
      size="wide"
      actions={actions}
    >
      {content}
    </Dialog>
  );
}
