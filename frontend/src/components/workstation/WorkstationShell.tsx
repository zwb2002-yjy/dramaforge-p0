import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { useUiStore } from "../../stores/uiStore";

type WorkstationShellProps = {
  children: ReactNode;
};

export function WorkstationShell({ children }: WorkstationShellProps) {
  const leftOpen = useUiStore((s) => s.leftNavOpen);
  const toggleLeft = useUiStore((s) => s.toggleLeftNav);

  return (
    <div className="workstation" data-testid="workstation-shell">
      <header className="workstation-topbar">
        <button type="button" onClick={toggleLeft} aria-label="Toggle navigation">
          ☰
        </button>
        <Link to="/" className="brand">
          DramaForge
        </Link>
        <span className="env-badge">BOOT-0</span>
      </header>
      <div className="workstation-body">
        <aside className={leftOpen ? "nav open" : "nav"} data-testid="workstation-nav">
          <nav>
            <Link to="/">首页</Link>
            <Link to="/projects/$projectId" params={{ projectId: "demo" }}>
              演示项目
            </Link>
            <Link to="/projects/$projectId/quick" params={{ projectId: "demo" }}>
              快速模式
            </Link>
            <Link to="/projects/$projectId/production" params={{ projectId: "demo" }}>
              专业生产
            </Link>
          </nav>
        </aside>
        <main className="workstation-main">{children}</main>
        <aside className="inspector" data-testid="workstation-inspector">
          <h3>检查器</h3>
          <p>任务状态与 Artifact 见项目快照 API；快速/专业共用 Project。</p>
        </aside>
      </div>
    </div>
  );
}
