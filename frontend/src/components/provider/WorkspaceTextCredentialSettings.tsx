import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { getWorkspaceCredentialStatus, putWorkspaceCredential } from "../../lib/api";

type WorkspaceTextCredentialSettingsProps = {
  workspaceId: string | null;
};

export function WorkspaceTextCredentialSettings({
  workspaceId,
}: WorkspaceTextCredentialSettingsProps) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ["workspace-text-credential", workspaceId],
    queryFn: () => getWorkspaceCredentialStatus(workspaceId!, "text"),
    enabled: Boolean(workspaceId),
  });
  const save = useMutation({
    mutationFn: () => {
      if (!workspaceId || !apiKey.trim()) throw new Error("请输入文本模型 API Key");
      return putWorkspaceCredential(workspaceId, "text", apiKey.trim());
    },
    onSuccess: async () => {
      setApiKey("");
      setMessage("文本模型凭证已加密保存，本界面不会回读 Key。");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["workspace-text-credential", workspaceId] });
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!save.isPending) save.mutate();
  }

  return (
    <section className="df-settings-card" data-testid="workspace-text-credential-settings">
      <div className="panel-header">
        <div>
          <h2>文本模型凭证</h2>
          <p className="muted">用于文本导演与剧本生成；仅显示是否已配置，不显示密钥内容。</p>
        </div>
        <span className={status.data?.configured ? "status-ok" : "status-pending"}>
          {status.isLoading ? "读取中" : status.data?.configured ? "已配置" : "未配置"}
        </span>
      </div>
      {!workspaceId ? (
        <p className="muted">请先选择工作空间。</p>
      ) : (
        <form className="inline-form" onSubmit={submit}>
          <input
            aria-label="文本模型 API Key"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="输入新的文本模型 API Key"
          />
          <button type="submit" disabled={!apiKey.trim() || save.isPending}>
            保存凭证
          </button>
        </form>
      )}
      {message && <div className="status-ok">{message}</div>}
      {error && <div className="status-bad">{error}</div>}
    </section>
  );
}
