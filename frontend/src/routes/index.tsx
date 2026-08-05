import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  createWorkspace,
  deleteWorkspace,
  fetchCurrentUser,
  fetchHealth,
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  loginUser,
  registerUser,
  renameWorkspace,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
  startProject,
  type WorkspaceRead,
} from "../lib/api";
import { ProviderConnectionPanel } from "../components/provider/ProviderConnectionPanel";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 8_000, retry: 1 });
  const currentUser = useQuery({ queryKey: ["current-user"], queryFn: fetchCurrentUser, retry: false });
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: listWorkspaces,
    enabled: Boolean(currentUser.data),
  });
  const [email, setEmail] = useState("creator@example.com");
  const [password, setPassword] = useState("password123");
  const [displayName, setDisplayName] = useState("创作者");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const [workspaceName, setWorkspaceName] = useState("");
  const [projectName, setProjectName] = useState("新短剧");
  const [idea, setIdea] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedWorkspaceId && workspaces.data?.[0]) setSelectedWorkspaceId(workspaces.data[0].id);
    if (selectedWorkspaceId && workspaces.data && !workspaces.data.some((workspace) => workspace.id === selectedWorkspaceId)) {
      setSelectedWorkspaceId(workspaces.data[0]?.id ?? null);
    }
  }, [selectedWorkspaceId, workspaces.data]);

  useEffect(() => {
    persistSelectedWorkspaceId(selectedWorkspaceId);
  }, [selectedWorkspaceId]);

  const projects = useQuery({
    queryKey: ["workspace-projects", selectedWorkspaceId],
    queryFn: () => listWorkspaceProjects(selectedWorkspaceId!),
    enabled: Boolean(
      currentUser.data &&
        selectedWorkspaceId &&
        workspaces.data?.some((workspace) => workspace.id === selectedWorkspaceId),
    ),
  });

  const invalidateWorkspaceData = async () => {
    await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    await queryClient.invalidateQueries({ queryKey: ["workspace-projects"] });
  };

  const authenticate = useMutation({
    onMutate: async () => {
      // A session can change accounts without a full page reload. Do not render
      // the prior account's selected workspace or cached projects while the
      // new session is being established.
      setSelectedWorkspaceId(null);
      persistSelectedWorkspaceId(null);
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["current-user"] }),
        queryClient.cancelQueries({ queryKey: ["workspaces"] }),
        queryClient.cancelQueries({ queryKey: ["workspace-projects"] }),
      ]);
      queryClient.removeQueries({ queryKey: ["current-user"] });
      queryClient.removeQueries({ queryKey: ["workspaces"] });
      queryClient.removeQueries({ queryKey: ["workspace-projects"] });
    },
    mutationFn: async (mode: "login" | "register") => {
      setError(null);
      if (mode === "register") return registerUser(email, password, displayName);
      return loginUser(email, password);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["current-user"] });
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const createWorkspaceMutation = useMutation({
    mutationFn: async () => createWorkspace(workspaceName.trim()),
    onSuccess: async (workspace) => {
      setWorkspaceName("");
      setSelectedWorkspaceId(workspace.id);
      await invalidateWorkspaceData();
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const renameWorkspaceMutation = useMutation({
    mutationFn: async (workspace: WorkspaceRead) => {
      const name = window.prompt("空间名", workspace.name)?.trim();
      if (!name || name === workspace.name) return;
      await renameWorkspace(workspace.id, name);
    },
    onSuccess: invalidateWorkspaceData,
    onError: (cause: Error) => setError(cause.message),
  });

  const deleteWorkspaceMutation = useMutation({
    mutationFn: async (workspace: WorkspaceRead) => {
      if (!window.confirm(`删除空间「${workspace.name}」？`)) return;
      await deleteWorkspace(workspace.id);
    },
    onSuccess: invalidateWorkspaceData,
    onError: (cause: Error) => setError(cause.message),
  });

  const createProjectMutation = useMutation({
    mutationFn: async () => {
      if (!selectedWorkspaceId) throw new Error("请先选择一个空间");
      return startProject({ workspace_id: selectedWorkspaceId, name: projectName, aspect_ratio: "9:16", idea });
    },
    onSuccess: async (project) => {
      await invalidateWorkspaceData();
      void navigate({ to: "/projects/$projectId/quick", params: { projectId: project.project_id } });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const dbUp = health.data?.db === "up" || (health.data?.status === "ok" && !health.data?.db);
  const apiLive = Boolean(health.data && !health.isError && health.data.status === "ok" && dbUp);
  const selectedWorkspace = workspaces.data?.find((workspace) => workspace.id === selectedWorkspaceId);
  const workspacesError = workspaces.error instanceof ApiError ? workspaces.error.message : null;

  function submitWorkspace(event: FormEvent) {
    event.preventDefault();
    if (workspaceName.trim()) createWorkspaceMutation.mutate();
  }

  return (
    <div className="workspace-home" data-testid="home-panel">
      <section className="workspace-header">
        <div>
          <h1>个人创作空间</h1>
          <p className="muted">每个短剧项目都放在仅由你账号拥有的独立空间内。</p>
        </div>
        <span className={apiLive ? "status-ok" : "status-bad"}>{apiLive ? "API 就绪" : "API 不可用"}</span>
      </section>

      {!currentUser.data ? (
        <section className="panel auth-panel">
          <h2>登录</h2>
          <form className="auth-form" onSubmit={(event) => { event.preventDefault(); authenticate.mutate("login"); }}>
            <label>邮箱<input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" /></label>
            <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
            <label>显示名<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" /></label>
            <div className="toolbar">
              <button className="primary" type="submit" disabled={authenticate.isPending || !apiLive}>登录</button>
              <button type="button" onClick={() => authenticate.mutate("register")} disabled={authenticate.isPending || !apiLive}>创建账号</button>
            </div>
          </form>
        </section>
      ) : (
        <>
          <section className="panel workspace-manager">
            <div className="panel-header">
              <div><h2>{currentUser.data.display_name}</h2><p className="muted">{currentUser.data.email}</p></div>
              <form className="inline-form" onSubmit={submitWorkspace}>
                <input aria-label="新空间名" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="新空间名" />
                <button type="submit" disabled={!workspaceName.trim() || createWorkspaceMutation.isPending}>创建空间</button>
              </form>
            </div>
            <div className="workspace-list" role="list" aria-label="我的空间">
              {workspaces.data?.map((workspace) => (
                <div className={workspace.id === selectedWorkspaceId ? "workspace-row selected" : "workspace-row"} key={workspace.id} role="listitem">
                  <button className="workspace-select" type="button" onClick={() => setSelectedWorkspaceId(workspace.id)}>{workspace.name}</button>
                  <div className="workspace-actions">
                    <button className="ghost" type="button" onClick={() => renameWorkspaceMutation.mutate(workspace)}>重命名</button>
                    <button className="ghost danger" type="button" onClick={() => deleteWorkspaceMutation.mutate(workspace)} disabled={projects.data?.some((project) => project.workspace_id === workspace.id)}>删除</button>
                  </div>
                </div>
              ))}
              {!workspaces.isLoading && !workspaces.data?.length && <p className="muted">先创建一个空间开始。</p>}
            </div>
          </section>

          <ProviderConnectionPanel
            workspaceId={selectedWorkspaceId}
            projects={projects.data ?? []}
          />

          <section className="panel project-manager">
            <div className="panel-header"><div><h2>{selectedWorkspace?.name ?? "选择一个空间"}</h2><p className="muted">项目隔离在所选空间内。</p></div></div>
            <form className="inline-form project-create" onSubmit={(event) => { event.preventDefault(); createProjectMutation.mutate(); }}>
              <input aria-label="项目名" value={projectName} onChange={(event) => setProjectName(event.target.value)} disabled={!selectedWorkspaceId} />
              <input aria-label="创意想法" value={idea} onChange={(event) => setIdea(event.target.value)} placeholder="创意想法（可选）" disabled={!selectedWorkspaceId} />
              <button className="primary" type="submit" disabled={!selectedWorkspaceId || createProjectMutation.isPending}>创建项目</button>
            </form>
            <div className="project-list">
              {projects.data?.map((project) => (
                <button className="project-row" type="button" key={project.id} onClick={() => void navigate({ to: "/projects/$projectId/quick", params: { projectId: project.id } })}>
                  <span>{project.name}</span><span className="muted">{project.stage} · {project.aspect_ratio}</span>
                </button>
              ))}
              {selectedWorkspaceId && !projects.isLoading && !projects.data?.length && <p className="muted">暂无项目。</p>}
            </div>
          </section>
        </>
      )}
      {(error || workspacesError) && <p className="flash err">{error ?? workspacesError}</p>}
    </div>
  );
}
