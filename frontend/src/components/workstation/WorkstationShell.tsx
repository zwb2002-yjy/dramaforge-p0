import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";

import { artifactContentUrl, fetchHealth, fetchSnapshot } from "../../lib/api";
import { useUiStore } from "../../stores/uiStore";

type WorkstationShellProps = {
  children: ReactNode;
};

export function WorkstationShell({ children }: WorkstationShellProps) {
  const leftOpen = useUiStore((s) => s.leftNavOpen);
  const toggleLeft = useUiStore((s) => s.toggleLeftNav);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const projectMatch = pathname.match(/\/projects\/([^/]+)/);
  const projectId = projectMatch?.[1];
  const isRealProject = Boolean(projectId && projectId !== "demo");
  const onQuick = pathname.includes("/quick");
  const onProd = pathname.includes("/production");

  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
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

  return (
    <div className="workstation" data-testid="workstation-shell">
      <header className="workstation-topbar">
        <button type="button" className="ghost" onClick={toggleLeft} aria-label="切换导航">
          ☰
        </button>
        <Link to="/" className="brand">
          Drama<span>Forge</span>
        </Link>
        <div className="topbar-meta">
          <span>私有短剧生产台</span>
          {isRealProject && (
            <div className="topbar-mode" data-testid="mode-switch">
              <Link
                to="/projects/$projectId/quick"
                params={{ projectId: projectId! }}
                className={onQuick ? "active" : undefined}
              >
                快速
              </Link>
              <Link
                to="/projects/$projectId/production"
                params={{ projectId: projectId! }}
                className={onProd ? "active" : undefined}
              >
                专业
              </Link>
            </div>
          )}
        </div>
        <span
          className="env-badge"
          data-testid="env-badge"
          title={health.data?.db_error ?? ""}
          style={{ color: apiLive ? "var(--ok)" : "var(--danger)" }}
        >
          {apiLive ? "API · DB 就绪" : "API 未就绪"}
        </span>
      </header>
      <div className="workstation-body">
        <aside className={leftOpen ? "nav open" : "nav"} data-testid="workstation-nav">
          <div className="nav-section">入口</div>
          <nav>
            <Link to="/" className={pathname === "/" ? "active" : undefined}>
              项目大厅
            </Link>
            {isRealProject ? (
              <>
                <div className="nav-section">当前项目</div>
                <Link
                  to="/projects/$projectId/quick"
                  params={{ projectId: projectId! }}
                  className={onQuick ? "active" : undefined}
                >
                  快速创作
                </Link>
                <Link
                  to="/projects/$projectId/production"
                  params={{ projectId: projectId! }}
                  className={onProd ? "active" : undefined}
                >
                  专业生产板
                </Link>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: projectId! }}
                  className={
                    pathname.endsWith(projectId!) || pathname.endsWith(`${projectId}/`)
                      ? "active"
                      : undefined
                  }
                >
                  项目总览
                </Link>
              </>
            ) : (
              <>
                <div className="nav-section">提示</div>
                <p className="muted" style={{ padding: "0 0.7rem", fontSize: "0.78rem" }}>
                  创建正式项目后，快速与专业入口绑定同一 Project — 资产、Run、成本不分裂。
                </p>
              </>
            )}
          </nav>
        </aside>
        <main className="workstation-main">{children}</main>
        <aside className="inspector" data-testid="workstation-inspector">
          <h3>生产检查器</h3>
          {isRealProject ? (
            <>
              <div className="inspector-stat">
                <span>项目</span>
                <strong title={projectId}>{projectId!.slice(0, 8)}…</strong>
              </div>
              <div className="inspector-stat">
                <span>NodeRun 数</span>
                <strong data-testid="insp-runs">{runs.length}</strong>
              </div>
              <div className="inspector-stat">
                <span>完成</span>
                <strong className="status-ok">{done}</strong>
              </div>
              <div className="inspector-stat">
                <span>进行中</span>
                <strong className="status-pending">{active}</strong>
              </div>
              <div className="inspector-stat">
                <span>失败</span>
                <strong className={failed ? "status-bad" : ""}>{failed}</strong>
              </div>
              <div className="inspector-stat">
                <span>产物数</span>
                <strong data-testid="insp-arts">{arts.length}</strong>
              </div>
              {snapshot.data?.name && (
                <p className="muted" style={{ marginTop: "0.75rem" }}>
                  {snapshot.data.name}
                </p>
              )}
              {projectId && arts[0] && (
                <div style={{ marginTop: "0.75rem" }}>
                  <h3>最近产物</h3>
                  <a
                    href={artifactContentUrl(projectId, arts[0].id)}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: "0.78rem", wordBreak: "break-all" }}
                  >
                    {arts[0].object_key.split("/").slice(-2).join("/")}
                  </a>
                </div>
              )}
            </>
          ) : (
            <p>
              行业台（LibTV / Jellyfish / Toonflow / ArcReel）共通：分镜可视、状态清楚、结果可回看。
              DramaForge 在此加 Production Graph、一致性门禁与审计。
            </p>
          )}
          <div style={{ marginTop: "0.85rem" }}>
            <span className="pill">Brief/Plan</span>
            <span className="pill">Canonical</span>
            <span className="pill">shot-p0-v1</span>
            <span className="pill">Audit</span>
          </div>
          <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.75rem" }}>
            假 Adapter 仅 pytest；不得作为 §3.1 验收主路径。
          </p>
        </aside>
      </div>
    </div>
  );
}
