import { createContext, type RefCallback } from "react";
import type { WorkspaceView } from "../../hooks/useProjectWorkspaceState";

export const PROJECT_VIEW_LABELS: Record<WorkspaceView, string> = {
  production: "项目总览",
  script: "故事剧本",
  assets: "角色与素材",
  scenes: "分镜制作",
  review: "审片确认",
  edit: "剪辑成片",
};

/** The existing shell owns navigation visibility; the project bar is its trigger. */
export const ProjectNavigationContext = createContext<{
  open: boolean;
  toggle: () => void;
  triggerRef: RefCallback<HTMLButtonElement>;
} | null>(null);
