import { useState } from "react";
import { Button, Field, Select, Alert } from "../ui";
import { useSettingsWorkspace } from "../../hooks/useSettingsWorkspace";
import type { WorkspaceRead } from "../../features/access/api";
import { ProviderList } from "./ProviderList";
import { ProjectModelInheritance } from "./ProjectModelInheritance";

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
        onChange={(event) => onChange(event || null)}
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

export function ModelConnectionSettings({ projectId }: { projectId?: string } = {}) {
  const { workspaces, selectedWorkspaceId, selectWorkspace } = useSettingsWorkspace();
  const [adding, setAdding] = useState(false);

  return (
    <section className="df-model-settings" data-testid="model-settings-panel">
      {workspaces.isError ? (
        <Alert
          role="alert"
          type="error"
          showIcon
          description={
            <>
              无法读取工作空间。<Button onClick={() => void workspaces.refetch()}>重试</Button>
            </>
          }
        />
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
          {projectId && (
            <ProjectModelInheritance projectId={projectId} workspaceId={selectedWorkspaceId} />
          )}
          <p className="muted">
            在下方连接中选择模型，点击「用于生图」或「用于视频」。选择会保存为当前工作空间的默认模型；已有项目覆盖以生成预检为准。
          </p>
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
