import type { ReactNode } from "react";
import { ProjectStageGuide } from "./ProjectStageGuide";

import "./project-shell.css";
import "./project-shell-visual.css";
import "./creation-controls.css";

export type ProjectWorkspaceView =
  "overview" | "script" | "assets" | "scenes" | "production" | "review" | "edit";

type ProjectWorkspaceShellProps = {
  projectId: string;
  projectName: string;
  activeView: ProjectWorkspaceView;
  children: ReactNode;
  modeLabel?: string;
  creationControls?: ReactNode;
};

const VIEW_LABELS: Record<ProjectWorkspaceView, string> = {
  overview: "场景总览",
  script: "故事剧本",
  assets: "角色素材",
  scenes: "分镜制作",
  production: "作品总览",
  review: "审片确认",
  edit: "剪辑成片",
};

export function ProjectWorkspaceShell({
  projectId,
  projectName,
  activeView,
  children,
  modeLabel,
  creationControls,
}: ProjectWorkspaceShellProps) {
  const displayModeLabel = modeLabel ?? VIEW_LABELS[activeView];

  return (
    <div
      className={`qc-project-shell${activeView === "scenes" ? " scene-view" : ""}`}
      data-testid="project-workspace-shell"
      data-project-id={projectId}
    >
      <header className="qc-project-bar">
        <span className="qc-project-name">{projectName}</span>
        <span className="qc-project-mode">{displayModeLabel}</span>
        {creationControls}
      </header>

      <div className="qc-content-grid no-inspector">
        <main className="qc-main-canvas qc-project-canvas">
          <ProjectStageGuide projectId={projectId} view={activeView} />
          {children}
        </main>
      </div>
    </div>
  );
}
