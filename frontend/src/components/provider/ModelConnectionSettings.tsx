import { useState } from "react";
import { Button, Field, Select } from "../ui";
import { useSettingsWorkspace } from "../../hooks/useSettingsWorkspace";
import type { WorkspaceRead } from "../../lib/api";
import { ProviderList } from "./ProviderList";

function WorkspaceSelector({
  workspaces,
  selectedWorkspaceId,
  onChange,
}: {
  workspaces: WorkspaceRead[];
  selectedWorkspaceId: string | null;
  onChange: (workspaceId: string | null) => void;
}) {
  return (
    <Field>
      工作空间
      <Select
        aria-label="设置工作空间"
        value={selectedWorkspaceId ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function ModelConnectionSettings() {
  const { workspaces, selectedWorkspaceId, selectWorkspace } = useSettingsWorkspace();
  const [adding, setAdding] = useState(false);

  return (
    <section className="df-model-settings" data-testid="model-settings-panel">
      {workspaces.isError ? (
        <p className="flash err" role="alert">
          无法读取工作空间。<Button onClick={() => void workspaces.refetch()}>重试</Button>
        </p>
      ) : workspaces.isPending ? (
        !selectedWorkspaceId && <p role="status">正在读取工作空间…</p>
      ) : (workspaces.data ?? []).length > 1 ? (
        <div className="df-settings-section">
          <WorkspaceSelector
            workspaces={workspaces.data ?? []}
            selectedWorkspaceId={selectedWorkspaceId}
            onChange={selectWorkspace}
          />
        </div>
      ) : null}
      {selectedWorkspaceId ? (
        <>
          <ProviderList
            key={`providers-${selectedWorkspaceId}`}
            workspaceId={selectedWorkspaceId}
            adding={adding}
            onAddingChange={setAdding}
          />
        </>
      ) : (
        !workspaces.isPending && <p className="muted">请先创建工作空间。</p>
      )}
    </section>
  );
}
