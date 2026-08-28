import { useState, type ReactNode } from "react";
import {
  Aperture,
  ChevronLeft,
  Clapperboard,
  FolderKanban,
  CircleHelp,
  Gauge,
  Library,
  Menu,
  Settings,
  Sparkles,
} from "lucide-react";

import { StageStepper } from "./components";
import type { PreviewStage } from "./types";
import "../../components/workstation/project-shell.css";
import "./mock-preview.css";

type DirectorControls = {
  collapsed: boolean;
  toggle: () => void;
};

type QuickCreationShellProps = {
  projectName: string;
  stages: PreviewStage[];
  children: ReactNode;
  directorContent?: ReactNode;
  renderDirector?: (controls: DirectorControls) => ReactNode;
  projectHref?: string;
  overviewHref?: string | null;
  quickHref?: string;
  secondaryHref?: string;
  secondaryLabel?: string;
  settingsHref?: string;
  settingsLabel?: string;
  helpHref?: string | null;
  avatarText?: string;
  live?: boolean;
};

export function QuickCreationShell({
  projectName,
  stages,
  children,
  directorContent,
  renderDirector,
  projectHref = "/",
  overviewHref = null,
  quickHref = "#creative-stage",
  secondaryHref = "/design-preview",
  secondaryLabel = "素材库",
  settingsHref = "/design-preview",
  settingsLabel = "设置",
  helpHref = "/design-preview",
  avatarText = "林",
  live = false,
}: QuickCreationShellProps) {
  const [directorCollapsed, setDirectorCollapsed] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const toggleDirector = () => setDirectorCollapsed((value) => !value);

  return (
    <div
      className={`qc-preview-shell${sidebarExpanded ? " sidebar-expanded" : ""}${directorCollapsed ? " director-collapsed" : ""}${live ? " qc-live" : ""}`}
      data-testid={live ? "quick-creation-workspace" : "quick-creation-preview"}
    >
      <aside className="qc-sidebar" aria-label="快速创作导航">
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
            {sidebarExpanded ? (
              <ChevronLeft size={19} aria-hidden="true" />
            ) : (
              <Menu size={19} aria-hidden="true" />
            )}
          </button>
        </div>
        <nav>
          <a href={projectHref} aria-label="返回项目大厅">
            <FolderKanban size={18} aria-hidden="true" />
            <span>项目大厅</span>
          </a>
          {overviewHref && (
            <a href={overviewHref}>
              <Gauge size={18} aria-hidden="true" />
              <span>项目总览</span>
            </a>
          )}
          <a href={quickHref} className="active" aria-current="page">
            <Clapperboard size={18} aria-hidden="true" />
            <span>快速创作</span>
          </a>
          <a href={secondaryHref}>
            <Library size={18} aria-hidden="true" />
            <span>{secondaryLabel}</span>
          </a>
        </nav>
        <div className="qc-sidebar-bottom">
          <a href={settingsHref}>
            <Settings size={18} aria-hidden="true" />
            <span>{settingsLabel}</span>
          </a>
          {helpHref && (
            <a href={helpHref}>
              <CircleHelp size={18} aria-hidden="true" />
              <span>帮助</span>
            </a>
          )}
        </div>
      </aside>

      <div className="qc-workspace">
        <header className="qc-project-bar">
          <span className="qc-project-name">{projectName}</span>
          <span className="qc-project-save">{live ? "已连接项目事实" : "已保存"}</span>
          <span className="qc-project-mode">快速模式</span>
          <button type="button" className="qc-avatar" aria-label="账户菜单">
            {avatarText}
          </button>
        </header>

        <div className="qc-content-grid">
          <main className="qc-main-canvas">
            <StageStepper stages={stages} testId={live ? "director-stage-rail" : "stage-stepper"} />
            {children}
          </main>

          {renderDirector ? (
            renderDirector({ collapsed: directorCollapsed, toggle: toggleDirector })
          ) : (
            <aside
              className={`qc-director-panel${directorCollapsed ? " collapsed" : ""}`}
              data-testid="director-panel"
            >
              {directorCollapsed ? (
                <>
                  <button
                    type="button"
                    className="qc-icon-button"
                    onClick={toggleDirector}
                    aria-label="展开 AI 导演"
                  >
                    <ChevronLeft size={19} aria-hidden="true" />
                  </button>
                  <Sparkles size={19} aria-hidden="true" />
                  <span>AI 导演</span>
                </>
              ) : (
                <>
                  <header className="qc-director-header">
                    <span className="qc-director-mark">
                      <Sparkles size={17} aria-hidden="true" />
                    </span>
                    <span>
                      <strong>AI 导演</strong>
                      <small>当前项目事实</small>
                    </span>
                    <button
                      type="button"
                      className="qc-icon-button"
                      onClick={toggleDirector}
                      aria-label="收起 AI 导演"
                    >
                      <ChevronLeft size={19} aria-hidden="true" />
                    </button>
                  </header>
                  <div className="qc-live-director-content">{directorContent}</div>
                </>
              )}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
