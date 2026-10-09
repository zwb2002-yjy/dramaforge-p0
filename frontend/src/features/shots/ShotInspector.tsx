import { useEffect, useRef, useState } from "react";

import {
  AssetReferencePicker,
  type ReferenceResolutionState,
} from "../../components/assets/AssetReferencePicker";
import { Disclosure } from "../../components/ui";
import { CreativeCapabilitiesPanel } from "../production/CreativeCapabilitiesPanel";
import { ShotDirectorSuggestionPanel } from "../director/ShotDirectorSuggestionPanel";
import { ShotDesignPanel, type ShotDesignDraft } from "./ShotDesignPanel";
import { ShotDetailsBody } from "./ShotDetailsPanel";
import { ShotProductionActions } from "./ShotProductionActions";
import type { ShotExecutionReference, ShotLite } from "./api";
import type { ShotCandidate } from "./shotCandidates";
import "./shot-inspector.css";

/** Sections that a deep link or the canvas can open on arrival. */
export type InspectorFocus = "generate" | "prompts" | "director" | null;

type ShotInspectorProps = {
  projectId: string;
  shot: ShotLite | null;
  references: ShotExecutionReference[];
  referencesReady: boolean;
  trace: unknown[];
  candidates: ShotCandidate[];
  onReferencesChange: (references: ShotExecutionReference[]) => void;
  onResolutionStateChange: (state: ReferenceResolutionState) => void;
  onExecuted: () => void | Promise<void>;
  onReviewCandidates: () => void;
  designDirty: boolean;
  onDesignDirtyChange: (dirty: boolean) => void;
  designDraft?: ShotDesignDraft;
  onDesignDraftChange: (draft: ShotDesignDraft) => void;
  onReferenceLabelChanged?: (before: string, after: string) => void;
  suggestionDraft: ShotDesignDraft | null;
  onApplySuggestionDraft: (draft: ShotDesignDraft | null) => void;
  onDesignSaved: () => void | Promise<void>;
  intentSeed?: { text: string; revision: number } | null;
  /** Bumps whenever something asks for a section; the latest request wins. */
  focusRequest?: { focus: InspectorFocus; revision: number } | null;
};

/**
 * The single right-hand inspector of the selected Shot.
 *
 * Organised around the Shot, not around tools: what the frame shows, who is
 * in it, how the camera moves, then one primary next step. Prompts, the local
 * AI director, voice and execution details are on-demand disclosures. All
 * facts still come from the SceneWorkspace read; drafts stay Scene-owned.
 */
export function ShotInspector({
  projectId,
  shot,
  references,
  referencesReady,
  trace,
  candidates,
  onReferencesChange,
  onResolutionStateChange,
  onExecuted,
  onReviewCandidates,
  designDirty,
  onDesignDirtyChange,
  designDraft,
  onDesignDraftChange,
  onReferenceLabelChanged,
  suggestionDraft,
  onApplySuggestionDraft,
  onDesignSaved,
  intentSeed,
  focusRequest,
}: ShotInspectorProps) {
  const root = useRef<HTMLElement>(null);
  const [directorOpen, setDirectorOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    setDirectorOpen(false);
    setDetailsOpen(false);
  }, [shot?.id]);

  // Deep links (?tool=…) and canvas entries reveal one section and bring it
  // into view. Nothing here writes a fact.
  // A request is handled once, as soon as the selected Shot has rendered.
  const handledFocus = useRef<number | null>(null);
  useEffect(() => {
    if (!focusRequest?.focus || !root.current) return;
    if (handledFocus.current === focusRequest.revision) return;
    handledFocus.current = focusRequest.revision;
    const focus = focusRequest.focus;
    if (focus === "director") setDirectorOpen(true);
    const target = root.current.querySelector<HTMLElement>(
      focus === "generate"
        ? '[data-testid="shot-production-actions"]'
        : focus === "prompts"
          ? '[data-testid="shot-design-prompts"]'
          : '[data-testid="shot-inspector-director"]',
    );
    if (focus === "prompts" && target instanceof HTMLDetailsElement) target.open = true;
    target?.scrollIntoView?.({ block: "nearest" });
  }, [focusRequest, shot?.id]);

  if (!shot) {
    return (
      <aside className="df-inspector" data-testid="shot-inspector" aria-label="当前镜头">
        <p className="df-inspector-empty">从下方选择一个镜头。</p>
      </aside>
    );
  }

  const handleSaved = async () => {
    onApplySuggestionDraft(null);
    await onDesignSaved();
  };

  return (
    <aside
      ref={root}
      className="df-inspector"
      data-testid="shot-inspector"
      data-shot-id={shot.id}
      aria-label={`镜头 ${shot.shot_number}`}
    >
      <header className="df-inspector-header">
        <h2>镜头 {shot.shot_number}</h2>
        {designDirty ? (
          <span className="df-status warn" data-testid="shot-design-dirty" role="status">
            未保存
          </span>
        ) : (
          <span className="df-status ok" data-testid="shot-design-saved-state" role="status">
            已保存
          </span>
        )}
      </header>

      <ShotDesignPanel
        key={`design:${shot.id}`}
        projectId={projectId}
        shot={shot}
        draft={designDraft}
        onDraftChange={onDesignDraftChange}
        applyDraft={suggestionDraft}
        onSaved={handleSaved}
        onDirtyChange={onDesignDirtyChange}
        references={
          <AssetReferencePicker
            key={`references:${shot.id}`}
            projectId={projectId}
            shotId={shot.id}
            onReferencesChange={onReferencesChange}
            onResolutionStateChange={onResolutionStateChange}
            onLabelChanged={onReferenceLabelChanged}
          />
        }
        production={(control) => (
          <ShotProductionActions
            key={`production:${shot.id}`}
            projectId={projectId}
            shot={shot}
            references={references}
            referencesReady={referencesReady}
            promptReferencesReady={control.promptReferencesReady}
            dirty={designDirty}
            trace={trace}
            candidates={candidates}
            onExecuted={onExecuted}
            onSave={control.save}
            saving={control.saving}
            onReviewCandidates={onReviewCandidates}
            onOpenDetails={() => setDetailsOpen(true)}
            onDirectorDelegated={() => setDirectorOpen(true)}
          />
        )}
      />

      <Disclosure
        title="AI 导演"
        description="分析这个镜头，给出可应用的修改"
        testId="shot-inspector-director"
        open={directorOpen}
        onOpenChange={setDirectorOpen}
      >
        {directorOpen && (
          <>
            <ShotDirectorSuggestionPanel
              key={`suggestion:${shot.id}`}
              projectId={projectId}
              shot={shot}
              dirty={designDirty}
              onApplyDraft={onApplySuggestionDraft}
              intentSeed={intentSeed}
            />
            <details className="df-inspector-subsection">
              <summary>创作手法</summary>
              <CreativeCapabilitiesPanel
                key={`methods:${shot.id}`}
                projectId={projectId}
                shotId={shot.id}
              />
            </details>
          </>
        )}
      </Disclosure>

      <Disclosure
        title="详情"
        testId="shot-inspector-details"
        open={detailsOpen}
        onOpenChange={setDetailsOpen}
      >
        {detailsOpen && <ShotDetailsBody projectId={projectId} shot={shot} trace={trace} />}
      </Disclosure>
    </aside>
  );
}
