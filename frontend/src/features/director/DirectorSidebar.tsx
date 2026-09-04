import { useEffect, useState } from "react";
import { X } from "lucide-react";

import {
  AssetReferencePicker,
  type ReferenceResolutionState,
} from "../../components/assets/AssetReferencePicker";
import { ShotDesignPanel } from "../shots/ShotDesignPanel";
import { ShotProductionActions } from "../shots/ShotProductionActions";
import { ShotProductionTrace } from "../shots/ShotProductionTrace";
import type { ShotExecutionReference, ShotLite } from "../shots/api";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import { ShotDirectorSuggestionPanel } from "./ShotDirectorSuggestionPanel";

export type DirectorTab = "shot" | "references" | "production";

type DirectorSidebarProps = {
  projectId: string;
  shot: ShotLite | null;
  trace: unknown[];
  references: ShotExecutionReference[];
  referencesReady: boolean;
  onReferencesChange: (references: ShotExecutionReference[]) => void;
  onResolutionStateChange: (state: ReferenceResolutionState) => void;
  onWorkspaceRefresh?: () => void | Promise<void>;
  /**
   * V2 Canvas-first (UI-1): the panel is a floating Context Sheet. SceneWorkspace
   * owns visibility and the requested tab; closing restores the full Canvas.
   */
  open?: boolean;
  requestedTab?: DirectorTab;
  onClose?: () => void;
  /** Shared draft state lives in SceneWorkspace so a sheet close keeps it. */
  designDirty?: boolean;
  onDesignDirtyChange?: (dirty: boolean) => void;
  suggestionDraft?: ShotDesignDraft | null;
  onApplySuggestionDraft?: (draft: ShotDesignDraft | null) => void;
  onDesignSaved?: () => void | Promise<void>;
};

const TABS: Array<{ id: DirectorTab; label: string; testId: string }> = [
  { id: "shot", label: "镜头", testId: "director-tab-shot" },
  { id: "references", label: "参考", testId: "director-tab-references" },
  { id: "production", label: "生成", testId: "director-tab-production" },
];

/**
 * Selected-Shot operation panel. Tabs are local UI state only: the canonical
 * SceneWorkspace snapshot remains the single source for Shot, reference,
 * production and trace facts. Since V2 UI-1 the panel is a Context Sheet that
 * floats over the Canvas and opens on demand instead of a permanent column.
 */
export function DirectorSidebar({
  projectId,
  shot,
  trace,
  references,
  referencesReady,
  onReferencesChange,
  onResolutionStateChange,
  onWorkspaceRefresh,
  open = true,
  requestedTab = "shot",
  onClose,
  designDirty,
  onDesignDirtyChange,
  suggestionDraft,
  onApplySuggestionDraft,
  onDesignSaved,
}: DirectorSidebarProps) {
  const [activeTab, setActiveTab] = useState<DirectorTab>(requestedTab);
  const [localDirty, setLocalDirty] = useState(false);
  const [localDraft, setLocalDraft] = useState<ShotDesignDraft | null>(null);

  const dirty = designDirty ?? localDirty;
  const draft = suggestionDraft ?? localDraft;
  const reportDirty = onDesignDirtyChange ?? setLocalDirty;
  const applyDraft =
    onApplySuggestionDraft ??
    ((next: ShotDesignDraft) =>
      setLocalDraft({
        image_prompt: next.image_prompt,
        video_prompt: next.video_prompt,
        director_state: { ...next.director_state },
      }));
  const handleDesignSaved = onDesignSaved ?? onWorkspaceRefresh;

  useEffect(() => {
    setActiveTab(requestedTab);
  }, [requestedTab]);

  // The panel is keyed by Shot identity, but the shell is not. Reset the
  // sibling production guard whenever selection changes so Shot A's draft can
  // never block or authorize Shot B.
  useEffect(() => {
    if (designDirty === undefined) setLocalDirty(false);
    if (suggestionDraft === undefined) setLocalDraft(null);
  }, [shot?.id, designDirty, suggestionDraft]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const clearSuggestionDraft = () => {
    if (onApplySuggestionDraft) {
      onApplySuggestionDraft(null);
      return;
    }
    setLocalDraft(null);
  };

  const handleSaved = async () => {
    clearSuggestionDraft();
    await handleDesignSaved?.();
  };

  const renderShotTab = () => (
    <section className="qc-director-sidebar-section" data-testid="director-section-design">
      {shot ? (
        <>
          <ShotDesignPanel
            key={`design:${shot.id}`}
            projectId={projectId}
            shot={shot}
            applyDraft={draft}
            onSaved={handleSaved}
            onDirtyChange={reportDirty}
          />
          <div className="qc-director-suggestion" data-testid="director-section-suggestion">
            <ShotDirectorSuggestionPanel
              key={`suggestion:${shot.id}`}
              projectId={projectId}
              shot={shot}
              dirty={dirty}
              onApplyDraft={applyDraft}
            />
          </div>
        </>
      ) : (
        <p className="muted">选择一个镜头查看设计。</p>
      )}
    </section>
  );

  const renderReferencesTab = () => (
    <section className="qc-director-sidebar-section" data-testid="director-section-references">
      {shot ? (
        <AssetReferencePicker
          key={`references:${shot.id}`}
          projectId={projectId}
          shotId={shot.id}
          onReferencesChange={onReferencesChange}
          onResolutionStateChange={onResolutionStateChange}
        />
      ) : (
        <p className="muted">选择一个镜头管理参考素材。</p>
      )}
    </section>
  );

  const renderProductionTab = () => (
    <section className="qc-director-sidebar-section" data-testid="director-section-production">
      {shot ? (
        <>
          <ShotProductionActions
            key={`production:${shot.id}`}
            projectId={projectId}
            shot={shot}
            references={references}
            referencesReady={referencesReady}
            dirty={dirty}
            onExecuted={onWorkspaceRefresh}
          />
          <ShotProductionTrace shotId={shot.id} trace={trace} />
        </>
      ) : (
        <p className="muted">选择一个镜头开始受控生产。</p>
      )}
    </section>
  );

  return (
    <aside
      className="qc-director-sidebar qc-director-context-sheet"
      data-testid="director-sidebar"
      data-operation-panel="director-operation-panel"
      data-shot-id={shot?.id ?? undefined}
      role="dialog"
      aria-modal="false"
      aria-label="镜头操作面板"
    >
      <header className="qc-director-sidebar-header">
        <div>
          <span className="director-stage-kicker">当前镜头</span>
          <strong>{shot ? `#${shot.shot_number} 镜头操作` : "镜头操作"}</strong>
        </div>
        <button
          type="button"
          className="qc-icon-button"
          onClick={onClose}
          aria-label="关闭操作面板"
          data-testid="director-sheet-close"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>

      <div id="director-sidebar-content" className="qc-director-sidebar-content">
        <div className="qc-director-tabs" role="tablist" aria-label="镜头操作 tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={tab.testId}
              data-testid={tab.testId}
              aria-selected={activeTab === tab.id}
              aria-controls={`director-panel-${tab.id}`}
              className={activeTab === tab.id ? "active" : undefined}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div
          id={`director-panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`director-tab-${activeTab}`}
          className="qc-director-tab-panel"
        >
          {activeTab === "shot"
            ? renderShotTab()
            : activeTab === "references"
              ? renderReferencesTab()
              : renderProductionTab()}
        </div>
      </div>
    </aside>
  );
}
