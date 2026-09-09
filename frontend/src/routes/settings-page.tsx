import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import { ProviderConnectionPanel } from "../components/provider/ProviderConnectionPanel";
import { CreativeAutonomySwitcher } from "../features/project/CreativeAutonomySwitcher";
import {
  createWorkspace,
  deleteWorkspace,
  fetchCurrentUser,
  fetchHealth,
  fetchProject,
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  renameWorkspace,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
  type WorkspaceRead,
} from "../lib/api";
import { queryKeys } from "../lib/queryKeys";

function SettingsHeader({ title, description }: { title: string; description: string }) {
  return (
    <header className="df-page-header">
      <div>
        <p className="df-page-eyebrow">Settings</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </header>
  );
}

function useSettingsWorkspace() {
  const workspaces = useQuery({
    queryKey: queryKeys.workspace.list(),
    queryFn: listWorkspaces,
  });
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const selectWorkspace = useCallback((workspaceId: string | null) => {
    persistSelectedWorkspaceId(workspaceId);
    setSelectedWorkspaceId(workspaceId);
  }, []);

  useEffect(() => {
    if (!selectedWorkspaceId && workspaces.data?.[0]) selectWorkspace(workspaces.data[0].id);
    if (
      selectedWorkspaceId &&
      workspaces.data &&
      !workspaces.data.some((workspace) => workspace.id === selectedWorkspaceId)
    ) {
      selectWorkspace(workspaces.data[0]?.id ?? null);
    }
  }, [selectWorkspace, selectedWorkspaceId, workspaces.data]);

  const projects = useQuery({
    queryKey: queryKeys.workspace.projects(selectedWorkspaceId),
    queryFn: () => listWorkspaceProjects(selectedWorkspaceId!),
    enabled: Boolean(selectedWorkspaceId),
  });

  return { workspaces, projects, selectedWorkspaceId, selectWorkspace };
}

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
    <label>
      工作空间
      <select
        aria-label="设置工作空间"
        value={selectedWorkspaceId ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AccountSettingsPage() {
  const currentUser = useQuery({
    queryKey: queryKeys.auth.currentUser(),
    queryFn: fetchCurrentUser,
    retry: false,
  });
  const health = useQuery({ queryKey: queryKeys.health(), queryFn: fetchHealth, retry: 1 });
  const serviceReady = health.data?.status === "ok" && (!health.data.db || health.data.db === "up");

  return (
    <main className="df-page df-settings-page" data-testid="account-settings-page">
      <SettingsHeader
        title="账号与实例"
        description="查看当前 Owner 和实例状态。项目与模型管理分别位于各自设置页面。"
      />
      <div className="df-settings-grid">
        <section className="df-settings-card">
          <h2>Owner</h2>
          {currentUser.isLoading ? (
            <p className="muted">正在读取账号…</p>
          ) : currentUser.data ? (
            <dl>
              <dt>显示名</dt>
              <dd>{currentUser.data.display_name}</dd>
              <dt>邮箱</dt>
              <dd>{currentUser.data.email}</dd>
            </dl>
          ) : (
            <p className="muted">请先在项目大厅登录 Owner 账号。</p>
          )}
        </section>
        <section className="df-settings-card">
          <h2>实例状态</h2>
          <p className={serviceReady ? "status-ok" : "status-bad"}>
            {serviceReady ? "服务就绪" : "服务未就绪"}
          </p>
          {health.data && (
            <dl>
              <dt>环境</dt>
              <dd>{health.data.env}</dd>
              <dt>版本</dt>
              <dd>{health.data.version}</dd>
            </dl>
          )}
        </section>
      </div>
    </main>
  );
}

export function WorkspaceSettingsPage() {
  const queryClient = useQueryClient();
  const { workspaces, projects, selectedWorkspaceId, selectWorkspace } = useSettingsWorkspace();
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.list() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.projectsRoot() });
  };

  const createMutation = useMutation({
    mutationFn: () => createWorkspace(workspaceName.trim()),
    onSuccess: async (workspace) => {
      setWorkspaceName("");
      selectWorkspace(workspace.id);
      await invalidate();
    },
    onError: (cause: Error) => setError(cause.message),
  });
  const renameMutation = useMutation({
    mutationFn: async (workspace: WorkspaceRead) => {
      const name = window.prompt("空间名", workspace.name)?.trim();
      if (!name || name === workspace.name) return;
      await renameWorkspace(workspace.id, name);
    },
    onSuccess: invalidate,
    onError: (cause: Error) => setError(cause.message),
  });
  const deleteMutation = useMutation({
    mutationFn: async (workspace: WorkspaceRead) => {
      if (!window.confirm(`删除空间「${workspace.name}」？`)) return;
      await deleteWorkspace(workspace.id);
    },
    onSuccess: invalidate,
    onError: (cause: Error) => setError(cause.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (workspaceName.trim()) createMutation.mutate();
  }

  return (
    <main className="df-page df-settings-page" data-testid="workspace-settings-page">
      <SettingsHeader
        title="工作空间管理"
        description="在这里管理项目容器；项目大厅只使用工作空间作为筛选条件。"
      />
      <section className="df-settings-card">
        <form className="inline-form" onSubmit={submit}>
          <input
            aria-label="新空间名"
            value={workspaceName}
            onChange={(event) => setWorkspaceName(event.target.value)}
            placeholder="新空间名"
          />
          <button type="submit" disabled={!workspaceName.trim() || createMutation.isPending}>
            创建空间
          </button>
        </form>
        <div className="workspace-list" role="list" aria-label="我的空间">
          {(workspaces.data ?? []).map((workspace) => (
            <div
              className={
                workspace.id === selectedWorkspaceId ? "workspace-row selected" : "workspace-row"
              }
              key={workspace.id}
              role="listitem"
            >
              <button
                className="workspace-select"
                type="button"
                onClick={() => selectWorkspace(workspace.id)}
              >
                {workspace.name}
              </button>
              <div className="workspace-actions">
                <button
                  className="ghost"
                  type="button"
                  onClick={() => renameMutation.mutate(workspace)}
                >
                  重命名
                </button>
                <button
                  className="ghost danger"
                  type="button"
                  onClick={() => deleteMutation.mutate(workspace)}
                  disabled={
                    workspace.id !== selectedWorkspaceId ||
                    Boolean(projects.data?.some((project) => project.workspace_id === workspace.id))
                  }
                >
                  删除
                </button>
              </div>
            </div>
          ))}
          {!workspaces.isLoading && !workspaces.data?.length && (
            <p className="muted">还没有工作空间，请先创建一个。</p>
          )}
        </div>
      </section>
      {error && <p className="flash err">{error}</p>}
    </main>
  );
}

export function ModelConnectionSettingsPage() {
  const { workspaces, projects, selectedWorkspaceId, selectWorkspace } = useSettingsWorkspace();

  return (
    <main className="df-page df-settings-page" data-testid="model-settings-page">
      <SettingsHeader
        title="模型连接"
        description="管理当前工作空间的模型供应连接和能力验证，不占用项目大厅。"
      />
      <div className="df-settings-section">
        <WorkspaceSelector
          workspaces={workspaces.data ?? []}
          selectedWorkspaceId={selectedWorkspaceId}
          onChange={selectWorkspace}
        />
      </div>
      <div className="df-settings-section">
        <ProviderConnectionPanel
          key={selectedWorkspaceId ?? "no-workspace"}
          workspaceId={selectedWorkspaceId}
          projects={projects.data ?? []}
        />
      </div>
    </main>
  );
}

export function DefaultPreferencesSettingsPage() {
  return (
    <main className="df-page df-settings-page" data-testid="default-settings-page">
      <SettingsHeader
        title="默认创作偏好"
        description="这些是新建项目表单的初始选择，每个项目创建时都可以调整。"
      />
      <section className="df-settings-card">
        <dl>
          <dt>创作起点</dt>
          <dd>自由创建</dd>
          <dt>导演参与度</dt>
          <dd>导演辅助</dd>
          <dt>默认画幅</dt>
          <dd>9:16 竖屏</dd>
        </dl>
        <p className="muted">
          当前版本不持久化实例级默认值；创建起点和导演参与度不会生成不同工作台或运行路径。
        </p>
      </section>
    </main>
  );
}

export function ProjectSettingsPage() {
  const params = useParams({ strict: false }) as { projectId?: string };
  const projectId = params.projectId ?? "";
  const selectedWorkspaceId = getSelectedWorkspaceId();
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: () => fetchProject(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  return (
    <main className="df-page df-settings-page" data-testid="project-settings-page">
      <SettingsHeader
        title={project.data?.name ? `${project.data.name} · 项目设置` : "当前项目设置"}
        description="项目偏好只影响当前作品，不改变统一创作主链。"
      />
      {project.isLoading ? (
        <p className="muted" role="status">
          正在读取项目设置…
        </p>
      ) : project.isError || !project.data ? (
        <p className="flash err">无法读取当前项目，请返回项目大厅重新选择。</p>
      ) : (
        <>
          <CreativeAutonomySwitcher project={project.data} />
          <section className="df-settings-section">
            <ModelProfileSettings projectId={projectId} workspaceId={selectedWorkspaceId} />
          </section>
        </>
      )}
    </main>
  );
}
