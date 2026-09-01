import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

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

type DirectorTab = "shot" | "references" | "production";

type DirectorSidebarProps = {
  projectId: string;
  shot: ShotLite | null;
  trace: unknown[];
  references: ShotExecutionReference[];
  referencesReady: boolean;
  onReferencesChange: (references: ShotExecutionReference[]) => void;
  onResolutionStateChange: (state: ReferenceResolutionState) => void;
  onWorkspaceRefresh?: () => void | Promise<void>;
};

const TABS: Array<{ id: DirectorTab; label: string; testId: string }> = [
  { id: "shot", label: "镜头", testId: "director-tab-shot" },
  { id: "references", label: "参考", testId: "director-tab-references" },
  { id: "production", label: "生成", testId: "director-tab-production" },
];

/**
 * Compact selected-Shot operation panel. Tabs are local UI state only: the
 * canonical SceneWorkspace snapshot remains the single source for Shot,
 * reference, production and trace facts.
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
}: DirectorSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<DirectorTab>("shot");
  const [designDirty, setDesignDirty] = useState(false);
  const [suggestionDraft, setSuggestionDraft] = useState<ShotDesignDraft | null>(null);

  // The panel is keyed by Shot identity, but the shell is not. Reset the
  // sibling production guard whenever selection changes so Shot A's draft can
  // never block or authorize Shot B.
  useEffect(() => {
    setDesignDirty(false);
    setSuggestionDraft(null);
  }, [shot?.id]);

  const applySuggestionDraft = useCallback((draft: ShotDesignDraft) => {
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

  const renderShotTab = () => (
    <section className="qc-director-sidebar-section" data-testid="director-section-design">
      {shot ? (
        <>
          <ShotDesignPanel
            key={`design:${shot.id}`}
            projectId={projectId}
            shot={shot}
            applyDraft={suggestionDraft}
            onSaved={handleDesignSaved}
            onDirtyChange={setDesignDirty}
          />
          <div className="qc-director-suggestion" data-testid="director-section-suggestion">
            <ShotDirectorSuggestionPanel
              key={`suggestion:${shot.id}`}
              projectId={projectId}
              shot={shot}
              dirty={designDirty}
              onApplyDraft={applySuggestionDraft}
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
            dirty={designDirty}
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
      className={`qc-director-sidebar${collapsed ? " is-collapsed" : ""}`}
      data-testid="director-sidebar"
      data-operation-panel="director-operation-panel"
      data-shot-id={shot?.id ?? undefined}
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
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "展开操作面板" : "收起操作面板"}
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
      )}
    </aside>
  );
}
