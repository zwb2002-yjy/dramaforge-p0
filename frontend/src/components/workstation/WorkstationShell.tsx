import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";

import { artifactContentUrl, fetchHealth, fetchSnapshot } from "../../lib/api";
import { useUiStore } from "../../stores/uiStore";
import { AppShell, AppShellBody, Sidebar, TopBar } from "../shell";

type WorkstationShellProps = {
  children: ReactNode;
};

export function WorkstationShell({ children }: WorkstationShellProps) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (
    pathname === "/" ||
    pathname.startsWith("/projects/") ||
    pathname === "/design-preview/product"
  ) {
    return <>{children}</>;
  }
  return <LegacyWorkstationShell pathname={pathname}>{children}</LegacyWorkstationShell>;
}

function LegacyWorkstationShell({
  children,
  pathname,
}: WorkstationShellProps & { pathname: string }) {
  const leftOpen = useUiStore((s) => s.leftNavOpen);
  const toggleLeft = useUiStore((s) => s.toggleLeftNav);
  const setLeftOpen = useUiStore((s) => s.setLeftNavOpen);
  const projectMatch = pathname.match(/\/projects\/([^/]+)/);
  const projectId = projectMatch?.[1];
  const isRealProject = Boolean(projectId && projectId !== "demo");
  const onQuick = pathname.includes("/quick");
  const onProd = pathname.includes("/production");
  const isDesignPreview = pathname.startsWith("/design-preview");
  const showInspector = isRealProject;

  useEffect(() => {
    if (window.matchMedia?.("(max-width: 1100px)").matches) {
      setLeftOpen(false);
    }
  }, [setLeftOpen]);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    enabled: !isDesignPreview && pathname !== "/",
    refetchInterval: 10_000,
    retry: 1,
  });

  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId!),
    enabled: isRealProject,
    refetchInterval: 4000,
  });

  const runs = snapshot.data?.node_runs ?? [];
  const arts = snapshot.data?.artifacts ?? [];
  const done = runs.filter((r) =>
    ["completed", "cached", "completed_after_cancel"].includes(r.status),
  ).length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const active = runs.filter((r) => ["queued", "running"].includes(r.status)).length;

  const dbUp = health.data?.db === "up" || (health.data?.status === "ok" && !health.data?.db);
  const apiLive = !!health.data && !health.isError && health.data.status === "ok" && dbUp !== false;

  const inspector = showInspector ? (
    <aside className="df-inspector inspector" data-testid="workstation-inspector">
      <h3>生产检查器</h3>
      <div className="df-inspector-stat inspector-stat">
        <span>项目</span>
        <strong title={projectId}>{projectId!.slice(0, 8)}…</strong>
      </div>
      <div className="df-inspector-stat inspector-stat">
        <span>NodeRun 数</span>
        <strong data-testid="insp-runs">{runs.length}</strong>
      </div>
      <div className="df-inspector-stat inspector-stat">
        <span>完成</span>
        <strong className="df-status-ok status-ok">{done}</strong>
      </div>
      <div className="df-inspector-stat inspector-stat">
        <span>进行中</span>
        <strong className="df-status-pending status-pending">{active}</strong>
      </div>
      <div className="df-inspector-stat inspector-stat">
        <span>失败</span>
        <strong className={failed ? "df-status-bad status-bad" : ""}>{failed}</strong>
      </div>
      <div className="df-inspector-stat inspector-stat">
        <span>产物数</span>
        <strong data-testid="insp-arts">{arts.length}</strong>
      </div>
      {snapshot.data?.name && (
        <p className="muted" style={{ marginTop: "var(--df-space-3)" }}>
          {snapshot.data.name}
        </p>
      )}
      {projectId && arts[0] && (
        <div style={{ marginTop: "var(--df-space-3)" }}>
          <h3>最近产物</h3>
          <a
            href={artifactContentUrl(projectId, arts[0].id)}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: "var(--df-text-sm)", wordBreak: "break-all" }}
          >
            {arts[0].object_key.split("/").slice(-2).join("/")}
          </a>
        </div>
      )}
      <div style={{ marginTop: "var(--df-space-3)" }}>
        <span className="df-pill pill">四阶段导演流程</span>
        <span className="df-pill pill">角色视觉锚点</span>
        <span className="df-pill pill">局部修复</span>
        <span className="df-pill pill">质量证据</span>
      </div>
    </aside>
  ) : undefined;

  return (
    <AppShell data-testid="workstation-shell">
      <TopBar>
        <button
          type="button"
          className="df-btn ghost nav-toggle"
          onClick={toggleLeft}
          aria-label={leftOpen ? "收起导航" : "展开导航"}
          aria-expanded={leftOpen}
          aria-controls="workstation-navigation"
        >
          ☰
        </button>
        <Link to="/" className="df-topbar-brand brand">
          Drama<span className="df-topbar-accent">Forge</span>
        </Link>
        <div className="df-topbar-meta topbar-meta">
          <span>私有短剧生产台</span>
          {isRealProject && (
            <div className="df-tabs topbar-mode" data-testid="mode-switch">
              <Link
                to="/projects/$projectId/quick"
                params={{ projectId: projectId! }}
                className={`df-tab ${onQuick ? "active" : ""}`}
              >
                快速
              </Link>
              <Link
                to="/projects/$projectId/production"
                params={{ projectId: projectId! }}
                className={`df-tab ${onProd ? "active" : ""}`}
              >
                专业
              </Link>
            </div>
          )}
        </div>
        {!isDesignPreview && (
          <span
            className="df-badge env-badge"
            data-testid="env-badge"
            title={health.data?.db_error ?? ""}
            style={{ color: apiLive ? "var(--df-success)" : "var(--df-danger)" }}
          >
            {apiLive ? "API · DB 就绪" : "API 未就绪"}
          </span>
        )}
      </TopBar>
      <AppShellBody navigationOpen={leftOpen} inspector={inspector}>
        <Sidebar id="workstation-navigation" data-testid="workstation-nav" open={leftOpen}>
          <div className="df-sidebar-section nav-section">入口</div>
          <nav className="df-sidebar-nav">
            <Link to="/" className={`df-sidebar-link ${pathname === "/" ? "active" : ""}`}>
              项目大厅
            </Link>
            {isRealProject ? (
              <>
                <div className="df-sidebar-section nav-section">当前项目</div>
                <Link
                  to="/projects/$projectId/quick"
                  params={{ projectId: projectId! }}
                  className={`df-sidebar-link ${onQuick ? "active" : ""}`}
                >
                  快速创作
                </Link>
                <Link
                  to="/projects/$projectId/production"
                  params={{ projectId: projectId! }}
                  className={`df-sidebar-link ${onProd ? "active" : ""}`}
                >
                  专业生产板
                </Link>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: projectId! }}
                  className={`df-sidebar-link ${
                    pathname.endsWith(projectId!) || pathname.endsWith(`${projectId}/`)
                      ? "active"
                      : ""
                  }`}
                >
                  项目总览
                </Link>
              </>
            ) : (
              <>
                <div className="df-sidebar-section nav-section">提示</div>
                <p className="df-sidebar-hint muted">
                  创建正式项目后，快速与专业入口绑定同一 Project — 资产、Run、成本不分裂。
                </p>
              </>
            )}
          </nav>
        </Sidebar>
        {leftOpen && (
          <button
            type="button"
            className="df-sidebar-scrim nav-scrim"
            aria-label="关闭导航"
            onClick={() => setLeftOpen(false)}
          />
        )}
        <main className="workstation-main">{children}</main>
      </AppShellBody>
    </AppShell>
  );
}
