import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute, useNavigate, redirect } from "@tanstack/react-router";
import { ArrowUpRight, Clapperboard, Plus, Search } from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
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
import { getRememberedProjectId } from "../lib/navigationPreferences";
import { Button, Field, Input, Select, PageHeader } from "../components/ui";
import { CreateProjectForm } from "../features/project/CreateProjectForm";
import { LazyWorkspaceSettingsPage } from "./pages";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: ({ location }) => {
    const hash = location.hash.replace(/^#/, "");
    if (hash === "project-filters" || hash === "recent-projects") {
      throw redirect({
        to: "/",
        search: { create: undefined, panel: hash === "project-filters" ? "workspace" : "recent" },
        hash: "",
        replace: true,
      });
    }
    const createParam = new URLSearchParams(location.searchStr).get("create");
    if (createParam === "false" || createParam === "0") {
      throw redirect({
        to: "/",
        search: { ...location.search, create: undefined },
        hash: location.hash,
        replace: true,
      });
    }
  },
  validateSearch: (
    search: Record<string, unknown>,
  ): { create?: boolean; panel?: "workspace" | "recent" | "select" } => ({
    create:
      search.create === true || search.create === "1" || search.create === "true"
        ? true
        : undefined,
    panel: (search.panel === "workspace" || search.panel === "recent" || search.panel === "select"
      ? search.panel
      : undefined) as "workspace" | "recent" | "select" | undefined,
  }),
  component: HomePage,
});

const PROJECT_PAGE_SIZE = 12;

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
  const createOpen = Boolean(search.create);
  const setCreateOpen = (open: boolean) =>
    void navigate({ to: "/", search: { ...search, create: open || undefined } });
  const [projectFilter, setProjectFilter] = useState("");
  const [visibleProjectLimit, setVisibleProjectLimit] = useState(PROJECT_PAGE_SIZE);
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
  const displayedProjects = visibleProjects.slice(0, visibleProjectLimit);
  const remainingProjectCount = visibleProjects.length - displayedProjects.length;

  useEffect(() => {
    setVisibleProjectLimit(PROJECT_PAGE_SIZE);
  }, [projectFilter, selectedWorkspaceId]);
  const rememberedProjectId = getRememberedProjectId();
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

  return (
    <main className="df-page df-project-lobby" data-testid="home-panel">
      <PageHeader
        title={
          createOpen
            ? "新建项目"
            : search.panel === "workspace"
              ? "工作空间"
              : search.panel === "recent"
                ? "最近打开"
                : search.panel === "select"
                  ? "选择项目开始创作"
                  : "项目大厅"
        }
        actions={
          <>
            {!apiLive && <span className="status-bad">服务未就绪</span>}
            {currentUser.data && !createOpen && search.panel !== "workspace" && (
              <Button tone="primary" onClick={() => setCreateOpen(true)}>
                <Plus size={16} aria-hidden="true" />
                新建项目
              </Button>
            )}
          </>
        }
      />

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
                <Field>
                  邮箱
                  <Input
                    id="email"
                    name="email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="username"
                    placeholder="owner@example.com"
                    required
                  />
                </Field>
                <Field>
                  密码
                  <Input
                    id={ownerInitialized ? "current-password" : "new-password"}
                    name="password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete={ownerInitialized ? "current-password" : "new-password"}
                    placeholder="输入密码"
                    required
                  />
                </Field>
                {registrationAvailable && (
                  <Field>
                    显示名
                    <Input
                      id="display-name"
                      name="display-name"
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      autoComplete="name"
                    />
                  </Field>
                )}
                <div className="toolbar">
                  {ownerInitialized && (
                    <Button
                      tone="primary"
                      type="submit"
                      disabled={authenticate.isPending || !apiLive || !authFormReady}
                    >
                      登录
                    </Button>
                  )}
                  {registrationAvailable && (
                    <Button
                      tone="primary"
                      type="submit"
                      disabled={
                        authenticate.isPending || !apiLive || !authFormReady || !displayName.trim()
                      }
                    >
                      初始化 Owner
                    </Button>
                  )}
                </div>
              </form>
            </>
          )}
        </section>
      ) : (
        <>
          <CreateProjectForm
            open={createOpen}
            workspaceId={selectedWorkspaceId}
            workspaces={workspaces.data ?? []}
            onWorkspaceChange={selectWorkspace}
            onCancel={() => setCreateOpen(false)}
            onCreated={(projectId) =>
              void navigate({ to: "/projects/$projectId/script", params: { projectId } })
            }
          />
          {!createOpen && search.panel === "workspace" && (
            <section aria-label="管理工作空间" data-testid="workspace-management-disclosure">
              <Suspense fallback={<p role="status">正在读取工作空间…</p>}>
                <LazyWorkspaceSettingsPage onWorkspaceChange={selectWorkspace} />
              </Suspense>
            </section>
          )}
          {!createOpen && recentProject && search.panel !== "workspace" && (
            <section className="df-lobby-section" id="recent-projects">
              <header>
                <h2>继续创作</h2>
              </header>
              <article className="df-continue-card">
                <span className="df-project-cover" aria-hidden="true">
                  <Clapperboard size={24} />
                </span>
                <div>
                  <strong>{recentProject.name}</strong>
                  <p>
                    画幅
                    {recentProject.aspect_ratio}
                  </p>
                </div>
                <Button tone="primary" type="button" onClick={() => openProject(recentProject.id)}>
                  继续创作
                </Button>
              </article>
            </section>
          )}

          {search.panel === "recent" && !recentProject && (
            <p role="status">当前空间还没有最近打开的项目。</p>
          )}
          <section
            hidden={createOpen || search.panel === "recent" || search.panel === "workspace"}
            className="df-lobby-section"
            aria-labelledby="all-projects-title"
          >
            <header>
              <h2 id="all-projects-title">全部项目</h2>
            </header>
            <div className="df-project-filters" id="project-filters">
              <Field>
                <span className="sr-only">工作空间</span>
                <Select
                  aria-label="工作空间筛选"
                  value={selectedWorkspaceId ?? ""}
                  onChange={(event) => selectWorkspace(event.target.value || null)}
                >
                  {(workspaces.data ?? []).map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field>
                <span className="sr-only">搜索项目</span>
                <span className="df-search-field">
                  <Search size={16} aria-hidden="true" />
                  <Input
                    aria-label="搜索项目"
                    value={projectFilter}
                    onChange={(event) => setProjectFilter(event.target.value)}
                    placeholder="搜索项目名称"
                  />
                </span>
              </Field>
            </div>

            {workspaces.isError || projects.isError ? (
              <div className="panel" role="status">
                <p>无法读取项目列表，请重新加载。</p>
                <Button
                  onClick={() => {
                    void workspaces.refetch();
                    if (selectedWorkspaceId) void projects.refetch();
                  }}
                >
                  重新加载列表
                </Button>
              </div>
            ) : workspaces.isPending ? (
              <p role="status">正在读取工作空间…</p>
            ) : !workspaces.data?.length ? (
              <div className="panel">
                <p>还没有工作空间。</p>
                <Link to="/" search={{ panel: "workspace" }}>
                  管理工作空间
                </Link>
              </div>
            ) : projects.isLoading ? (
              <div className="panel muted" role="status">
                正在读取项目…
              </div>
            ) : visibleProjects.length ? (
              <div className="df-project-grid" role="list" aria-label="项目列表">
                {displayedProjects.map((project) => (
                  <div role="listitem" key={project.id}>
                    <Button
                      className="df-project-card"
                      type="button"
                      onClick={() => openProject(project.id)}
                    >
                      <span className="df-project-cover" aria-hidden="true">
                        <Clapperboard size={24} />
                      </span>
                      <span className="df-project-card-body">
                        <strong title={project.name}>{project.name}</strong>
                        <span className="df-project-card-meta">
                          {project.aspect_ratio === "16:9" ? "横屏" : "竖屏"} ·{" "}
                          {project.aspect_ratio}
                        </span>
                        <span className="df-project-card-enter">
                          打开作品 <ArrowUpRight size={16} aria-hidden="true" />
                        </span>
                      </span>
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="panel muted">
                <p>{projectFilter.trim() ? "没有符合搜索条件的项目。" : "当前空间暂无项目。"}</p>
                {!projectFilter.trim() && (
                  <Button tone="primary" onClick={() => setCreateOpen(true)}>
                    创建第一个项目
                  </Button>
                )}
              </div>
            )}

            {remainingProjectCount > 0 && (
              <div className="df-project-more">
                <Button
                  tone="ghost"
                  type="button"
                  onClick={() => setVisibleProjectLimit((limit) => limit + PROJECT_PAGE_SIZE)}
                >
                  显示更多项目（剩余 {remainingProjectCount} 个）
                </Button>
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
