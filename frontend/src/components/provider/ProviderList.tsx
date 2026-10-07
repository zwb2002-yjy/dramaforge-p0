import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, MessageSquareText, Plus, Search, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { listProviderConnections, listProviderPlugins } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Input } from "../ui";
import { AddProviderDialog } from "./AddProviderDialog";
import { ProviderDetails } from "./ProviderDetails";
import { connectionStatus, pluginFor } from "./providerSetup";
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
  const list = [...(connections.data ?? [])].sort((a, b) => Number(b.enabled) - Number(a.enabled));
  const selected = list.find((item) => item.id === selectedId) ?? list[0];
  useEffect(() => {
    if (connections.data && !connections.data.some((item) => item.id === selectedId)) {
      setSelectedId(
        connections.data.find((item) => item.enabled)?.id ?? connections.data[0]?.id ?? null,
      );
    }
  }, [selectedId, connections.data]);
  const filtered = list.filter((item) =>
    `${item.display_name} ${pluginFor(plugins.data, item)?.display_name ?? ""}`
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
          <p className="muted">选择一个连接，配置服务地址、密钥和可用模型。</p>
        </div>
        <Button
          tone="primary"
          disabled={!plugins.isSuccess}
          onClick={() => onAddingChange(true)}
          data-testid="add-provider"
        >
          <Plus size={16} aria-hidden="true" />
          添加供应商
        </Button>
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
      ) : list.length ? (
        <div className="df-provider-workspace" data-testid="provider-workspace">
          <nav className="df-provider-sidebar" aria-label="已连接的供应商">
            <header>
              <span>我的连接</span>
              <span className="muted df-num">{list.length}</span>
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
              {filtered.map((connection) => {
                const plugin = pluginFor(plugins.data, connection);
                const status = connectionStatus(connection);
                const Icon = plugin?.kind === "text" ? MessageSquareText : ImageIcon;
                return (
                  <Button
                    key={connection.id}
                    tone="ghost"
                    className="df-provider-option"
                    aria-label={`管理 ${connection.display_name}`}
                    aria-pressed={selected?.id === connection.id}
                    data-testid={`provider-connection-${connection.id}`}
                    onClick={() => setSelectedId(connection.id)}
                  >
                    <span className="df-provider-mark" aria-hidden="true">
                      <Icon size={18} />
                    </span>
                    <span className="df-provider-option-copy">
                      <strong>{connection.display_name}</strong>
                      <small>
                        {plugin?.kind === "text" ? "文本服务" : "图片与视频"} · {status.label}
                      </small>
                    </span>
                    <span className={`df-provider-status-dot ${status.tone}`} aria-hidden="true" />
                  </Button>
                );
              })}
              {!filtered.length && <p className="muted">没有匹配的供应商。</p>}
            </div>
            <p className="df-provider-sidebar-note">
              同一供应商可以添加多个连接，分别保存地址和密钥。
            </p>
          </nav>
          {selected && (
            <ProviderDetails
              key={selected.id}
              workspaceId={workspaceId}
              connection={selected}
              plugin={pluginFor(plugins.data, selected)}
            />
          )}
        </div>
      ) : (
        <div className="df-provider-empty">
          <Settings2 size={28} aria-hidden="true" />
          <h3>连接你的第一个供应商</h3>
          <p className="muted">添加文本、图片或视频服务，读取模型后即可设置默认模型。</p>
        </div>
      )}
      {adding && plugins.data && (
        <AddProviderDialog
          workspaceId={workspaceId}
          plugins={plugins.data}
          onClose={() => onAddingChange(false)}
        />
      )}
    </section>
  );
}
