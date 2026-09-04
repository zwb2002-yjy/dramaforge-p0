export type ContextTool = "character" | "camera" | "motion" | "look" | "generate" | "director";

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
  { id: "character", label: "角色", testId: "context-dock-character" },
  { id: "camera", label: "机位", testId: "context-dock-camera" },
  { id: "motion", label: "运动", testId: "context-dock-motion" },
  { id: "look", label: "画面", testId: "context-dock-look" },
  { id: "generate", label: "生成", testId: "context-dock-generate" },
  { id: "director", label: "导演", testId: "context-dock-director" },
];

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
      {TOOLS.map((tool) => {
        const active = activeTool === tool.id;
        return (
          <button
            key={tool.id}
            type="button"
            className={active ? "active" : undefined}
            data-testid={tool.testId}
            aria-pressed={active}
            disabled={!hasShot}
            onClick={() => onSelectTool(tool.id)}
          >
            {tool.label}
          </button>
        );
      })}
      <span className="qc-context-dock-divider" aria-hidden="true" />
      <button
        type="button"
        className={trayExpanded ? "active" : undefined}
        data-testid="context-dock-takes"
        aria-expanded={trayExpanded}
        disabled={!hasShot}
        onClick={onToggleTray}
      >
        Takes · {candidateCount}
      </button>
      <button
        type="button"
        className={detailsOpen ? "active" : undefined}
        data-testid="context-dock-details"
        aria-expanded={detailsOpen}
        disabled={!hasShot}
        onClick={onToggleDetails}
      >
        详情
      </button>
    </nav>
  );
}
