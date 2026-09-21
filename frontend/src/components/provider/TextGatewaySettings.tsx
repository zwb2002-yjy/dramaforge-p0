import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import {
  createProviderConnection,
  listProviderConnections,
  listProviderProbes,
  runProviderProbe,
  updateProviderConnection,
  updateProviderConnectionCredential,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Field, Input } from "../ui";

const PROVIDER_TYPE = "litellm";
const PROTOCOL_PROFILE = "openai_chat_v1";
const DEFAULT_URL = "http://litellm:4000";

export function TextGatewaySettings({ workspaceId }: { workspaceId: string | null }) {
  const queryClient = useQueryClient();
  const [urlDraft, setUrlDraft] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
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
        item.provider_type === PROVIDER_TYPE && item.protocol_profile === PROTOCOL_PROFILE,
    ) ?? null;
  const probes = useQuery({
    queryKey: queryKeys.provider.probes(workspaceId, connection?.id),
    queryFn: () => listProviderProbes(workspaceId!, connection!.id),
    enabled: Boolean(workspaceId && connection),
    retry: false,
  });
  const savedUrl = connection?.base_url ?? DEFAULT_URL;
  const url = urlDraft ?? savedUrl;
  const resetFeedback = () => {
    setMessage(null);
    setError(null);
  };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.provider.connections(workspaceId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.provider.probesRoot(workspaceId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.model.catalog() });
  };
  const save = useMutation({
    retry: false,
    mutationFn: async () => {
      if (!workspaceId || !url.trim()) throw new Error("请填写文本服务 URL");
      if (!connection) {
        if (!keyDraft.trim()) throw new Error("首次保存需要 API Key");
        return createProviderConnection(workspaceId, keyDraft, {
          provider_type: PROVIDER_TYPE,
          protocol_profile: PROTOCOL_PROFILE,
          display_name: "LiteLLM / OpenAI 兼容文本服务",
          base_url: url.trim(),
        });
      }
      let saved = connection;
      if (url.trim() !== savedUrl) {
        saved = await updateProviderConnection(workspaceId, connection.id, {
          base_url: url.trim(),
        });
      }
      if (keyDraft.trim()) {
        saved = await updateProviderConnectionCredential(workspaceId, connection.id, keyDraft);
      }
      return saved;
    },
    onMutate: resetFeedback,
    onSuccess: async () => {
      setUrlDraft(null);
      setKeyDraft("");
      setMessage("文本连接已保存。请显式探测模型后再到默认模型中选择。");
      await refresh();
    },
    onError: (cause: Error) => setError(cause.message),
  });
  const discover = useMutation({
    retry: false,
    mutationFn: () => {
      if (!workspaceId || !connection) throw new Error("请先保存文本连接");
      if (urlDraft !== null || keyDraft) throw new Error("请先保存或放弃连接草稿");
      return runProviderProbe(workspaceId, connection.id, {
        capability: "auth_models",
        paid_request_confirmed: false,
      });
    },
    onMutate: resetFeedback,
    onSuccess: async (result) => {
      if (result.status === "passed") {
        setMessage(`已发现 ${result.discovered_model_ids.length} 个文本模型。`);
      } else {
        setError("文本模型探测失败，请核对 URL、Key 和模型目录接口。");
      }
      await refresh();
    },
    onError: (cause: Error) => setError(cause.message),
  });
  const latestModels =
    probes.data?.find((item) => item.capability === "auth_models" && item.status === "passed")
      ?.discovered_model_ids ?? [];
  const busy = save.isPending || discover.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="df-settings-card" data-testid="text-gateway-settings">
      <h2>文本服务</h2>
      <p className="muted">
        支持 LiteLLM 或 OpenAI 兼容 Chat 接口。URL 与 Key 按工作空间加密保存；密钥不回显。
      </p>
      {!workspaceId ? (
        <p>请先选择工作空间。</p>
      ) : connections.isError ? (
        <p role="alert">文本连接读取失败，当前状态未知。</p>
      ) : (
        <form onSubmit={submit}>
          <Field>
            文本服务 URL
            <Input
              aria-label="文本服务 URL"
              value={url}
              disabled={busy || !connections.isSuccess}
              onChange={(event) => {
                setUrlDraft(event.target.value);
                resetFeedback();
              }}
            />
          </Field>
          <Field>
            API Key
            <Input
              aria-label="文本服务 API Key"
              type="password"
              autoComplete="new-password"
              value={keyDraft}
              disabled={busy || !connections.isSuccess}
              placeholder={connection?.credential_configured ? "已保存；输入新 Key 可轮换" : "输入 Key"}
              onChange={(event) => {
                setKeyDraft(event.target.value);
                resetFeedback();
              }}
            />
          </Field>
          <div className="toolbar">
            <Button
              type="submit"
              disabled={
                busy ||
                !connections.isSuccess ||
                !url.trim() ||
                (!connection && !keyDraft.trim()) ||
                (Boolean(connection) && url.trim() === savedUrl && !keyDraft.trim())
              }
            >
              {save.isPending ? "保存中…" : "保存文本连接"}
            </Button>
            <Button
              type="button"
              disabled={busy || !connection || urlDraft !== null || Boolean(keyDraft)}
              onClick={() => discover.mutate()}
            >
              {discover.isPending ? "探测中…" : "探测文本模型"}
            </Button>
          </div>
        </form>
      )}
      {latestModels.length > 0 && <p>已发现：{latestModels.join("、")}</p>}
      {message && <p className="status-ok">{message}</p>}
      {error && (
        <p className="status-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
