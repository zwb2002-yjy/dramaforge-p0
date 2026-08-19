import { useState, type ReactNode } from "react";
import {
  Aperture,
  ChevronLeft,
  Clapperboard,
  FolderKanban,
  Menu,
  Settings,
} from "lucide-react";

import "./quick-creation-preview.css";

export function ProjectLobbyShell({
  apiLive,
  children,
}: {
  apiLive: boolean;
  children: ReactNode;
}) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  return (
    <div
      className={`qc-preview-shell qc-lobby-shell${sidebarExpanded ? " sidebar-expanded" : ""}`}
      data-testid="project-lobby-shell"
    >
      <aside className="qc-sidebar" aria-label="项目大厅导航">
        <div className="qc-sidebar-head">
          <div className="qc-brand">
            <Aperture size={22} aria-hidden="true" />
            <span>DramaForge</span>
          </div>
          <button
            type="button"
            className="qc-icon-button qc-sidebar-toggle"
            onClick={() => setSidebarExpanded((value) => !value)}
            aria-label={sidebarExpanded ? "收起导航" : "展开导航"}
            aria-expanded={sidebarExpanded}
          >
            {sidebarExpanded ? <ChevronLeft size={19} aria-hidden="true" /> : <Menu size={19} aria-hidden="true" />}
          </button>
        </div>
        <nav>
          <a href="#workspace" className="active" aria-current="page">
            <FolderKanban size={18} aria-hidden="true" />
            <span>项目大厅</span>
          </a>
          <a href="#projects">
            <Clapperboard size={18} aria-hidden="true" />
            <span>开始创作</span>
          </a>
        </nav>
        <div className="qc-sidebar-bottom">
          <a href="#provider-settings">
            <Settings size={18} aria-hidden="true" />
            <span>模型设置</span>
          </a>
        </div>
      </aside>

      <div className="qc-workspace">
        <header className="qc-project-bar">
          <span className="qc-project-name">DramaForge</span>
          <span className="qc-project-save">个人创作空间</span>
          <span className="qc-project-mode">单用户 · 私有部署</span>
          <span className={apiLive ? "qc-runtime-state ready" : "qc-runtime-state"}>
            {apiLive ? "服务就绪" : "服务未就绪"}
          </span>
        </header>
        <main className="qc-lobby-main" id="workspace">{children}</main>
      </div>
    </div>
  );
}
