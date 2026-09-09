import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { DirectorSidebar } from "../director/DirectorSidebar";
import type { ReferenceResolutionState } from "../../components/assets/AssetReferencePicker";
import { ContextDock, type ContextTool } from "../shots/ContextDock";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotCandidateTray } from "../shots/ShotCandidateTray";
import { ShotDetailsPanel } from "../shots/ShotDetailsPanel";
import { ShotStrip } from "../shots/ShotStrip";
import {
  isConfirmableShotCandidate,
  parseShotCandidates,
  type ShotCandidate,
} from "../shots/shotCandidates";
import type { ShotExecutionReference, ShotLite } from "../shots/api";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import { hasActiveSceneRuns, SCENE_ACTIVE_REFETCH_MS } from "../production/sceneRunState";
import { fetchSceneWorkspace, type SceneWorkspaceRead } from "./api";
import { queryKeys } from "../../lib/queryKeys";
import { UnsavedChangesDialog } from "./UnsavedChangesDialog";

type SceneWorkspaceProps = {
  projectId: string;
  sceneId: string;
  initialShotId?: string;
  openDirector?: boolean;
  onOpenEditing?: () => void;
  onDirtyStateChange?: (dirty: boolean) => void;
};

type ShotReferenceContext = {
  references: ShotExecutionReference[];
  ready: boolean;
};

const EMPTY_REFERENCE_CONTEXT: ShotReferenceContext = { references: [], ready: false };

function sameReferences(left: ShotExecutionReference[], right: ShotExecutionReference[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function draftFromShot(shot: ShotLite): ShotDesignDraft {
  return {
    image_prompt: shot.image_prompt,
    video_prompt: shot.video_prompt,
    director_state: { ...shot.director_state },
    director_state_text: JSON.stringify(shot.director_state ?? {}, null, 2),
  };
}

/**
 * Canvas-first Scene/Shot Workbench orchestrator (V2 UI-1).
 *
 * SceneWorkspaceRead remains the only server snapshot. selectedShotId, local
 * candidate preview, reference resolution drafts, and the new Context Dock /
 * sheet / tray / strip UI state are view state scoped to the current Scene;
 * none create a second media or production fact source. The Canvas keeps
 * dominant visual weight: the operation panel and Details are floating sheets
 * opened on demand, the Candidate Tray is a conditional review surface, and
 * the ShotStrip defaults to compact navigation.
 */
export function SceneWorkspace({
  projectId,
  sceneId,
  initialShotId,
  openDirector = false,
  onOpenEditing,
  onDirtyStateChange,
}: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(initialShotId ?? null);
  const [previewCandidate, setPreviewCandidate] = useState<ShotCandidate | null>(null);
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, ShotReferenceContext>>({});
  // Context Dock / sheet / tray / strip / details are pure UI state.
  const [activeTool, setActiveTool] = useState<ContextTool | null>(
    openDirector ? "director" : null,
  );
  const [trayExpanded, setTrayExpanded] = useState(false);
  const [stripExpanded, setStripExpanded] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  // Shared design draft lives here so closing the Context Sheet keeps it.
  const [designDirty, setDesignDirty] = useState(false);
  const [designDrafts, setDesignDrafts] = useState<Record<string, ShotDesignDraft>>({});
  const [suggestionDraft, setSuggestionDraft] = useState<ShotDesignDraft | null>(null);
  const [pendingShotId, setPendingShotId] = useState<string | null>(null);
  const workspace = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, sceneId),
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId) && projectId !== "demo",
    refetchInterval: (query) =>
      hasActiveSceneRuns(query.state.data?.trace as Record<string, unknown[]> | undefined)
        ? SCENE_ACTIVE_REFETCH_MS
        : false,
  });

  useEffect(() => {
    setSelectedShotId(initialShotId ?? null);
    setPreviewCandidate(null);
    setReferenceDrafts({});
    setActiveTool(openDirector ? "director" : null);
    setTrayExpanded(false);
    setStripExpanded(false);
    setDetailsOpen(false);
    setDesignDirty(false);
    setDesignDrafts({});
    setSuggestionDraft(null);
    setPendingShotId(null);
  }, [projectId, sceneId, initialShotId, openDirector]);

  useEffect(() => {
    onDirtyStateChange?.(designDirty);
  }, [designDirty, onDirtyStateChange]);

  const data = workspace.data as SceneWorkspaceRead | undefined;
  const shots = data?.shots ?? [];
  const selected = (
    selectedShotId !== null
      ? (shots.find((shot) => shot.id === selectedShotId) ?? null)
      : (shots[0] ?? null)
  ) as ShotLite | null;
  const selectedShotKey = selected?.id ?? null;
  const selectedBindingRows = selected ? (data?.references?.[selected.id] ?? []) : [];
  const selectedShotHasBindings = selectedBindingRows.length > 0;

  // A fallback first Shot is still a selected Shot from the user's point of
  // view. Drafts are keyed by Shot so returning to A cannot read B's context.
  useEffect(() => {
    if (selectedShotKey === null) return;
    setReferenceDrafts((current) =>
      current[selectedShotKey]
        ? current
        : {
            ...current,
            [selectedShotKey]: {
              ...EMPTY_REFERENCE_CONTEXT,
              // An unbound Shot has no server resolution to wait for. Keep
              // generation available while the References tab remains lazy;
              // bound Shots stay fail-closed until AssetReferencePicker has
              // resolved their concrete artifacts.
              ready: !selectedShotHasBindings,
            },
          },
    );
  }, [selectedShotHasBindings, selectedShotKey]);

  useEffect(() => {
    // Canvas previews and design drafts are local and must never bleed into a
    // newly selected Shot. Formal confirmation also clears preview state
    // before refetching.
    setPreviewCandidate(null);
    setDesignDirty(false);
    setSuggestionDraft(null);
  }, [selectedShotKey]);

  const selectShot = useCallback(
    (shotId: string) => {
      if (shotId === selectedShotKey) return;
      if (designDirty) {
        setPendingShotId(shotId);
        return;
      }
      setSelectedShotId(shotId);
      setPreviewCandidate(null);
    },
    [designDirty, selectedShotKey],
  );

  const selectTool = useCallback((tool: ContextTool) => {
    // Context Sheet and Details are mutually exclusive. Takes stays independent
    // so Generate can still auto-expand the Candidate Tray.
    setDetailsOpen(false);
    setActiveTool((current) => (current === tool ? null : tool));
  }, []);

  const toggleDetails = useCallback(() => {
    if (detailsOpen) {
      setDetailsOpen(false);
      return;
    }
    setActiveTool(null);
    setDetailsOpen(true);
  }, [detailsOpen]);

  const handleExecuted = useCallback(async () => {
    // Generate fired: surface the Candidate review surface without leaving the
    // Canvas. The tray re-reads candidates from the refreshed workspace.
    setTrayExpanded(true);
    await workspace.refetch();
  }, [workspace]);

  const handleDesignSaved = useCallback(async () => {
    if (selectedShotKey !== null) {
      setDesignDrafts((current) => {
        const next = { ...current };
        delete next[selectedShotKey];
        return next;
      });
    }
    setDesignDirty(false);
    setSuggestionDraft(null);
    await workspace.refetch();
  }, [selectedShotKey, workspace]);

  const updateDesignDraft = useCallback(
    (draft: ShotDesignDraft) => {
      if (selectedShotKey === null) return;
      setDesignDrafts((current) => ({ ...current, [selectedShotKey]: draft }));
    },
    [selectedShotKey],
  );

  const updateDesignDirty = useCallback(
    (dirty: boolean) => {
      setDesignDirty(dirty);
      if (dirty || selectedShotKey === null) return;
      setDesignDrafts((current) => {
        if (!(selectedShotKey in current)) return current;
        const next = { ...current };
        delete next[selectedShotKey];
        return next;
      });
    },
    [selectedShotKey],
  );

  const updateSelectedReferences = useCallback(
    (references: ShotExecutionReference[]) => {
      if (selectedShotKey === null) return;
      setReferenceDrafts((current) => {
        const previous = current[selectedShotKey] ?? EMPTY_REFERENCE_CONTEXT;
        if (sameReferences(previous.references, references)) return current;
        return {
          ...current,
          [selectedShotKey]: {
            references: references.map((reference) => ({ ...reference })),
            ready: previous.ready,
          },
        };
      });
    },
    [selectedShotKey],
  );

  const updateReferenceResolutionState = useCallback(
    (state: ReferenceResolutionState) => {
      if (selectedShotKey === null) return;
      setReferenceDrafts((current) => {
        const previous = current[selectedShotKey] ?? EMPTY_REFERENCE_CONTEXT;
        const ready = state === "ready";
        if (previous.ready === ready) return current;
        return {
          ...current,
          [selectedShotKey]: { ...previous, ready },
        };
      });
    },
    [selectedShotKey],
  );

  const selectedReferenceContext = (selectedShotKey && referenceDrafts[selectedShotKey]) || {
    ...EMPTY_REFERENCE_CONTEXT,
    ready: !selectedShotHasBindings,
  };
  const selectedReferences = selectedReferenceContext.references;
  const selectedReferencesReady = selectedReferenceContext.ready;
  const candidates = selected ? (data?.candidates?.[selected.id] ?? []) : [];
  const candidateCount = parseShotCandidates(candidates).filter(isConfirmableShotCandidate).length;
  const trace = selected ? (data?.trace?.[selected.id] ?? []) : [];
  const designDraft = selected ? (designDrafts[selected.id] ?? draftFromShot(selected)) : undefined;

  return (
    <div className="qc-scene-workspace" data-testid="scene-workspace">
      <header className="qc-scene-header">
        <div className="qc-scene-context" data-testid="scene-context">
          <span className="director-stage-kicker">场景工作台</span>
          <h1>{data?.scene.location_name ?? "场景"}</h1>
          <span>
            {data?.scene.episode_number}.{data?.scene.scene_number} ·{" "}
            {data?.scene.time_of_day ?? "—"}
          </span>
          {data?.scene.synopsis && <p>{data.scene.synopsis}</p>}
        </div>
        <div className="qc-scene-header-actions">
          <span>{shots.length} 个镜头</span>
          <a
            className="qc-overview-primary"
            href={`/projects/${projectId}/edit`}
            data-testid="scene-edit-entry"
            onClick={(event) => {
              if (onOpenEditing) {
                event.preventDefault();
                onOpenEditing();
              }
            }}
          >
            进入剪辑
          </a>
        </div>
      </header>

      {data && selectedShotId !== null && !selected && (
        <p role="alert">目标镜头不在此场景，请重新选择镜头。</p>
      )}
      {workspace.isError && (
        <div className="flash err" data-testid="scene-sync-error">
          {data
            ? `连接中断，状态待同步：${String(workspace.error)}`
            : `无法读取场景工作区：${String(workspace.error)}`}
        </div>
      )}
      {data && hasActiveSceneRuns(data.trace as Record<string, unknown[]>) && (
        <p className="qc-scene-sync" data-testid="scene-active-sync" role="status">
          生产进行中，页面将自动同步服务端状态。
        </p>
      )}
      {workspace.isLoading && !data && (
        <p className="qc-scene-loading" data-testid="scene-workspace-loading">
          正在读取场景与镜头事实…
        </p>
      )}

      <div className="qc-scene-layout" data-selected-shot-id={selectedShotKey ?? undefined}>
        <div className="qc-scene-stage" data-testid="scene-stage">
          <CinematicCanvas
            projectId={projectId}
            shot={selected}
            candidates={candidates}
            selectedCandidate={previewCandidate}
            trace={trace}
          />
          <ContextDock
            activeTool={activeTool}
            candidateCount={candidateCount}
            trayExpanded={trayExpanded}
            detailsOpen={detailsOpen}
            hasShot={Boolean(selected)}
            onSelectTool={selectTool}
            onToggleTray={() => setTrayExpanded((value) => !value)}
            onToggleDetails={toggleDetails}
          />
          <ShotCandidateTray
            projectId={projectId}
            shot={selected}
            candidates={candidates}
            selectedCandidate={previewCandidate}
            expanded={trayExpanded}
            onToggleExpanded={() => setTrayExpanded((value) => !value)}
            onPreviewCandidate={setPreviewCandidate}
            onConfirmed={async () => {
              setPreviewCandidate(null);
              await workspace.refetch();
            }}
          />
          <ShotStrip
            projectId={projectId}
            shots={shots}
            selectedShotId={selectedShotKey}
            onSelectShot={selectShot}
            expanded={stripExpanded}
            onToggleExpanded={() => setStripExpanded((value) => !value)}
            traceByShot={(data?.trace ?? {}) as Record<string, unknown[]>}
          />
          <DirectorSidebar
            projectId={projectId}
            shot={selected}
            references={selectedReferences}
            referencesReady={selectedReferencesReady}
            trace={trace}
            onReferencesChange={updateSelectedReferences}
            onResolutionStateChange={updateReferenceResolutionState}
            onWorkspaceRefresh={handleExecuted}
            open={activeTool !== null}
            requestedTool={activeTool}
            onClose={() => setActiveTool(null)}
            designDirty={designDirty}
            onDesignDirtyChange={updateDesignDirty}
            designDraft={designDraft}
            onDesignDraftChange={updateDesignDraft}
            suggestionDraft={suggestionDraft}
            onApplySuggestionDraft={setSuggestionDraft}
            onDesignSaved={handleDesignSaved}
          />
          <ShotDetailsPanel
            open={detailsOpen}
            shot={selected}
            trace={trace}
            onClose={() => setDetailsOpen(false)}
          />
        </div>
      </div>
      {pendingShotId !== null && (
        <UnsavedChangesDialog
          title="切换镜头前先处理当前草稿"
          detail="当前镜头有未保存的设计。返回保存可继续编辑；放弃后才会切换，草稿不会带到下一个镜头。"
          discardLabel="放弃并切换"
          onReturnToSave={() => {
            setPendingShotId(null);
            setActiveTool("director");
          }}
          onDiscard={() => {
            if (selectedShotKey !== null) {
              setDesignDrafts((current) => {
                const next = { ...current };
                delete next[selectedShotKey];
                return next;
              });
            }
            setDesignDirty(false);
            setSuggestionDraft(null);
            setSelectedShotId(pendingShotId);
            setPreviewCandidate(null);
            setPendingShotId(null);
          }}
        />
      )}
    </div>
  );
}
