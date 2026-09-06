import { useQuery } from "@tanstack/react-query";
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
import { useEffect, useState, type ReactNode } from "react";

import { fetchProject } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import "./navigation-shell.css";

type WorkstationShellProps = {
  children: ReactNode;
};

type PrimarySection = "projects" | "creation" | "settings";

const LAST_PROJECT_STORAGE_KEY = "dramaforge.last-project-id";

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
}: {
  active: boolean;
  label: string;
  to: string;
  icon: typeof FolderKanban;
}) {
  return (
    <Link
      to={to}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
      aria-label={label}
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
}: {
  active: boolean;
  label: string;
  to: string;
  icon?: typeof FileText;
}) {
  return (
    <Link
      to={to}
      className={active ? "active" : undefined}
      aria-current={active ? "page" : undefined}
    >
      {Icon && <Icon size={17} aria-hidden="true" />}
      <span>{label}</span>
    </Link>
  );
}

export function WorkstationShell({ children }: WorkstationShellProps) {
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const primary = primarySectionFromPath(pathname);
  const projectId = projectIdFromPath(pathname);
  const [secondaryOpen, setSecondaryOpen] = useState(
    () => window.innerWidth >= 720 && (primary === "projects" || window.innerWidth >= 1360),
  );

  useEffect(() => {
    setSecondaryOpen(
      window.innerWidth >= 720 && (primary === "projects" || window.innerWidth >= 1360),
    );
  }, [primary]);

  useEffect(() => {
    if (projectId && projectId !== "demo") {
      window.sessionStorage.setItem(LAST_PROJECT_STORAGE_KEY, projectId);
    }
  }, [projectId]);

  const rememberedProjectId =
    projectId ?? window.sessionStorage.getItem(LAST_PROJECT_STORAGE_KEY) ?? null;
  const navigationProjectId = projectId ?? (primary === "settings" ? rememberedProjectId : null);
  const project = useQuery({
    queryKey: queryKeys.project.detail(navigationProjectId ?? "none"),
    queryFn: () => fetchProject(navigationProjectId!),
    enabled: Boolean(navigationProjectId && navigationProjectId !== "demo"),
    retry: false,
  });
  const projectName =
    navigationProjectId === "demo"
      ? "演示项目"
      : (project.data?.name ?? (navigationProjectId ? "当前项目" : null));
  const creationTarget = rememberedProjectId ? `/projects/${rememberedProjectId}` : "/";
  const creationView = creationViewFromPath(pathname);

  return (
    <div
      className={`df-global-shell${secondaryOpen ? " secondary-open" : ""}`}
      data-testid="workstation-shell"
      data-primary-section={primary}
    >
      <aside className="df-primary-sidebar">
        <a href="/" className="df-primary-brand" aria-label="DramaForge 项目大厅">
          <Aperture size={23} aria-hidden="true" />
        </a>
        <nav aria-label="一级导航">
          <PrimaryLink active={primary === "projects"} label="项目" to="/" icon={FolderKanban} />
          {rememberedProjectId ? (
            <PrimaryLink
              active={primary === "creation"}
              label="创作"
              to={creationTarget}
              icon={Clapperboard}
            />
          ) : (
            <span className="df-primary-disabled" aria-label="创作" aria-disabled="true">
              <Clapperboard size={20} aria-hidden="true" />
              <span>创作</span>
            </span>
          )}
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
            {navigationProjectId ? (
              <a
                href={`/settings/projects/${navigationProjectId}`}
                className={primary === "settings" ? "active" : undefined}
                aria-current={primary === "settings" ? "page" : undefined}
                aria-label="设置"
              >
                <Settings size={20} aria-hidden="true" />
                <span>设置</span>
              </a>
            ) : (
              <Link
                to="/settings/account"
                className={primary === "settings" ? "active" : undefined}
                aria-current={primary === "settings" ? "page" : undefined}
                aria-label="设置"
              >
                <Settings size={20} aria-hidden="true" />
                <span>设置</span>
              </Link>
            )}
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
              <ContextLink active={!location.hash} label="全部项目" to="/" />
              <a
                href="/#recent-projects"
                className={location.hash === "#recent-projects" ? "active" : undefined}
              >
                最近打开
              </a>
              <a href="/#project-filters">空间筛选</a>
            </nav>
            <a className="df-context-primary-action" href="/?create=1">
              新建项目
            </a>
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
              <span>产品管理</span>
              <strong>设置</strong>
            </header>
            <nav aria-label="设置导航">
              <ContextLink
                active={pathname === "/settings/account"}
                label="账号与实例"
                to="/settings/account"
                icon={UserRound}
              />
              <ContextLink
                active={pathname === "/settings/workspaces"}
                label="工作空间管理"
                to="/settings/workspaces"
                icon={FolderKanban}
              />
              <ContextLink
                active={pathname === "/settings/models"}
                label="模型连接"
                to="/settings/models"
                icon={Wrench}
              />
              <ContextLink
                active={pathname === "/settings/defaults"}
                label="默认创作偏好"
                to="/settings/defaults"
                icon={SlidersHorizontal}
              />
              {navigationProjectId && (
                <a
                  href={`/settings/projects/${navigationProjectId}`}
                  className={pathname.startsWith("/settings/projects/") ? "active" : undefined}
                  aria-current={pathname.startsWith("/settings/projects/") ? "page" : undefined}
                >
                  <Clapperboard size={17} aria-hidden="true" />
                  <span>当前项目设置</span>
                </a>
              )}
            </nav>
          </>
        )}
      </aside>

      <div className="df-shell-content">{children}</div>
    </div>
  );
}
