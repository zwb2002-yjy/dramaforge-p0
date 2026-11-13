import { useContext, useLayoutEffect, useRef, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { Button } from "../ui";
import { ProjectStageGuide } from "./ProjectStageGuide";
import { ProjectNavigationContext, PROJECT_VIEW_LABELS } from "./projectNavigation";

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
  overview: "项目总览",
  ...PROJECT_VIEW_LABELS,
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
  const navigation = useContext(ProjectNavigationContext);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const bar = barRef.current;
    const shell = shellRef.current;
    if (!bar || !shell) return;

    // The measured height is consumed by sticky children, never by the bar itself:
    // feeding it back into min-height would prevent the bar from shrinking.
    let measuredHeight = 0;
    const syncTopbarHeight = () => {
      const height = Math.ceil(bar.getBoundingClientRect().height);
      if (height > 0 && height !== measuredHeight) {
        measuredHeight = height;
        shell.style.setProperty("--df-project-topbar-height", `${height}px`);
      }
    };

    syncTopbarHeight();
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(syncTopbarHeight);
    observer?.observe(bar);

    return () => {
      observer?.disconnect();
      shell.style.removeProperty("--df-project-topbar-height");
    };
  }, []);

  return (
    <div
      ref={shellRef}
      className={`qc-project-shell${activeView === "scenes" ? " scene-view" : ""}`}
      data-testid="project-workspace-shell"
      data-project-id={projectId}
    >
      <header ref={barRef} className="qc-project-bar">
        {navigation && (
          <Button
            ref={navigation.triggerRef}
            tone="ghost"
            aria-controls="project-navigation"
            aria-expanded={navigation.open}
            data-testid="project-navigation-toggle"
            onClick={navigation.toggle}
          >
            <Menu size={17} aria-hidden="true" />
            项目导航
          </Button>
        )}
        <span className="qc-project-name">{projectName}</span>
        <span className="qc-project-mode">{displayModeLabel}</span>
        <ProjectStageGuide projectId={projectId} view={activeView} />
        {creationControls}
      </header>

      <div className="qc-content-grid no-inspector">
        <main className="qc-main-canvas qc-project-canvas">{children}</main>
      </div>
    </div>
  );
}
