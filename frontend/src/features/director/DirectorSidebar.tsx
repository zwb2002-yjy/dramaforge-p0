import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import {
  AssetReferencePicker,
  type ReferenceResolutionState,
} from "../../components/assets/AssetReferencePicker";
import { ShotDesignPanel } from "../shots/ShotDesignPanel";
import { ShotDirectorSuggestionPanel } from "./ShotDirectorSuggestionPanel";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import { ShotFormalOutputActions } from "../shots/ShotFormalOutputActions";
import { ShotProductionActions } from "../shots/ShotProductionActions";
import { ShotProductionTrace } from "../shots/ShotProductionTrace";
import type { ShotExecutionReference, ShotLite } from "../shots/api";

type DirectorSidebarProps = {
  projectId: string;
  shot: ShotLite | null;
  candidates: unknown[];
  trace: unknown[];
  references: ShotExecutionReference[];
  referencesReady: boolean;
  onReferencesChange: (references: ShotExecutionReference[]) => void;
  onResolutionStateChange: (state: ReferenceResolutionState) => void;
  onWorkspaceRefresh?: () => void | Promise<void>;
};

/**
 * The selected-shot director surface.
 *
 * This component is intentionally a composition layer.  Design, references,
 * production, formal selection, and trace remain owned by their existing
 * feature components and APIs; the sidebar only gives them one shot identity
 * and one visual home.
 */
export function DirectorSidebar({
  projectId,
  shot,
  candidates,
  trace,
  references,
  referencesReady,
  onReferencesChange,
  onResolutionStateChange,
  onWorkspaceRefresh,
}: DirectorSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [designDirty, setDesignDirty] = useState(false);
  const [suggestionDraft, setSuggestionDraft] = useState<ShotDesignDraft | null>(null);

  // The panel is keyed by Shot identity, but the sidebar itself is not. Reset
  // the sibling production guard whenever selection changes so Shot A's draft
  // can never block or authorize Shot B.
  useEffect(() => {
    setDesignDirty(false);
    setSuggestionDraft(null);
  }, [shot?.id]);

  const applySuggestionDraft = useCallback((draft: ShotDesignDraft) => {
    // This is intentionally a local editor hand-off. ShotDesignPanel owns the
    // draft and its existing explicit save mutation remains the only write.
    setSuggestionDraft({
      image_prompt: draft.image_prompt,
      video_prompt: draft.video_prompt,
      director_state: { ...draft.director_state },
    });
  }, []);

  const handleDesignSaved = useCallback(async () => {
    setSuggestionDraft(null);
    await onWorkspaceRefresh?.();
  }, [onWorkspaceRefresh]);

  return (
    <aside
      className={`qc-director-sidebar${collapsed ? " is-collapsed" : ""}`}
      data-testid="director-sidebar"
      data-shot-id={shot?.id ?? undefined}
      aria-label="导演侧栏"
    >
      <header className="qc-director-sidebar-header">
        <div>
          <span className="director-stage-kicker">当前镜头</span>
          <strong>{shot ? `#${shot.shot_number} 导演侧栏` : "导演侧栏"}</strong>
        </div>
        <button
          type="button"
          className="qc-icon-button"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "展开导演侧栏" : "收起导演侧栏"}
          aria-expanded={!collapsed}
          aria-controls="director-sidebar-content"
        >
          {collapsed ? (
            <ChevronRight size={18} aria-hidden="true" />
          ) : (
            <ChevronLeft size={18} aria-hidden="true" />
          )}
        </button>
      </header>

      {!collapsed && (
        <div id="director-sidebar-content" className="qc-director-sidebar-content">
          <section
            className="qc-director-sidebar-section"
            data-testid="director-section-design"
            aria-labelledby="director-section-design-title"
          >
            <h2 id="director-section-design-title">镜头设计</h2>
            {shot ? (
              <ShotDesignPanel
                key={`design:${shot.id}`}
                projectId={projectId}
                shot={shot}
                applyDraft={suggestionDraft}
                onSaved={handleDesignSaved}
                onDirtyChange={setDesignDirty}
              />
            ) : (
              <p className="muted">选择一个镜头查看设计。</p>
            )}
            {shot ? (
              <ShotDirectorSuggestionPanel
                key={`suggestion:${shot.id}`}
                projectId={projectId}
                shot={shot}
                dirty={designDirty}
                onApplyDraft={applySuggestionDraft}
              />
            ) : null}
          </section>

          <section
            className="qc-director-sidebar-section"
            data-testid="director-section-references"
            aria-labelledby="director-section-references-title"
          >
            <h2 id="director-section-references-title">参考素材</h2>
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

          <section
            className="qc-director-sidebar-section"
            data-testid="director-section-production"
            aria-labelledby="director-section-production-title"
          >
            <h2 id="director-section-production-title">生产</h2>
            {shot ? (
              <ShotProductionActions
                key={`production:${shot.id}`}
                projectId={projectId}
                shot={shot}
                references={references}
                referencesReady={referencesReady}
                dirty={designDirty}
                onExecuted={onWorkspaceRefresh}
              />
            ) : (
              <p className="muted">选择一个镜头开始受控生产。</p>
            )}
          </section>

          <section
            className="qc-director-sidebar-section"
            data-testid="director-section-output"
            aria-labelledby="director-section-output-title"
          >
            <h2 id="director-section-output-title">执行状态 / 正式结果</h2>
            {shot ? (
              <>
                <ShotFormalOutputActions
                  key={`formal:${shot.id}`}
                  projectId={projectId}
                  shot={shot}
                  candidates={candidates}
                  onConfirmed={onWorkspaceRefresh}
                />
                <ShotProductionTrace shotId={shot.id} trace={trace} />
              </>
            ) : (
              <p className="muted">选择一个镜头查看执行状态与正式结果。</p>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}
