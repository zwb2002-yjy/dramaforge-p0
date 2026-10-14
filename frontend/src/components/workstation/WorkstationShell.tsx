import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, defaultParseSearch, useRouter, useRouterState } from "@tanstack/react-router";
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
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import {
  getSelectedWorkspaceId,
  resolveProjectWorkspace,
  setSelectedWorkspaceId,
} from "../../lib/api";
import { validateSettingsReturnTo, setRememberedProjectId } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import { useModalDialog } from "../ui/useModalDialog";
import { Button } from "../ui";
import { ProjectNavigationContext, PROJECT_VIEW_LABELS } from "./projectNavigation";
import "./navigation-shell.css";

type WorkstationShellProps = {
  children: ReactNode;
};

type PrimarySection = "projects" | "project" | "settings";

function projectIdFromPath(pathname: string): string | null {
  return (
    pathname.match(/^\/projects\/([^/]+)/)?.[1] ??
    pathname.match(/^\/settings\/projects\/([^/]+)/)?.[1] ??
    null
  );
}

function primarySectionFromPath(pathname: string): PrimarySection {
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/projects/")) return "project";
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
  expanded?: boolean;
  label: string;
  to: string;
  icon: typeof FolderKanban;
  onActivate?: () => void;
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
      aria-expanded={onActivate ? active && expanded : undefined}
      aria-controls={onActivate ? "context-navigation" : undefined}
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
        if (active && onActivate) {
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
  const router = useRouter();
  const routeStatus = useRouterState({ select: (state) => state.status });
  const routeLoading = useRouterState({ select: (state) => state.isLoading });
  const queryClient = useQueryClient();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const primary = primarySectionFromPath(pathname);
  const projectId = projectIdFromPath(pathname);
  const hasContext = primary !== "projects";
  const [narrow, setNarrow] = useState(() => window.innerWidth < 1100);
  const [secondaryOpen, setSecondaryOpen] = useState(() => hasContext && window.innerWidth >= 1100);
  const contentRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLElement>(null);
  const projectTrigger = useRef<HTMLButtonElement | null>(null);
  const restoreFocusPending = useRef(false);
  const openRef = useRef(secondaryOpen);
  openRef.current = secondaryOpen;
  const restoreProjectFocus = useCallback(() => {
    const trigger = projectTrigger.current;
    if (
      restoreFocusPending.current &&
      trigger?.isConnected &&
      router.state.status === "idle" &&
      !router.state.isLoading &&
      !contentRef.current?.inert
    ) {
      trigger.focus();
      if (document.activeElement === trigger) restoreFocusPending.current = false;
    }
  }, [router]);
  const registerProjectTrigger = useCallback(
    (trigger: HTMLButtonElement | null) => {
      projectTrigger.current = trigger;
      if (trigger) requestAnimationFrame(restoreProjectFocus);
    },
    [restoreProjectFocus],
  );
  const closeNavigation = useCallback(() => {
    if (primary === "project" && openRef.current) restoreFocusPending.current = true;
    setSecondaryOpen(false);
    // The content becomes non-inert on commit; restore focus after that commit.
    requestAnimationFrame(() => {
      if (primary === "project") restoreProjectFocus();
      else
        document
          .querySelector<HTMLElement>('.df-primary-sidebar [aria-controls="context-navigation"]')
          ?.focus();
    });
  }, [primary, restoreProjectFocus]);
  const previousLocation = useRef(location.href);
  const previousPrimary = useRef(primary);
  useEffect(() => {
    if (!hasContext) {
      setSecondaryOpen(false);
    } else if (previousPrimary.current !== primary) {
      setSecondaryOpen(!narrow);
    } else if (previousLocation.current !== location.href && window.innerWidth < 1100) {
      closeNavigation();
    }
    previousPrimary.current = primary;
    previousLocation.current = location.href;
  }, [location.href, primary, hasContext, narrow, closeNavigation]);

  useEffect(() => {
    if (!secondaryOpen || narrow) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeNavigation();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [secondaryOpen, narrow, closeNavigation]);

  const drawerOpen = hasContext && secondaryOpen && narrow;
  useEffect(() => {
    if (drawerOpen) return;
    const frame = requestAnimationFrame(restoreProjectFocus);
    return () => cancelAnimationFrame(frame);
  }, [drawerOpen, location.href, routeStatus, routeLoading, restoreProjectFocus]);
  const navigationRef = useModalDialog<HTMLElement>(drawerOpen, closeNavigation);
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 1100px)");
    const syncNavigation = () => {
      setNarrow(!wide.matches);
      if (!wide.matches && navigationRef.current?.contains(document.activeElement)) {
        closeNavigation();
      } else {
        setSecondaryOpen(hasContext && wide.matches);
      }
    };
    wide.addEventListener("change", syncNavigation);
    return () => wide.removeEventListener("change", syncNavigation);
  }, [hasContext, navigationRef, closeNavigation]);
  useEffect(() => {
    const surfaces = [contentRef.current, railRef.current];
    for (const surface of surfaces) if (surface) surface.inert = drawerOpen;
    return () => {
      for (const surface of surfaces) if (surface) surface.inert = false;
    };
  }, [drawerOpen]);
  useEffect(() => {
    if (!drawerOpen) return;
    // The existing modal hook owns trapping/Escape. Opening an animated sidebar
    // needs one rendered frame before its initially hidden links can take focus.
    let focusFrame = 0;
    const frame = requestAnimationFrame(() => {
      focusFrame = requestAnimationFrame(() =>
        navigationRef.current?.querySelector<HTMLElement>("a[href]")?.focus(),
      );
    });
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(focusFrame);
    };
  }, [drawerOpen, navigationRef]);

  const [activatedProjectId, setActivatedProjectId] = useState<string | null>(null);
  const projectContext = useQuery({
    queryKey: queryKeys.project.workspaceContext(projectId ?? "none"),
    queryFn: async () => {
      const resolved = await resolveProjectWorkspace(projectId!, getSelectedWorkspaceId());
      queryClient.setQueryData(queryKeys.project.detail(projectId!), resolved.project);
      return resolved;
    },
    enabled: Boolean(projectId),
    retry: false,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (!projectId || !projectContext.isSuccess) {
      setActivatedProjectId(null);
      return;
    }
    // A cached context must establish the same header source as a fresh read.
    // Mount children only after activation, so their first request is scoped.
    setSelectedWorkspaceId(projectContext.data.workspaceId);
    setRememberedProjectId(projectId);
    setActivatedProjectId(projectId);
  }, [projectId, projectContext.isSuccess, projectContext.data]);

  const returnTo = validateSettingsReturnTo(location.search.returnTo);
  const navigationProjectId =
    projectId ?? (returnTo ? projectIdFromPath(returnTo.split(/[?#]/)[0]) : null);
  const projectName =
    projectContext.data?.project.name ?? (navigationProjectId ? "当前项目" : null);
  const settingsOrigin = primary === "settings" ? returnTo : location.href;
  const settingsSearch = settingsOrigin ? { returnTo: settingsOrigin } : {};
  const returnUrl = new URL(returnTo ?? "/", window.location.origin);
  const returnSearch = defaultParseSearch(returnUrl.search);
  const creationView = creationViewFromPath(pathname);
  // Return links use a stable parent (or the validated settings origin), not
  // browser history, so they also work after a refresh or a direct visit.
  const backTarget = pathname.startsWith("/settings/projects/")
    ? { to: "/settings/models", search: settingsSearch, label: "返回模型设置" }
    : primary === "settings"
      ? {
          to: returnUrl.pathname,
          search: returnSearch,
          hash: returnUrl.hash.slice(1),
          label: navigationProjectId ? "返回工作台" : "返回我的项目",
        }
      : projectId && /^\/projects\/[^/]+\/scenes\/[^/]+$/.test(pathname)
        ? { to: `/projects/${projectId}/scenes`, search: {}, label: "返回场景" }
        : projectId && creationViewFromPath(pathname) === "review" && pathname.endsWith("/review")
          ? { to: `/projects/${projectId}/production`, search: {}, label: "返回项目总览" }
          : projectId || location.search.panel || location.search.create
            ? { to: "/", search: {}, label: "返回我的项目" }
            : null;
  const needsProjectContext = Boolean(projectId);
  const projectContent = needsProjectContext ? (
    projectContext.isPending || (!projectContext.isError && activatedProjectId !== projectId) ? (
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
            返回我的项目
          </Link>
          <Button onClick={() => void projectContext.refetch()}>重试</Button>
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
      className={`df-global-shell${hasContext && secondaryOpen ? " secondary-open" : ""}`}
      data-testid="workstation-shell"
      data-primary-section={primary}
    >
      <aside className="df-primary-sidebar" ref={railRef}>
        <Link
          to="/"
          search={{ create: undefined }}
          className="df-primary-brand"
          activeProps={{}}
          activeOptions={{ exact: true, includeSearch: true }}
          aria-label="DramaForge 我的项目"
        >
          <Aperture size={23} aria-hidden="true" />
        </Link>
        <nav aria-label="一级导航">
          <PrimaryLink
            active={primary !== "settings"}
            label="我的项目"
            to="/"
            icon={FolderKanban}
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

      {hasContext && (
        <aside
          id={primary === "project" ? "project-navigation" : "context-navigation"}
          className="df-context-sidebar"
          aria-label="二级导航"
          ref={navigationRef}
          role={drawerOpen ? "dialog" : undefined}
          aria-modal={drawerOpen || undefined}
          tabIndex={-1}
        >
          {primary === "project" && projectId && (
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
                  label={PROJECT_VIEW_LABELS.production}
                  to={`/projects/${projectId}/production`}
                  icon={Clapperboard}
                />
                <ContextLink
                  active={creationView === "script"}
                  label={PROJECT_VIEW_LABELS.script}
                  step="01"
                  to={`/projects/${projectId}/script`}
                  icon={FileText}
                />
                <ContextLink
                  active={creationView === "assets"}
                  label={PROJECT_VIEW_LABELS.assets}
                  step="02"
                  to={`/projects/${projectId}/assets`}
                  icon={Package}
                />
                <ContextLink
                  active={creationView === "scenes"}
                  label={PROJECT_VIEW_LABELS.scenes}
                  step="03"
                  to={`/projects/${projectId}/scenes`}
                  icon={Film}
                />
                <ContextLink
                  active={creationView === "review"}
                  label={PROJECT_VIEW_LABELS.review}
                  step="04"
                  to={`/projects/${projectId}/review`}
                  icon={CheckCheck}
                />
                <ContextLink
                  active={creationView === "edit"}
                  label={PROJECT_VIEW_LABELS.edit}
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
                  label="模型设置"
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
      )}

      {hasContext && secondaryOpen && (
        <button
          type="button"
          className="df-context-scrim"
          onClick={closeNavigation}
          aria-label="关闭二级导航"
        />
      )}

      <div className="df-shell-content" ref={contentRef}>
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
        <ProjectNavigationContext.Provider
          value={
            primary === "project"
              ? {
                  open: secondaryOpen,
                  toggle: () => {
                    restoreFocusPending.current = false;
                    setSecondaryOpen((open) => !open);
                  },
                  triggerRef: registerProjectTrigger,
                }
              : null
          }
        >
          {projectContent}
        </ProjectNavigationContext.Provider>
      </div>
    </div>
  );
}
