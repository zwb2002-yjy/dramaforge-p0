import {
  Aperture,
  Camera,
  Clapperboard,
  Info,
  Layers,
  MoveUpRight,
  Sparkles,
  Users,
} from "lucide-react";

import { Tab, Tabs } from "../../components/ui";

export type ContextTool =
  "prompts" | "character" | "camera" | "motion" | "look" | "generate" | "director";

type ContextDockProps = {
  activeTool: ContextTool | null;
  candidateCount: number;
  trayExpanded: boolean;
  detailsOpen: boolean;
  hasShot: boolean;
  onSelectTool: (tool: ContextTool) => void;
  onToggleTray: () => void;
  onToggleDetails: () => void;
};

const TOOLS: Array<{
  id: ContextTool;
  label: string;
  testId: string;
}> = [
  { id: "prompts", label: "提示词", testId: "context-dock-prompts" },
  { id: "character", label: "角色", testId: "context-dock-character" },
  { id: "camera", label: "机位", testId: "context-dock-camera" },
  { id: "motion", label: "运动", testId: "context-dock-motion" },
  { id: "look", label: "画面", testId: "context-dock-look" },
  { id: "generate", label: "生成", testId: "context-dock-generate" },
  { id: "director", label: "导演", testId: "context-dock-director" },
];

const TOOL_ICONS = {
  prompts: Info,
  character: Users,
  camera: Camera,
  motion: MoveUpRight,
  look: Aperture,
  generate: Clapperboard,
  director: Sparkles,
};

/**
 * V2 Canvas-first Context Dock (UI-1).
 *
 * One quiet strip under the Canvas exposing the current Shot's director
 * dimensions. Opening a tool floats the Context Sheet over the Canvas; at
 * most one tool surface is open at a time. The dock itself is pure UI state —
 * production facts still come from the SceneWorkspace read.
 */
export function ContextDock({
  activeTool,
  candidateCount,
  trayExpanded,
  detailsOpen,
  hasShot,
  onSelectTool,
  onToggleTray,
  onToggleDetails,
}: ContextDockProps) {
  return (
    <nav className="qc-context-dock" data-testid="context-dock" aria-label="当前镜头操作">
      <Tabs label="镜头操作工具" className="qc-context-dock-tabs">
        {TOOLS.map((tool, index) => {
          const active = activeTool === tool.id;
          const Icon = TOOL_ICONS[tool.id];
          return (
            <Tab
              key={tool.id}
              id={`context-tool-${tool.id}`}
              active={active}
              tabIndex={active || (activeTool === null && index === 0) ? 0 : -1}
              data-testid={tool.testId}
              aria-controls="shot-context-sheet"
              disabled={!hasShot}
              onClick={() => onSelectTool(tool.id)}
            >
              <Icon size={17} aria-hidden="true" />
              {tool.label}
            </Tab>
          );
        })}
      </Tabs>
      <span className="qc-context-dock-divider" aria-hidden="true" />
      <button
        type="button"
        className={trayExpanded ? "active" : undefined}
        data-testid="context-dock-takes"
        aria-expanded={trayExpanded}
        disabled={!hasShot}
        onClick={onToggleTray}
      >
        <Layers size={17} aria-hidden="true" />
        备选画面 · {candidateCount}
      </button>
      <button
        type="button"
        className={detailsOpen ? "active" : undefined}
        data-testid="context-dock-details"
        aria-expanded={detailsOpen}
        disabled={!hasShot}
        onClick={onToggleDetails}
      >
        <Info size={17} aria-hidden="true" />
        详情
      </button>
    </nav>
  );
}
