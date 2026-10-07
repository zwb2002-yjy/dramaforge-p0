import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import type { ProjectWorkspaceView } from "./ProjectWorkspaceShell";
import "./project-stage-guide.css";

/** The one suggested next step per project view; navigation lives in the shell. */
const NEXT_STEP: Partial<
  Record<
    ProjectWorkspaceView,
    {
      label: string;
      to:
        | "/projects/$projectId/assets"
        | "/projects/$projectId/scenes"
        | "/projects/$projectId/review"
        | "/projects/$projectId/edit"
        | "/projects/$projectId/production";
    }
  >
> = {
  script: { label: "准备角色素材", to: "/projects/$projectId/assets" },
  assets: { label: "进入分镜与生成", to: "/projects/$projectId/scenes" },
  scenes: { label: "进入审片确认", to: "/projects/$projectId/review" },
  review: { label: "进入剪辑成片", to: "/projects/$projectId/edit" },
  edit: { label: "返回作品总览", to: "/projects/$projectId/production" },
};

export function ProjectStageGuide({
  projectId,
  view,
}: {
  projectId: string;
  view: ProjectWorkspaceView;
}) {
  const next = NEXT_STEP[view];
  if (!next) return null;
  return (
    <Link
      className="project-stage-next"
      data-testid="project-stage-guide"
      to={next.to}
      params={{ projectId }}
    >
      <span className="project-stage-next-kicker">下一步</span>
      {next.label}
      <ArrowRight size={14} aria-hidden="true" />
    </Link>
  );
}
