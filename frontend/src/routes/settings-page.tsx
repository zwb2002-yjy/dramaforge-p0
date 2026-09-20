import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useRouterState } from "@tanstack/react-router";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { Button, Disclosure, Field, Input, Select, PageHeader, Tabs, Tab } from "../components/ui";
import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import {
  ProjectModelSourceSummary,
  ProviderConfigurationBoundaries,
} from "../components/provider/ProjectModelSourceSummary";
import { ProviderConnectionPanel } from "../components/provider/ProviderConnectionPanel";
import { WorkspaceModelProfileSettings } from "../components/provider/WorkspaceModelProfileSettings";
import { TextGatewaySettings } from "../components/provider/TextGatewaySettings";
import { AdvancedRecoveryPanel } from "../features/maintenance/AdvancedRecoveryPanel";
import {
  ApiError,
  createWorkspace,
  deleteWorkspace,
  fetchCurrentUser,
  fetchHealth,
  fetchProject,
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  logoutUser,
  renameWorkspace,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
  type WorkspaceRead,
} from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { validateSettingsReturnTo } from "../lib/navigationPreferences";

function SettingsHeader({ title }: { title: string }) {
  return <PageHeader title={title} />;
}

const ENVIRONMENT_LABELS: Record<string, string> = {
  development: "开发环境",
  test: "测试环境",
  staging: "预发布环境",
  production: "生产环境",
};

function environmentLabel(env: string | undefined): string {
  if (!env) return "—";
  return ENVIRONMENT_LABELS[env] ?? env;
}

function useSettingsWorkspace(onSelect?: (workspaceId: string | null) => void) {
  const workspaces = useQuery({
    queryKey: queryKeys.workspace.list(),
    queryFn: listWorkspaces,
  });
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const selectWorkspace = useCallback(
    (workspaceId: string | null) => {
      persistSelectedWorkspaceId(workspaceId);
      setSelectedWorkspaceId(workspaceId);
      onSelect?.(workspaceId);
    },
    [onSelect],
  );

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

export function AccountSettingsPage() {
  const queryClient = useQueryClient();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const currentUser = useQuery({
    queryKey: queryKeys.auth.currentUser(),
    queryFn: fetchCurrentUser,
    retry: false,
  });
  const logout = useMutation({
    mutationFn: logoutUser,
    onSuccess: async () => {
      setLogoutError(null);
      queryClient.setQueryData(queryKeys.auth.currentUser(), null);
      // Drop every cached fact that was scoped to the previous session, then
      // let the routes re-read bootstrap/current-user from the server.
      persistSelectedWorkspaceId(null);
      queryClient.removeQueries({ queryKey: queryKeys.workspace.list() });
      queryClient.removeQueries({ queryKey: queryKeys.workspace.projectsRoot() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.bootstrap() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.currentUser() });
    },
    onError: (cause: Error) => setLogoutError(cause.message),
  });
  const health = useQuery({ queryKey: queryKeys.health(), queryFn: fetchHealth, retry: 1 });
  const serviceReady = health.data?.status === "ok" && (!health.data.db || health.data.db === "up");

  return (
    <main className="df-page df-settings-page" data-testid="account-settings-page">
      <SettingsHeader title="账号" />
      <div>
        <section className="df-settings-card">
          {currentUser.isLoading ? (
            <p className="muted">正在读取账号…</p>
          ) : currentUser.isError &&
            !(currentUser.error instanceof ApiError && currentUser.error.status === 401) ? (
            <div role="alert">
              <p>无法读取账号：{currentUser.error.message}</p>
              <Button
                type="button"
                onClick={() => void currentUser.refetch()}
                disabled={currentUser.isFetching}
              >
                重试
              </Button>
            </div>
          ) : !currentUser.isError && currentUser.data ? (
            <>
              <dl>
                <dt>显示名</dt>
                <dd>{currentUser.data.display_name}</dd>
                <dt>邮箱</dt>
                <dd>{currentUser.data.email}</dd>
              </dl>
              <div className="toolbar">
                <Button
                  type="button"
                  className="ghost danger"
                  data-testid="logout-button"
                  onClick={() => logout.mutate()}
                  disabled={logout.isPending}
                >
                  {logout.isPending ? "正在退出…" : "退出登录"}
                </Button>
              </div>
              {logoutError && (
                <p className="status-bad" role="alert">
                  退出失败：{logoutError}
                </p>
              )}
            </>
          ) : (
            <p>
              未登录。<a href="/">前往登录</a>
            </p>
          )}
        </section>
        <Disclosure title="实例与维护" testId="account-maintenance-disclosure">
          <section className="df-settings-card">
            <h2>实例状态</h2>
            {health.isLoading ? (
              <p className="muted" role="status">
                正在读取实例状态…
              </p>
            ) : (
              <>
                <p className={serviceReady ? "status-ok" : "status-bad"}>
                  {serviceReady ? "服务就绪" : "服务未就绪"}
                </p>
                {health.data && (
                  <dl>
                    <dt>环境</dt>
                    <dd>{environmentLabel(health.data.env)}</dd>
                    <dt>版本</dt>
                    <dd>{health.data.version}</dd>
                  </dl>
                )}
              </>
            )}
          </section>
          <AdvancedRecoveryPanel />
        </Disclosure>
      </div>
    </main>
  );
}

export function WorkspaceSettingsPage({
  onWorkspaceChange,
}: {
  onWorkspaceChange?: (workspaceId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const { workspaces, projects, selectedWorkspaceId, selectWorkspace } =
    useSettingsWorkspace(onWorkspaceChange);
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
    <section data-testid="workspace-settings-page" aria-label="工作空间管理">
      <section className="df-settings-card">
        <form className="inline-form" onSubmit={submit}>
          <Input
            aria-label="新空间名"
            autoFocus
            value={workspaceName}
            onChange={(event) => setWorkspaceName(event.target.value)}
            placeholder="新空间名"
          />
          <Button
            type="submit"
            disabled={!workspaceName.trim() || createMutation.isPending}
            title={workspaceName.trim() ? undefined : "请先填写新空间名"}
          >
            创建空间
          </Button>
        </form>
        <div className="workspace-list" role="list" aria-label="我的空间">
          {(workspaces.data ?? []).map((workspace) => {
            const hasProjects = Boolean(
              projects.data?.some((project) => project.workspace_id === workspace.id),
            );
            const isSelected = workspace.id === selectedWorkspaceId;
            // Only the active, empty workspace can be deleted; the disabled
            // action states the reason instead of failing silently.
            const deleteDisabledReason =
              projects.isPending || projects.isError
                ? "请先读取该空间的项目。"
                : hasProjects
                  ? "该空间仍有项目，请先移动或删除其中的项目。"
                  : isSelected
                    ? ""
                    : "请先切换到该空间，再删除它。";
            return (
              <div
                className={isSelected ? "workspace-row selected" : "workspace-row"}
                key={workspace.id}
                role="listitem"
              >
                <Button
                  className="workspace-select"
                  type="button"
                  onClick={() => selectWorkspace(workspace.id)}
                >
                  {workspace.name}
                </Button>
                <div className="workspace-actions">
                  <Button
                    tone="ghost"
                    type="button"
                    onClick={() => renameMutation.mutate(workspace)}
                  >
                    重命名
                  </Button>
                  <Button
                    className="ghost danger"
                    type="button"
                    onClick={() => deleteMutation.mutate(workspace)}
                    disabled={Boolean(deleteDisabledReason)}
                    title={deleteDisabledReason || undefined}
                  >
                    删除
                  </Button>
                </div>
              </div>
            );
          })}
          {!workspaces.isLoading && !workspaces.data?.length && (
            <p className="muted">还没有工作空间，请先创建一个。</p>
          )}
        </div>
      </section>
      {error && <p className="flash err">{error}</p>}
    </section>
  );
}

export function ModelConnectionSettingsPage() {
  const [section, setSection] = useState("connection");
  const sections = [
    { id: "connection", label: "连接" },
    { id: "defaults", label: "默认模型" },
    { id: "project", label: "项目模型" },
    { id: "advanced", label: "高级" },
  ];
  const { workspaces, projects, selectedWorkspaceId, selectWorkspace } = useSettingsWorkspace();
  const returnTo = useRouterState({
    select: (state) => validateSettingsReturnTo(state.location.search.returnTo),
  });
  const originProjectId = returnTo?.match(/^\/projects\/([^/?#]+)/)?.[1];
  const selectionScope = JSON.stringify([selectedWorkspaceId, returnTo]);
  const [projectSelection, setProjectSelection] = useState<{ scope: string; id: string } | null>(
    null,
  );
  const selectedProjectId =
    projectSelection?.scope === selectionScope ? projectSelection.id : originProjectId;
  // Only a project returned for this workspace may become the selected target.
  const selectedProject = projects.data?.find((project) => project.id === selectedProjectId);

  return (
    <main className="df-page df-settings-page" data-testid="model-settings-page">
      <SettingsHeader title="模型连接" />
      <div className="df-settings-section">
        {workspaces.isError ? (
          <p className="flash err" role="alert">
            无法读取工作空间。<Button onClick={() => void workspaces.refetch()}>重试</Button>
          </p>
        ) : workspaces.isPending ? (
          <p role="status">正在读取工作空间…</p>
        ) : (
          <WorkspaceSelector
            workspaces={workspaces.data ?? []}
            selectedWorkspaceId={selectedWorkspaceId}
            onChange={(id) => {
              selectWorkspace(id);
              setProjectSelection(null);
            }}
          />
        )}
      </div>
      <Tabs label="模型设置分区" className="df-section-tabs">
        {sections.map((item) => (
          <Tab
            key={item.id}
            id={`settings-tab-${item.id}`}
            aria-controls={`settings-panel-${item.id}`}
            active={section === item.id}
            onClick={() => setSection(item.id)}
          >
            {item.label}
          </Tab>
        ))}
      </Tabs>
      <section
        role="tabpanel"
        id="settings-panel-connection"
        aria-labelledby="settings-tab-connection"
        hidden={section !== "connection"}
      >
        <ProviderConnectionPanel
          key={selectedWorkspaceId ?? "no-workspace"}
          workspaceId={selectedWorkspaceId}
          projects={projects.isSuccess ? projects.data : []}
          initialProjectId={selectedProject?.id}
        />
      </section>
      {projects.isError && (
        <p role="alert">
          无法确认当前空间的作品列表。
          <Button onClick={() => void projects.refetch()}>重新读取作品列表</Button>
        </p>
      )}
      {projects.isSuccess && selectedProject && (
        <ProjectModelSourceSummary
          key={selectedProject.id}
          projectId={selectedProject.id}
          projectName={selectedProject.name}
        />
      )}
      <section
        role="tabpanel"
        id="settings-panel-defaults"
        aria-labelledby="settings-tab-defaults"
        hidden={section !== "defaults"}
        data-testid="default-models-disclosure"
      >
        <WorkspaceModelProfileSettings
          key={selectedWorkspaceId ?? "no-workspace"}
          workspaceId={selectedWorkspaceId}
        />
      </section>
      <section
        role="tabpanel"
        id="settings-panel-project"
        aria-labelledby="settings-tab-project"
        hidden={section !== "project"}
        data-testid="project-models-disclosure"
      >
        <h2>项目模型覆盖</h2>
        <p className="muted">仅影响所选项目。</p>
        <Field>
          项目
          <Select
            aria-label="项目模型覆盖"
            value={selectedProject?.id ?? ""}
            onChange={(event) =>
              setProjectSelection({ scope: selectionScope, id: event.target.value })
            }
          >
            <option value="">选择项目</option>
            {(projects.data ?? []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </Select>
        </Field>
        {projects.isError && <p role="alert">无法读取项目列表。</p>}
        {selectedProject && (
          <Link
            className="df-btn"
            to="/settings/projects/$projectId"
            params={{ projectId: selectedProject.id }}
            search={returnTo ? { returnTo } : {}}
          >
            配置项目模型
          </Link>
        )}
      </section>
      <section
        role="tabpanel"
        id="settings-panel-advanced"
        aria-labelledby="settings-tab-advanced"
        hidden={section !== "advanced"}
        data-testid="text-service-disclosure"
      >
        <TextGatewaySettings />
      </section>
    </main>
  );
}

export function ProjectSettingsPage() {
  const params = useParams({ strict: false }) as { projectId?: string };
  const projectId = params.projectId ?? "";
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: () => fetchProject(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  return (
    <main className="df-page df-settings-page" data-testid="project-settings-page">
      <SettingsHeader title={project.data?.name ? `${project.data.name} · 项目模型` : "项目模型"} />
      {project.isLoading ? (
        <p className="muted" role="status">
          正在读取项目设置…
        </p>
      ) : project.isError || !project.data ? (
        <p className="flash err">无法读取当前项目，请返回项目大厅重新选择。</p>
      ) : (
        <>
          <section className="df-settings-section">
            <ProviderConfigurationBoundaries />
            <ModelProfileSettings projectId={projectId} workspaceId={project.data.workspace_id} />
          </section>
        </>
      )}
    </main>
  );
}
