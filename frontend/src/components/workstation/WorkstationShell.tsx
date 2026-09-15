import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  Aperture,
  ChevronLeft,
  Clapperboard,
  FileText,
  Film,
  FolderKanban,
  Menu,
  Package,
  Scissors,
  Settings,
  SlidersHorizontal,
  UserRound,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  getSelectedWorkspaceId,
  resolveProjectWorkspace,
  setSelectedWorkspaceId,
} from "../../lib/api";
import { validateSettingsReturnTo, setRememberedProjectId } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import "./navigation-shell.css";

type WorkstationShellProps = {
  children: ReactNode;
};

type PrimarySection = "projects" | "creation" | "settings";

function projectIdFromPath(pathname: string): string | null {
  return (
    pathname.match(/^\/projects\/([^/]+)/)?.[1] ??
    pathname.match(/^\/settings\/projects\/([^/]+)/)?.[1] ??
    null
  );
}

function primarySectionFromPath(pathname: string): PrimarySection {
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/projects/")) return "creation";
  return "projects";
}

function creationViewFromPath(pathname: string): string | null {
  const segment = pathname.match(/^\/projects\/[^/]+\/([^/]+)/)?.[1] ?? null;
  return segment === "review" ? "production" : segment;
}

function PrimaryLink({
  active,
  label,
  to,
  icon: Icon,
  onActivate,
  search,
}: {
  active: boolean;
  label: string;
  to: string;
  icon: typeof FolderKanban;
  onActivate: () => void;
  search?: Record<string, unknown>;
}) {
  return (
    <Link
      to={to}
      search={search}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
      aria-label={label}
      onClick={(event) => {
        if (active) {
          event.preventDefault();
          onActivate();
        }
      }}
    >
      <Icon size={20} aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}

function ContextLink({
  active,
  label,
  to,
  icon: Icon,
  search,
}: {
  active: boolean;
  label: string;
  to: string;
  icon?: typeof FileText;
  search?: Record<string, unknown>;
}) {
  return (
    <Link
      to={to}
      search={search}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
    >
      {Icon && <Icon size={17} aria-hidden="true" />}
      <span>{label}</span>
    </Link>
  );
}

export function WorkstationShell({ children }: WorkstationShellProps) {
  const queryClient = useQueryClient();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const primary = primarySectionFromPath(pathname);
  const projectId = projectIdFromPath(pathname);
  const [secondaryOpen, setSecondaryOpen] = useState(
    () => window.innerWidth >= 720 || primary === "settings",
  );
  const previousLocation = useRef(location.href);
  const previousPrimary = useRef(primary);
  useEffect(() => {
    if (previousPrimary.current !== primary) {
      setSecondaryOpen(window.innerWidth >= 720 || primary === "settings");
    } else if (previousLocation.current !== location.href && window.innerWidth < 720) {
      setSecondaryOpen(false);
    }
    previousPrimary.current = primary;
    previousLocation.current = location.href;
  }, [location.href, primary]);

  useEffect(() => {
    if (!secondaryOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSecondaryOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [secondaryOpen]);

  const projectContext = useQuery({
    queryKey: queryKeys.project.workspaceContext(projectId ?? "none"),
    queryFn: async () => {
      const resolved = await resolveProjectWorkspace(projectId!, getSelectedWorkspaceId());
      // Establish the header source before child Project routes mount and start
      // their own business queries.
      setSelectedWorkspaceId(resolved.workspaceId);
      setRememberedProjectId(projectId!);
      queryClient.setQueryData(queryKeys.project.detail(projectId!), resolved.project);
      return resolved;
    },
    enabled: Boolean(projectId && projectId !== "demo"),
    retry: false,
    staleTime: 60_000,
  });

  const returnTo = validateSettingsReturnTo(location.search.returnTo);
  const navigationProjectId =
    projectId ?? (returnTo ? projectIdFromPath(returnTo.split(/[?#]/)[0]) : null);
  const projectName =
    navigationProjectId === "demo"
      ? "演示项目"
      : (projectContext.data?.project.name ?? (navigationProjectId ? "当前项目" : null));
  const settingsOrigin = primary === "settings" ? returnTo : location.href;
  const settingsSearch = settingsOrigin ? { returnTo: settingsOrigin } : {};
  const returnUrl = new URL(
    returnTo ?? (projectId ? `/projects/${projectId}` : "/?create=false"),
    window.location.origin,
  );
  const returnSearch = Object.fromEntries(returnUrl.searchParams);
  const creationTarget =
    primary === "creation" ? pathname : navigationProjectId ? returnUrl.pathname : "/";
  const creationView = creationViewFromPath(pathname);
  const needsProjectContext = Boolean(projectId && projectId !== "demo");
  const projectContent = needsProjectContext ? (
    projectContext.isPending ? (
      <main className="df-page">
        <p className="muted">正在恢复项目工作区…</p>
      </main>
    ) : projectContext.isError ? (
      <main className="df-page">
        <section className="panel">
          <h1>无法恢复项目工作区</h1>
          <p className="flash err">
            {projectContext.error instanceof Error
              ? projectContext.error.message
              : "项目可能已被删除，或当前账号已无权访问。"}
          </p>
          <Link to="/" search={{ create: false }}>
            返回项目大厅
          </Link>
        </section>
      </main>
    ) : (
      children
    )
  ) : (
    children
  );

  return (
    <div
      className={`df-global-shell${secondaryOpen ? " secondary-open" : ""}`}
      data-testid="workstation-shell"
      data-primary-section={primary}
    >
      <aside className="df-primary-sidebar">
        <Link
          to="/"
          search={{ create: false }}
          className="df-primary-brand"
          aria-label="DramaForge 项目大厅"
        >
          <Aperture size={23} aria-hidden="true" />
        </Link>
        <nav aria-label="一级导航">
          <PrimaryLink
            active={primary === "projects"}
            label="项目"
            to="/"
            icon={FolderKanban}
            onActivate={() => setSecondaryOpen(true)}
          />
          <PrimaryLink
            active={primary === "creation"}
            label="创作"
            to={creationTarget}
            search={navigationProjectId ? returnSearch : { create: false, panel: "select" }}
            icon={Clapperboard}
            onActivate={() => setSecondaryOpen(true)}
          />
          <div className="df-primary-bottom">
            <button
              type="button"
              className="df-secondary-toggle"
              onClick={() => setSecondaryOpen((open) => !open)}
              aria-label={secondaryOpen ? "收起二级导航" : "展开二级导航"}
              aria-expanded={secondaryOpen}
            >
              {secondaryOpen ? (
                <ChevronLeft size={19} aria-hidden="true" />
              ) : (
                <Menu size={19} aria-hidden="true" />
              )}
            </button>
            <PrimaryLink
              to="/settings/account"
              search={settingsSearch}
              active={primary === "settings"}
              label="设置"
              icon={Settings}
              onActivate={() => setSecondaryOpen(true)}
            />
            <span className="df-owner-mark" aria-label="Owner 账号">
              创
            </span>
          </div>
        </nav>
      </aside>

      <aside className="df-context-sidebar" aria-label="二级导航">
        {primary === "projects" && (
          <>
            <header>
              <span>项目</span>
              <strong>项目大厅</strong>
            </header>
            <nav aria-label="项目导航">
              <Link
                to="/"
                search={{ create: false }}
                aria-current={!location.search.panel ? "page" : undefined}
              >
                全部项目
              </Link>
              <Link
                to="/"
                search={{ create: false, panel: "recent" }}
                aria-current={location.search.panel === "recent" ? "page" : undefined}
              >
                最近打开
              </Link>
              <Link
                to="/"
                search={{ create: false, panel: "workspace" }}
                aria-current={location.search.panel === "workspace" ? "page" : undefined}
              >
                按工作空间筛选
              </Link>
            </nav>
            <Link className="df-context-primary-action" to="/" search={{ create: true }}>
              新建项目
            </Link>
          </>
        )}

        {primary === "creation" && projectId && (
          <>
            <header>
              <span>当前项目</span>
              <strong>{projectName}</strong>
              <Link to="/" search={{ create: false }} className="df-project-switcher">
                切换项目
              </Link>
            </header>
            <nav aria-label="创作导航">
              <ContextLink
                active={creationView === "script"}
                label="剧本"
                to={`/projects/${projectId}/script`}
                icon={FileText}
              />
              <ContextLink
                active={creationView === "assets"}
                label="资产"
                to={`/projects/${projectId}/assets`}
                icon={Package}
              />
              <ContextLink
                active={creationView === "scenes"}
                label="场景"
                to={`/projects/${projectId}/scenes`}
                icon={Film}
              />
              <ContextLink
                active={creationView === "production"}
                label="制作"
                to={`/projects/${projectId}/production`}
                icon={Clapperboard}
              />
              <ContextLink
                active={creationView === "edit"}
                label="剪辑"
                to={`/projects/${projectId}/edit`}
                icon={Scissors}
              />
            </nav>
          </>
        )}

        {primary === "settings" && (
          <>
            <header>
              <span>全局配置与项目配置</span>
              <strong>设置</strong>
              <Link
                to={returnUrl.pathname}
                search={returnSearch}
                hash={returnUrl.hash.slice(1)}
                className="df-project-switcher"
                replace
              >
                {navigationProjectId ? "返回创作" : "返回项目大厅"}
              </Link>
            </header>
            <nav aria-label="设置导航">
              <span className="df-nav-scope">全局 · 跨项目配置</span>
              <ContextLink
                active={pathname === "/settings/account"}
                label="账号与实例"
                to="/settings/account"
                search={settingsSearch}
                icon={UserRound}
              />
              <ContextLink
                active={pathname === "/settings/workspaces"}
                label="工作空间（项目归集）"
                to="/settings/workspaces"
                search={settingsSearch}
                icon={FolderKanban}
              />
              <ContextLink
                active={pathname === "/settings/models"}
                label="模型连接"
                to="/settings/models"
                search={settingsSearch}
                icon={Wrench}
              />
              <ContextLink
                active={pathname === "/settings/defaults"}
                label="新项目默认偏好"
                to="/settings/defaults"
                search={settingsSearch}
                icon={SlidersHorizontal}
              />
              {navigationProjectId && (
                <>
                  <span className="df-nav-scope">仅此项目</span>
                  <Link
                    to="/settings/projects/$projectId"
                    params={{ projectId: navigationProjectId }}
                    search={settingsSearch}
                    className={pathname.startsWith("/settings/projects/") ? "active" : undefined}
                    aria-current={pathname.startsWith("/settings/projects/") ? "page" : undefined}
                  >
                    <Clapperboard size={17} aria-hidden="true" />
                    <span>项目设置</span>
                  </Link>
                </>
              )}
            </nav>
          </>
        )}
      </aside>

      {secondaryOpen && (
        <button
          type="button"
          className="df-context-scrim"
          onClick={() => setSecondaryOpen(false)}
          aria-label="关闭二级导航"
        />
      )}

      <div className="df-shell-content">{projectContent}</div>
    </div>
  );
}
