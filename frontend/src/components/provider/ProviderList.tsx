import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Image as ImageIcon, MessageSquareText, Plus, Search, Settings2 } from "lucide-react";
import { useState } from "react";
import {
  listProviderConnections,
  listProviderPlugins,
  type ProviderConnectionRead,
  type ProviderPluginRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Input } from "../ui";
import { AddProviderDialog } from "./AddProviderDialog";
import { ProviderDetails } from "./ProviderDetails";
import { connectionStatus, pluginFor, pluginKey, providerLabel } from "./providerSetup";
import "./provider-settings.css";

export function ProviderList({
  workspaceId,
  adding,
  onAddingChange,
}: {
  workspaceId: string;
  adding: boolean;
  onAddingChange: (open: boolean) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showDisabled, setShowDisabled] = useState(false);
  const [setupConnectionId, setSetupConnectionId] = useState<string | null>(null);
  const [setupBusy, setSetupBusy] = useState(false);
  const [addingKind, setAddingKind] = useState<"text" | "media">("media");
  const queryClient = useQueryClient();
  const plugins = useQuery({
    queryKey: queryKeys.provider.plugins(),
    queryFn: listProviderPlugins,
    staleTime: 60_000,
    retry: false,
  });
  const connections = useQuery({
    queryKey: queryKeys.provider.connections(workspaceId),
    queryFn: () => listProviderConnections(workspaceId),
    retry: false,
  });
  const allConnections = connections.data ?? [];
  const inactiveCount = allConnections.filter((item) => !item.enabled).length;
  const hasActive = allConnections.some((item) => item.enabled);
  const list = allConnections
    .filter((item) => item.id !== setupConnectionId && (item.enabled || showDisabled || !hasActive))
    .sort((a, b) => Number(b.enabled) - Number(a.enabled));
  const primaryTypes = ["agnes", "minimax", "volcengine", "openai_compatible_media", "litellm"];
  const entries: {
    key: string;
    plugin?: ProviderPluginRead;
    connection?: ProviderConnectionRead;
  }[] = list.map((connection) => ({
    key: connection.id,
    connection,
    plugin: pluginFor(plugins.data, connection),
  }));
  for (const plugin of plugins.data ?? []) {
    if (
      !plugin.implemented ||
      !primaryTypes.includes(plugin.provider_type) ||
      plugin.provider_type === "openai_compatible_media"
    )
      continue;
    if (
      allConnections.some(
        (item) =>
          item.id !== setupConnectionId && item.enabled && pluginKey(item) === pluginKey(plugin),
      )
    )
      continue;
    entries.push({ key: pluginKey(plugin), plugin });
  }
  entries.sort((a, b) => {
    const rank = (entry: (typeof entries)[number]) => {
      const index = primaryTypes.indexOf(entry.plugin?.provider_type ?? "");
      return index < 0 ? primaryTypes.length : index;
    };
    return rank(a) - rank(b);
  });
  const selected = entries.find((item) => item.key === selectedId) ?? entries[0];
  const filtered = entries.filter((item) =>
    `${item.connection?.display_name ?? ""} ${item.plugin ? providerLabel(item.plugin) : ""}`
      .toLocaleLowerCase()
      .includes(search.trim().toLocaleLowerCase()),
  );
  return (
    <section
      className="df-settings-block"
      aria-labelledby="providers-title"
      data-testid="provider-config"
    >
      <header className="df-settings-block-header">
        <div>
          <h2 id="providers-title">供应商</h2>
        </div>
        <div className="df-manage-row-actions">
          <Button
            disabled={!plugins.isSuccess || setupBusy}
            onClick={() => {
              setAddingKind("text");
              onAddingChange(true);
            }}
          >
            添加 LLM 配置
          </Button>
          <Button
            tone="primary"
            disabled={!plugins.isSuccess || setupBusy}
            onClick={() => {
              setAddingKind("media");
              onAddingChange(true);
            }}
            data-testid="add-provider"
          >
            <Plus size={16} aria-hidden="true" />
            添加供应商
          </Button>
        </div>
      </header>
      {connections.isPending || plugins.isPending ? (
        <p role="status">正在读取供应商…</p>
      ) : connections.isError || plugins.isError ? (
        <p role="alert">
          无法读取供应商。
          <Button
            tone="ghost"
            onClick={() => {
              void connections.refetch();
              void plugins.refetch();
            }}
          >
            重试
          </Button>
        </p>
      ) : entries.length ? (
        <div className="df-provider-workspace" data-testid="provider-workspace">
          <nav className="df-provider-sidebar" aria-label="已连接的供应商">
            <header>
              <span>供应商</span>
              <span className="muted df-num">{entries.length}</span>
            </header>
            <span className="df-search-field">
              <Search size={16} aria-hidden="true" />
              <Input
                aria-label="搜索供应商"
                placeholder="搜索供应商"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </span>
            <div className="df-provider-options">
              {filtered.map((entry) => {
                const { connection, plugin } = entry;
                const label = connection?.display_name ?? (plugin ? providerLabel(plugin) : "");
                const status = connection
                  ? connectionStatus(connection)
                  : { tone: "idle", label: "未配置" };
                const Icon = plugin?.kind === "text" ? MessageSquareText : ImageIcon;
                return (
                  <Button
                    key={entry.key}
                    tone="ghost"
                    className="df-provider-option"
                    aria-label={`${connection ? "管理" : "选择"} ${label}`}
                    aria-pressed={selected?.key === entry.key}
                    data-testid={`provider-connection-${entry.key}`}
                    disabled={setupBusy}
                    onClick={() => {
                      if (entry.key !== selected?.key) setSetupConnectionId(null);
                      setSelectedId(entry.key);
                    }}
                  >
                    <span className="df-provider-mark" aria-hidden="true">
                      <Icon size={18} />
                    </span>
                    <span className="df-provider-option-copy">
                      <strong>{label}</strong>
                      <small>
                        {plugin?.kind === "text"
                          ? "LLM"
                          : plugin?.provider_type === "openai_compatible_media"
                            ? "自定义"
                            : "图片与视频"}{" "}
                        · {status.label}
                      </small>
                    </span>
                    <span className={`df-provider-status-dot ${status.tone}`} aria-hidden="true" />
                  </Button>
                );
              })}
              {!filtered.length && <p className="muted">没有匹配的供应商。</p>}
            </div>
            {inactiveCount > 0 && hasActive && (
              <Button tone="ghost" onClick={() => setShowDisabled((value) => !value)}>
                {showDisabled ? "收起停用连接" : `停用的连接 · ${inactiveCount}`}
              </Button>
            )}
          </nav>
          {selected?.connection ? (
            <ProviderDetails
              key={selected.key}
              workspaceId={workspaceId}
              connection={selected.connection}
              plugin={selected.plugin}
            />
          ) : (
            selected?.plugin && (
              <AddProviderDialog
                key={selected.key}
                inline
                workspaceId={workspaceId}
                plugins={[selected.plugin]}
                onBusyChange={setSetupBusy}
                onConnectionCreated={(connection) => {
                  setSetupConnectionId(connection.id);
                  queryClient.setQueryData<ProviderConnectionRead[]>(
                    queryKeys.provider.connections(workspaceId),
                    (rows) => [
                      ...(rows ?? []).filter((row) => row.id !== connection.id),
                      connection,
                    ],
                  );
                }}
                onClose={(connectionId) => {
                  setSetupConnectionId(null);
                  if (connectionId) setSelectedId(connectionId);
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.provider.connections(workspaceId),
                  });
                }}
              />
            )
          )}
        </div>
      ) : (
        <div className="df-provider-empty">
          <Settings2 size={28} aria-hidden="true" />
          <h3>连接你的第一个供应商</h3>
          <p className="muted">添加文本、图片或视频服务，读取模型后点击启用。</p>
        </div>
      )}
      {adding && plugins.data && (
        <AddProviderDialog
          workspaceId={workspaceId}
          custom
          plugins={plugins.data.filter((plugin) =>
            addingKind === "text"
              ? plugin.kind === "text"
              : plugin.provider_type === "openai_compatible_media",
          )}
          onClose={(connectionId) => {
            if (connectionId) setSelectedId(connectionId);
            onAddingChange(false);
          }}
        />
      )}
    </section>
  );
}
