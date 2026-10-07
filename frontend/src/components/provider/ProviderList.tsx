import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, MessageSquareText, Plus } from "lucide-react";
import { useState } from "react";

import {
  listProviderConnections,
  listProviderModelBindings,
  listProviderPlugins,
  listProviderProbes,
  type ProviderConnectionRead,
  type ProviderPluginRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button } from "../ui";
import { AddProviderDialog } from "./AddProviderDialog";
import { ProviderManageDialog } from "./ProviderManageDialog";
import { connectionStatus, latestCatalogRead, pluginFor } from "./providerSetup";
import "./provider-settings.css";

function ProviderCard({
  workspaceId,
  connection,
  plugin,
  onManage,
}: {
  workspaceId: string;
  connection: ProviderConnectionRead;
  plugin: ProviderPluginRead | undefined;
  onManage: () => void;
}) {
  const isText = plugin?.kind === "text";
  const bindings = useQuery({
    queryKey: queryKeys.provider.bindings(workspaceId, connection.id),
    queryFn: () => listProviderModelBindings(workspaceId, connection.id),
    enabled: !isText,
    retry: false,
  });
  const probes = useQuery({
    queryKey: queryKeys.provider.probes(workspaceId, connection.id),
    queryFn: () => listProviderProbes(workspaceId, connection.id),
    enabled: isText,
    retry: false,
  });
  const count = isText
    ? (latestCatalogRead(probes.data)?.discovered_model_ids.length ?? null)
    : (bindings.data?.length ?? null);
  const status = connectionStatus(connection);
  const Icon = isText ? MessageSquareText : ImageIcon;
  return (
    <li className="df-provider-card" data-testid={`provider-card-${connection.id}`}>
      <span className="df-provider-card-icon" aria-hidden="true">
        <Icon size={18} />
      </span>
      <div className="df-provider-card-body">
        <strong>{connection.display_name}</strong>
        <code title={connection.base_url}>{connection.base_url}</code>
      </div>
      <div className="df-provider-card-meta">
        <span className={`df-status ${status.tone}`}>{status.label}</span>
        <span className="muted df-num">
          {count === null ? "—" : `${count} 个${isText ? "文本" : ""}模型`}
        </span>
      </div>
      <Button tone="ghost" onClick={onManage} aria-label={`管理 ${connection.display_name}`}>
        管理
      </Button>
    </li>
  );
}

/** Workspace connections as quiet cards, plus the single "添加供应商" entry. */
export function ProviderList({
  workspaceId,
  adding,
  onAddingChange,
}: {
  workspaceId: string;
  adding: boolean;
  onAddingChange: (open: boolean) => void;
}) {
  const [managingId, setManagingId] = useState<string | null>(null);
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
  const managing = connections.data?.find((item) => item.id === managingId) ?? null;
  const list = [...(connections.data ?? [])].sort((left, right) =>
    left.enabled === right.enabled ? 0 : left.enabled ? -1 : 1,
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
          <p className="muted">填 Key 后自动读取账号可用的模型。</p>
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
      {connections.isPending ? (
        <ul className="df-provider-list" aria-busy="true">
          <li className="df-provider-card skeleton" />
          <li className="df-provider-card skeleton" />
        </ul>
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
        <ul className="df-provider-list" aria-label="已连接的供应商">
          {list.map((connection) => (
            <ProviderCard
              key={connection.id}
              workspaceId={workspaceId}
              connection={connection}
              plugin={pluginFor(plugins.data, connection)}
              onManage={() => setManagingId(connection.id)}
            />
          ))}
        </ul>
      ) : (
        <div className="df-provider-empty">
          <p>还没有连接供应商。</p>
          <p className="muted">添加一个图片 / 视频供应商和一个文本服务，就可以开始生成。</p>
        </div>
      )}
      {adding && plugins.data && (
        <AddProviderDialog
          workspaceId={workspaceId}
          plugins={plugins.data}
          onClose={() => onAddingChange(false)}
        />
      )}
      {managing && (
        <ProviderManageDialog
          key={managing.id}
          workspaceId={workspaceId}
          connection={managing}
          plugin={pluginFor(plugins.data, managing)}
          onClose={() => setManagingId(null)}
        />
      )}
    </section>
  );
}
