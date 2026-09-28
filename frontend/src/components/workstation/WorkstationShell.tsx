import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  Aperture,
  ArrowLeft,
  Clapperboard,
  FileText,
  Film,
  FolderKanban,
  Package,
  CheckCheck,
  Scissors,
  Settings,
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

function primarySectionFromPath(pathname: string, panel?: unknown): PrimarySection {
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/projects/") || (pathname === "/" && panel === "select"))
    return "creation";
  return "projects";
}

function creationViewFromPath(pathname: string): string | null {
  const segment = pathname.match(/^\/projects\/[^/]+\/([^/]+)/)?.[1] ?? null;
  return segment;
}

function PrimaryLink({
  active,
  expanded,
  label,
  to,
  icon: Icon,
  onActivate,
  search,
}: {
  active: boolean;
  expanded: boolean;
  label: string;
  to: string;
  icon: typeof FolderKanban;
  onActivate: () => void;
  search?: Record<string, unknown>;
}) {
  return (
    <Link
      to={to}
      search={search ?? {}}
      activeOptions={{ exact: true, includeSearch: true }}
      activeProps={{}}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
      aria-label={label}
      aria-expanded={active && expanded}
      aria-controls="context-navigation"
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
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
  description,
  step,
  search,
}: {
  active: boolean;
  label: string;
  to: string;
  icon?: typeof FileText;
  description?: string;
  step?: string;
  search?: Record<string, unknown>;
}) {
  return (
    <Link
      to={to}
      search={search ?? {}}
      activeOptions={{ exact: true, includeSearch: true }}
      activeProps={{}}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
      aria-label={label}
    >
      {step ? (
        <span className="df-context-step" aria-hidden="true">
          {step}
        </span>
      ) : (
        Icon && <Icon size={17} aria-hidden="true" />
      )}
      <span className="df-context-link-copy">
        <span>{label}</span>
        {description && <small>{description}</small>}
      </span>
    </Link>
  );
}

export function WorkstationShell({ children }: WorkstationShellProps) {
  const queryClient = useQueryClient();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const primary = primarySectionFromPath(pathname, location.search.panel);
  const projectId = projectIdFromPath(pathname);
  const [secondaryOpen, setSecondaryOpen] = useState(() => window.innerWidth >= 1100);
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 1100px)");
    const syncNavigation = () => setSecondaryOpen(wide.matches);
    wide.addEventListener("change", syncNavigation);
    return () => wide.removeEventListener("change", syncNavigation);
  }, []);
  const previousLocation = useRef(location.href);
  const previousPrimary = useRef(primary);
  useEffect(() => {
    if (previousPrimary.current !== primary) {
      setSecondaryOpen(window.innerWidth >= 1100);
    } else if (previousLocation.current !== location.href && window.innerWidth < 1100) {
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
    enabled: Boolean(projectId),
    retry: false,
    staleTime: 60_000,
  });

  const returnTo = validateSettingsReturnTo(location.search.returnTo);
  const navigationProjectId =
    projectId ?? (returnTo ? projectIdFromPath(returnTo.split(/[?#]/)[0]) : null);
  const projectName =
    projectContext.data?.project.name ?? (navigationProjectId ? "当前项目" : null);
  const settingsOrigin = primary === "settings" ? returnTo : location.href;
  const settingsSearch = settingsOrigin ? { returnTo: settingsOrigin } : {};
  const returnUrl = new URL(returnTo ?? "/", window.location.origin);
  const returnSearch = Object.fromEntries(returnUrl.searchParams);
  const creationTarget =
    primary === "creation"
      ? pathname
      : navigationProjectId
        ? projectIdFromPath(returnUrl.pathname) === navigationProjectId
          ? returnUrl.pathname
          : `/projects/${navigationProjectId}`
        : "/";
  const creationView = creationViewFromPath(pathname);
  // Return links use a stable parent (or the validated settings origin), not
  // browser history, so they also work after a refresh or a direct visit.
  const backTarget = pathname.startsWith("/settings/projects/")
    ? { to: "/settings/models", search: settingsSearch, label: "返回模型连接" }
    : primary === "settings"
      ? {
          to: returnUrl.pathname,
          search: returnSearch,
          hash: returnUrl.hash.slice(1),
          label: navigationProjectId ? "返回创作" : "返回项目大厅",
        }
      : projectId && /^\/projects\/[^/]+\/scenes\/[^/]+$/.test(pathname)
        ? { to: `/projects/${projectId}/scenes`, search: {}, label: "返回场景" }
        : projectId && creationViewFromPath(pathname) === "review" && pathname.endsWith("/review")
          ? { to: `/projects/${projectId}/production`, search: {}, label: "返回作品总览" }
          : projectId || location.search.panel || location.search.create
            ? { to: "/", search: {}, label: "返回项目大厅" }
            : null;
  const needsProjectContext = Boolean(projectId);
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
          <Link to="/" search={{ create: undefined }}>
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
          search={{ create: undefined }}
          className="df-primary-brand"
          activeProps={{}}
          activeOptions={{ exact: true, includeSearch: true }}
          aria-label="DramaForge 项目大厅"
        >
          <Aperture size={23} aria-hidden="true" />
        </Link>
        <nav aria-label="一级导航">
          <PrimaryLink
            active={primary === "projects"}
            expanded={secondaryOpen}
            label="项目"
            to="/"
            icon={FolderKanban}
            onActivate={() => setSecondaryOpen((open) => !open)}
          />
          <PrimaryLink
            active={primary === "creation"}
            expanded={secondaryOpen}
            label="创作"
            to={creationTarget}
            search={
              navigationProjectId
                ? creationTarget === returnUrl.pathname
                  ? returnSearch
                  : {}
                : { panel: "select" }
            }
            icon={Clapperboard}
            onActivate={() => setSecondaryOpen((open) => !open)}
          />
          <div className="df-primary-bottom">
            <PrimaryLink
              to="/settings/models"
              search={settingsSearch}
              active={primary === "settings"}
              expanded={secondaryOpen}
              label="设置"
              icon={Settings}
              onActivate={() => setSecondaryOpen((open) => !open)}
            />
          </div>
        </nav>
      </aside>

      <aside id="context-navigation" className="df-context-sidebar" aria-label="二级导航">
        {(primary === "projects" || (primary === "creation" && !projectId)) && (
          <>
            <header>
              <span>{primary === "creation" ? "创作" : "项目"}</span>
              <strong>{primary === "creation" ? "选择项目" : "项目大厅"}</strong>
            </header>
            <nav aria-label="项目导航">
              <ContextLink
                to="/"
                search={{}}
                label="全部项目"
                active={!location.search.panel && !location.search.create}
              />
              <ContextLink
                to="/"
                search={{ panel: "recent" }}
                label="最近打开"
                active={location.search.panel === "recent" && !location.search.create}
              />
              <ContextLink
                to="/"
                search={{ panel: "workspace" }}
                label="工作空间"
                active={location.search.panel === "workspace" && !location.search.create}
              />
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
              <Link to="/" search={{ create: undefined }} className="df-project-switcher">
                切换项目
              </Link>
            </header>
            <nav aria-label="创作导航">
              <ContextLink
                active={creationView === "production"}
                label="作品总览"
                to={`/projects/${projectId}/production`}
                icon={Clapperboard}
              />
              <ContextLink
                active={creationView === "script"}
                label="故事剧本"
                step="01"
                to={`/projects/${projectId}/script`}
                icon={FileText}
              />
              <ContextLink
                active={creationView === "assets"}
                label="角色素材"
                step="02"
                to={`/projects/${projectId}/assets`}
                icon={Package}
              />
              <ContextLink
                active={creationView === "scenes"}
                label="分镜制作"
                step="03"
                to={`/projects/${projectId}/scenes`}
                icon={Film}
              />
              <ContextLink
                active={creationView === "review"}
                label="审片确认"
                step="04"
                to={`/projects/${projectId}/review`}
                icon={CheckCheck}
              />
              <ContextLink
                active={creationView === "edit"}
                label="剪辑成片"
                step="05"
                to={`/projects/${projectId}/edit`}
                icon={Scissors}
              />
            </nav>
          </>
        )}

        {primary === "settings" && (
          <>
            <header>
              <strong>设置</strong>
            </header>
            <nav aria-label="设置导航">
              <ContextLink
                active={
                  pathname === "/settings/models" || pathname.startsWith("/settings/projects/")
                }
                label="模型连接"
                to="/settings/models"
                search={settingsSearch}
                icon={Wrench}
              />
              <ContextLink
                active={pathname === "/settings/account"}
                label="账号"
                to="/settings/account"
                search={settingsSearch}
                icon={UserRound}
              />
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

      <div className="df-shell-content">
        {backTarget && (
          <nav className="df-workspace-return" aria-label="页面返回" data-testid="workspace-return">
            <Link
              to={backTarget.to}
              search={backTarget.search}
              hash={backTarget.hash}
              activeProps={{}}
            >
              <ArrowLeft size={16} aria-hidden="true" />
              {backTarget.label}
            </Link>
          </nav>
        )}
        {projectContent}
      </div>
    </div>
  );
}
