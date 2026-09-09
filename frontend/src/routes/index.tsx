import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute, useNavigate } from "@tanstack/react-router";
import { Clapperboard, Plus, Search } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createProject,
  fetchBootstrapStatus,
  fetchCurrentUser,
  fetchHealth,
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  loginUser,
  registerUser,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
} from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (search: Record<string, unknown>) => ({
    create: search.create === true || search.create === "1",
  }),
  component: HomePage,
});

const V1_TEMPLATES = [
  { key: "dual_character_conflict_v1", name: "双人对白反转" },
  { key: "single_monologue_v1", name: "单人情绪独白" },
] as const;

const STAGE_LABELS: Record<string, string> = {
  draft: "创作准备",
  planning: "故事规划",
  production: "制作中",
  review: "待审内容",
  delivering: "交付中",
  archived: "已归档",
};

function HomePage() {
  const navigate = useNavigate();
  const search = indexRoute.useSearch();
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: queryKeys.health(),
    queryFn: fetchHealth,
    refetchInterval: 8_000,
    retry: 1,
  });
  const bootstrapStatus = useQuery({
    queryKey: queryKeys.auth.bootstrap(),
    queryFn: fetchBootstrapStatus,
    retry: 1,
  });
  const currentUser = useQuery({
    queryKey: queryKeys.auth.currentUser(),
    queryFn: fetchCurrentUser,
    retry: false,
  });
  const workspaces = useQuery({
    queryKey: queryKeys.workspace.list(),
    queryFn: listWorkspaces,
    enabled: Boolean(currentUser.data),
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("创作者");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const [projectName, setProjectName] = useState("新短剧");
  const [aspectRatio, setAspectRatio] = useState<"9:16" | "16:9">("9:16");
  const [startType, setStartType] = useState<"TEMPLATE" | "FREE">("FREE");
  const [templateKey, setTemplateKey] = useState<string>(V1_TEMPLATES[0].key);
  const [directorAutonomy, setDirectorAutonomy] = useState<"AUTO" | "ASSIST" | "MANUAL">("ASSIST");
  const [createOpen, setCreateOpen] = useState(search.create);
  const [projectFilter, setProjectFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const selectWorkspace = useCallback((workspaceId: string | null) => {
    persistSelectedWorkspaceId(workspaceId);
    setSelectedWorkspaceId(workspaceId);
  }, []);

  useEffect(() => {
    if (search.create) setCreateOpen(true);
  }, [search.create]);

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
    enabled: Boolean(
      currentUser.data &&
      selectedWorkspaceId &&
      workspaces.data?.some((workspace) => workspace.id === selectedWorkspaceId),
    ),
  });

  const authenticate = useMutation({
    onMutate: async () => {
      selectWorkspace(null);
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.auth.currentUser() }),
        queryClient.cancelQueries({ queryKey: queryKeys.workspace.list() }),
        queryClient.cancelQueries({ queryKey: queryKeys.workspace.projectsRoot() }),
      ]);
      queryClient.removeQueries({ queryKey: queryKeys.auth.currentUser() });
      queryClient.removeQueries({ queryKey: queryKeys.workspace.list() });
      queryClient.removeQueries({ queryKey: queryKeys.workspace.projectsRoot() });
    },
    mutationFn: async (mode: "login" | "register") => {
      setError(null);
      return mode === "register"
        ? registerUser(email, password, displayName)
        : loginUser(email, password);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.currentUser() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.list() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.bootstrap() });
    },
    onError: (cause: Error) => {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("邮箱或密码不正确，请使用初始化此实例时创建的 Owner 账号。");
      } else if (cause instanceof ApiError && cause.code === "REGISTRATION_CLOSED") {
        setError("此单用户实例已有 Owner，请直接登录。");
      } else {
        setError(cause.message);
      }
    },
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
      await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.projectsRoot() });
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
  const visibleProjects = useMemo(() => {
    const value = projectFilter.trim().toLocaleLowerCase();
    if (!value) return projects.data ?? [];
    return (projects.data ?? []).filter((project) =>
      project.name.toLocaleLowerCase().includes(value),
    );
  }, [projectFilter, projects.data]);
  const rememberedProjectId = window.sessionStorage.getItem("dramaforge.last-project-id");
  const recentProject =
    (projects.data ?? []).find((project) => project.id === rememberedProjectId) ?? null;
  const queryError =
    workspaces.error instanceof Error
      ? workspaces.error.message
      : projects.error instanceof Error
        ? projects.error.message
        : null;

  function openProject(projectId: string) {
    void navigate({ to: "/projects/$projectId", params: { projectId } });
  }

  function submitProject(event: FormEvent) {
    event.preventDefault();
    createProjectMutation.mutate();
  }

  return (
    <main className="df-page" data-testid="home-panel">
      <header className="df-page-header">
        <div>
          <p className="df-page-eyebrow">Projects</p>
          <h1>项目大厅</h1>
          <p>找到作品、恢复上次位置，或者从同一条创作主链开始新项目。</p>
        </div>
        <div className="toolbar">
          <span className={apiLive ? "status-ok" : "status-bad"}>
            {apiLive ? "服务就绪" : "服务未就绪"}
          </span>
          {currentUser.data && (
            <button className="primary" type="button" onClick={() => setCreateOpen(true)}>
              <Plus size={16} aria-hidden="true" />
              新建项目
            </button>
          )}
        </div>
      </header>

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
                <span className="auth-mode-badge">{ownerInitialized ? "单用户" : "首次设置"}</span>
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
                    id="email"
                    name="email"
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
                    id={ownerInitialized ? "current-password" : "new-password"}
                    name="password"
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
                      id="display-name"
                      name="display-name"
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
                        authenticate.isPending || !apiLive || !authFormReady || !displayName.trim()
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
          {createOpen && (
            <section className="panel df-create-panel" aria-label="新建项目">
              <div className="panel-header">
                <div>
                  <h2>新建项目</h2>
                  <p className="muted">创建起点和导演参与度不会改变工作台或运行路径。</p>
                </div>
                <button className="ghost" type="button" onClick={() => setCreateOpen(false)}>
                  取消
                </button>
              </div>
              <form className="inline-form project-create" onSubmit={submitProject}>
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
                  onChange={(event) => setStartType(event.target.value as "TEMPLATE" | "FREE")}
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
                    setDirectorAutonomy(event.target.value as "AUTO" | "ASSIST" | "MANUAL")
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
                  创建并进入剧本
                </button>
              </form>
            </section>
          )}

          <section className="df-lobby-section" id="recent-projects">
            <header>
              <h2>继续创作</h2>
              <p className="muted">打开最近项目后恢复上次有效工作位置。</p>
            </header>
            {recentProject ? (
              <article className="df-continue-card">
                <span className="df-project-cover" aria-hidden="true">
                  <Clapperboard size={24} />
                </span>
                <div>
                  <strong>{recentProject.name}</strong>
                  <p>
                    {STAGE_LABELS[recentProject.stage] ?? recentProject.stage} ·{" "}
                    {recentProject.aspect_ratio}
                  </p>
                </div>
                <button
                  className="primary"
                  type="button"
                  onClick={() => openProject(recentProject.id)}
                >
                  继续创作
                </button>
              </article>
            ) : (
              <div className="panel muted">
                {projects.data?.length
                  ? "从全部项目选择作品后，这里会恢复最近打开的项目。"
                  : "当前空间还没有项目，可以从新建项目开始。"}
              </div>
            )}
          </section>

          <section className="df-lobby-section" aria-labelledby="all-projects-title">
            <header>
              <h2 id="all-projects-title">全部项目</h2>
              <p className="muted">项目卡片只呈现作品选择所需的信息。</p>
            </header>
            <div className="df-project-filters" id="project-filters">
              <label>
                <span className="sr-only">工作空间</span>
                <select
                  aria-label="工作空间筛选"
                  value={selectedWorkspaceId ?? ""}
                  onChange={(event) => selectWorkspace(event.target.value || null)}
                >
                  {(workspaces.data ?? []).map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">搜索项目</span>
                <span className="df-search-field">
                  <Search size={16} aria-hidden="true" />
                  <input
                    aria-label="搜索项目"
                    value={projectFilter}
                    onChange={(event) => setProjectFilter(event.target.value)}
                    placeholder="搜索项目名称"
                  />
                </span>
              </label>
            </div>

            {!workspaces.isLoading && !workspaces.data?.length ? (
              <div className="panel">
                <p>还没有工作空间。</p>
                <Link to="/settings/workspaces">前往设置创建工作空间</Link>
              </div>
            ) : projects.isLoading ? (
              <div className="panel muted" role="status">
                正在读取项目…
              </div>
            ) : visibleProjects.length ? (
              <div className="df-project-grid" role="list" aria-label="项目列表">
                {visibleProjects.map((project) => (
                  <div role="listitem" key={project.id}>
                    <button
                      className="df-project-card"
                      type="button"
                      onClick={() => openProject(project.id)}
                    >
                      <span className="df-project-cover" aria-hidden="true">
                        <Clapperboard size={20} />
                      </span>
                      <span>
                        <strong>{project.name}</strong>
                        <p>
                          {STAGE_LABELS[project.stage] ?? project.stage} · {project.aspect_ratio}
                        </p>
                      </span>
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="panel muted">
                {projectFilter.trim() ? "没有符合搜索条件的项目。" : "当前空间暂无项目。"}
              </div>
            )}
          </section>
        </>
      )}

      {(error || queryError) && (
        <p className="flash err" role="alert">
          {error ?? queryError}
        </p>
      )}
    </main>
  );
}
