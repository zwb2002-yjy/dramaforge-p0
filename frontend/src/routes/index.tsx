import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createProject,
  createWorkspace,
  deleteWorkspace,
  fetchBootstrapStatus,
  fetchCurrentUser,
  fetchHealth,
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  loginUser,
  registerUser,
  renameWorkspace,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
  type WorkspaceRead,
} from "../lib/api";
import { ProviderConnectionPanel } from "../components/provider/ProviderConnectionPanel";
import { ProjectLobbyShell } from "../components/workstation/ProjectLobbyShell";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const V1_TEMPLATES = [
  { key: "dual_character_conflict_v1", name: "双人对白反转" },
  { key: "single_monologue_v1", name: "单人情绪独白" },
] as const;

function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 8_000,
    retry: 1,
  });
  const bootstrapStatus = useQuery({
    queryKey: ["bootstrap-status"],
    queryFn: fetchBootstrapStatus,
    retry: 1,
  });
  const currentUser = useQuery({
    queryKey: ["current-user"],
    queryFn: fetchCurrentUser,
    retry: false,
  });
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: listWorkspaces,
    enabled: Boolean(currentUser.data),
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("创作者");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const [workspaceName, setWorkspaceName] = useState("");
  const [projectName, setProjectName] = useState("新短剧");
  const [aspectRatio, setAspectRatio] = useState<"9:16" | "16:9">("9:16");
  const [startType, setStartType] = useState<"TEMPLATE" | "FREE">("FREE");
  const [templateKey, setTemplateKey] = useState<string>(V1_TEMPLATES[0].key);
  const [directorAutonomy, setDirectorAutonomy] = useState<
    "AUTO" | "ASSIST" | "MANUAL"
  >("ASSIST");
  const [error, setError] = useState<string | null>(null);

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
      selectWorkspace(null);
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
      await queryClient.invalidateQueries({ queryKey: ["bootstrap-status"] });
    },
    onError: (cause: Error) => {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("邮箱或密码不正确，请使用初始化此实例时创建的 Owner 账号。");
        return;
      }
      if (cause instanceof ApiError && cause.code === "REGISTRATION_CLOSED") {
        setError("此单用户实例已有 Owner，请直接登录。");
        return;
      }
      setError(cause.message);
    },
  });

  const createWorkspaceMutation = useMutation({
    mutationFn: async () => createWorkspace(workspaceName.trim()),
    onSuccess: async (workspace) => {
      setWorkspaceName("");
      selectWorkspace(workspace.id);
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
      return createProject({
        workspace_id: selectedWorkspaceId,
        name: projectName,
        aspect_ratio: aspectRatio,
        start_type: startType,
        template_key: startType === "TEMPLATE" ? templateKey : null,
        director_autonomy: directorAutonomy,
      });
    },
    onSuccess: async (project) => {
      await invalidateWorkspaceData();
      void navigate({
        to: "/projects/$projectId/script",
        params: { projectId: project.id },
      });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const dbUp = health.data?.db === "up" || (health.data?.status === "ok" && !health.data?.db);
  const apiLive = Boolean(health.data && !health.isError && health.data.status === "ok" && dbUp);
  const registrationAvailable = bootstrapStatus.data?.registration_available === true;
  const ownerInitialized = bootstrapStatus.data?.owner_initialized === true;
  const bootstrapReady = bootstrapStatus.data !== undefined;
  const authFormReady = email.trim().length > 0 && password.length > 0;
  const selectedWorkspace = workspaces.data?.find(
    (workspace) => workspace.id === selectedWorkspaceId,
  );
  const workspacesError = workspaces.error instanceof ApiError ? workspaces.error.message : null;

  function submitWorkspace(event: FormEvent) {
    event.preventDefault();
    if (workspaceName.trim()) createWorkspaceMutation.mutate();
  }

  return (
    <ProjectLobbyShell apiLive={apiLive}>
      <div className="workspace-home" data-testid="home-panel">
        <section className="workspace-header">
          <div>
            <h1>个人创作空间</h1>
            <p className="muted">每个短剧项目都放在仅由你账号拥有的独立空间内。</p>
          </div>
          <span className={apiLive ? "status-ok" : "status-bad"}>
            {apiLive ? "API 就绪" : "API 不可用"}
          </span>
        </section>

        {!currentUser.data ? (
          <section className="panel auth-panel">
            {!bootstrapReady ? (
              <p className="muted auth-loading">正在确认实例账号状态…</p>
            ) : (
              <>
                <div className="auth-heading">
                  <div>
                    <h2>{ownerInitialized ? "Owner 登录" : "初始化 Owner"}</h2>
                    <p className="muted">
                      {ownerInitialized
                        ? "这是单用户实例，已关闭后续注册。"
                        : "首次使用需要创建唯一的 Owner 账号。"}
                    </p>
                  </div>
                  <span className="auth-mode-badge">
                    {ownerInitialized ? "单用户" : "首次设置"}
                  </span>
                </div>
                <form
                  className="auth-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    authenticate.mutate(ownerInitialized ? "login" : "register");
                  }}
                >
                  <label>
                    邮箱
                    <input
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      autoComplete="username"
                      placeholder="owner@example.com"
                      required
                    />
                  </label>
                  <label>
                    密码
                    <input
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete={ownerInitialized ? "current-password" : "new-password"}
                      placeholder="输入密码"
                      required
                    />
                  </label>
                  {registrationAvailable && (
                    <label>
                      显示名
                      <input
                        value={displayName}
                        onChange={(event) => setDisplayName(event.target.value)}
                        autoComplete="name"
                      />
                    </label>
                  )}
                  <div className="toolbar">
                    {ownerInitialized && (
                      <button
                        className="primary"
                        type="submit"
                        disabled={authenticate.isPending || !apiLive || !authFormReady}
                      >
                        登录
                      </button>
                    )}
                    {registrationAvailable && (
                      <button
                        className="primary"
                        type="submit"
                        disabled={
                          authenticate.isPending ||
                          !apiLive ||
                          !authFormReady ||
                          !displayName.trim()
                        }
                      >
                        初始化 Owner
                      </button>
                    )}
                  </div>
                </form>
              </>
            )}
          </section>
        ) : (
          <>
            <section className="panel workspace-manager">
              <div className="panel-header">
                <div>
                  <h2>{currentUser.data.display_name}</h2>
                  <p className="muted">{currentUser.data.email}</p>
                </div>
                <form className="inline-form" onSubmit={submitWorkspace}>
                  <input
                    aria-label="新空间名"
                    value={workspaceName}
                    onChange={(event) => setWorkspaceName(event.target.value)}
                    placeholder="新空间名"
                  />
                  <button
                    type="submit"
                    disabled={!workspaceName.trim() || createWorkspaceMutation.isPending}
                  >
                    创建空间
                  </button>
                </form>
              </div>
              <div className="workspace-list" role="list" aria-label="我的空间">
                {workspaces.data?.map((workspace) => (
                  <div
                    className={
                      workspace.id === selectedWorkspaceId
                        ? "workspace-row selected"
                        : "workspace-row"
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
                        onClick={() => renameWorkspaceMutation.mutate(workspace)}
                      >
                        重命名
                      </button>
                      <button
                        className="ghost danger"
                        type="button"
                        onClick={() => deleteWorkspaceMutation.mutate(workspace)}
                        disabled={projects.data?.some(
                          (project) => project.workspace_id === workspace.id,
                        )}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
                {!workspaces.isLoading && !workspaces.data?.length && (
                  <p className="muted">先创建一个空间开始。</p>
                )}
              </div>
            </section>

            <div id="provider-settings">
              <ProviderConnectionPanel
                key={selectedWorkspaceId ?? "no-workspace"}
                workspaceId={selectedWorkspaceId}
                projects={projects.data ?? []}
              />
            </div>

            <section className="panel project-manager" id="projects">
              <div className="panel-header">
                <div>
                  <h2>{selectedWorkspace?.name ?? "选择一个空间"}</h2>
                  <p className="muted">项目隔离在所选空间内。</p>
                </div>
              </div>
              <form
                className="inline-form project-create"
                onSubmit={(event) => {
                  event.preventDefault();
                  createProjectMutation.mutate();
                }}
              >
                <input
                  aria-label="项目名"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  disabled={!selectedWorkspaceId}
                />
                <select
                  aria-label="画幅"
                  value={aspectRatio}
                  onChange={(event) => setAspectRatio(event.target.value as "9:16" | "16:9")}
                  disabled={!selectedWorkspaceId}
                >
                  <option value="9:16">9:16 竖屏</option>
                  <option value="16:9">16:9 横屏</option>
                </select>
                <select
                  aria-label="创作起点"
                  value={startType}
                  onChange={(event) =>
                    setStartType(event.target.value as "TEMPLATE" | "FREE")
                  }
                  disabled={!selectedWorkspaceId}
                >
                  <option value="FREE">自由创建</option>
                  <option value="TEMPLATE">从模板开始</option>
                </select>
                {startType === "TEMPLATE" && (
                  <select
                    aria-label="创作模板"
                    value={templateKey}
                    onChange={(event) => setTemplateKey(event.target.value)}
                    disabled={!selectedWorkspaceId}
                  >
                    {V1_TEMPLATES.map((template) => (
                      <option key={template.key} value={template.key}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                )}
                <select
                  aria-label="导演参与度"
                  value={directorAutonomy}
                  onChange={(event) =>
                    setDirectorAutonomy(
                      event.target.value as "AUTO" | "ASSIST" | "MANUAL",
                    )
                  }
                  disabled={!selectedWorkspaceId}
                >
                  <option value="AUTO">导演自动 AUTO</option>
                  <option value="ASSIST">导演辅助 ASSIST</option>
                  <option value="MANUAL">手动控制 MANUAL</option>
                </select>
                <button
                  className="primary"
                  type="submit"
                  disabled={!selectedWorkspaceId || createProjectMutation.isPending}
                >
                  创建项目
                </button>
              </form>
              <div className="project-list">
                {projects.data?.map((project) => (
                  <button
                    className="project-row"
                    type="button"
                    key={project.id}
                    onClick={() =>
                      void navigate({
                        to: "/projects/$projectId/production",
                        params: { projectId: project.id },
                      })
                    }
                  >
                    <span>{project.name}</span>
                    <span className="muted">
                  {project.creative_profile?.start_type ?? project.stage} ·{" "}
                  {project.creative_profile?.director_autonomy ?? project.aspect_ratio}
                </span>
                  </button>
                ))}
                {selectedWorkspaceId && !projects.isLoading && !projects.data?.length && (
                  <p className="muted">暂无项目。</p>
                )}
              </div>
            </section>
          </>
        )}
        {(error || workspacesError) && <p className="flash err">{error ?? workspacesError}</p>}
      </div>
    </ProjectLobbyShell>
  );
}
