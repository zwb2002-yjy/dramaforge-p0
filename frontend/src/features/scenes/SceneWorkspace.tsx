import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ReferenceResolutionState } from "../../components/assets/AssetReferencePicker";
import { Button, Dialog, Drawer, Alert, Field, Select } from "../../components/ui";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import { ModelConnectionSettings } from "../../components/provider/ModelConnectionSettings";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotCandidateTray } from "../shots/ShotCandidateTray";
import { ShotInspector, type InspectorFocus } from "../shots/ShotInspector";
import { ShotStrip } from "../shots/ShotStrip";
import { ShotContinuityCompare } from "../shots/ShotContinuityCompare";
import { parseShotCandidates, type ShotCandidate } from "../shots/shotCandidates";
import type { ShotExecutionReference, ShotLite } from "../shots/api";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import {
  clearShotDraft,
  detectDraftConflicts,
  loadShotDraft,
  saveShotDraft,
  restoreShotDraft,
  shotDraftFromServer,
  type DraftConflictChoices,
  type StoredShotDraft,
} from "../shots/shotDraftStorage";
import { hasActiveSceneRuns, SCENE_ACTIVE_REFETCH_MS } from "../production/sceneRunState";
import { fetchSceneWorkspace, type SceneWorkspaceRead } from "./api";
import { queryKeys } from "../../lib/queryKeys";
import { SceneAnimaticPreview } from "./SceneAnimaticPreview";
import { UnsavedChangesDialog } from "./UnsavedChangesDialog";
import { ResonanceStage } from "../resonance/ResonanceStage";
import { BatchFillActions } from "../production";
import { replaceMentionLabel } from "../../lib/mentionLabels";

type SceneWorkspaceProps = {
  projectId: string;
  sceneId: string;
  initialShotId?: string;
  openDirector?: boolean;
  openPrompts?: boolean;
  openGenerate?: boolean;
  openCandidates?: boolean;
  onOpenEditing?: () => void;
  editingReturnHref?: string;
  onOpenOverview?: () => void;
  onDirtyStateChange?: (dirty: boolean) => void;
  onSelectedShotChange?: (shotId: string) => void;
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
    dialogue: shot.dialogue ?? "",
    image_prompt: shot.image_prompt,
    video_prompt: shot.video_prompt,
    director_state: { ...shot.director_state },
    director_state_text: JSON.stringify(shot.director_state ?? {}, null, 2),
  };
}

function initialFocus(
  openGenerate: boolean,
  openPrompts: boolean,
  openDirector: boolean,
): { focus: InspectorFocus; revision: number } | null {
  const focus = openGenerate
    ? "generate"
    : openPrompts
      ? "prompts"
      : openDirector
        ? "director"
        : null;
  return focus ? { focus, revision: 1 } : null;
}

/**
 * Scene/Shot workbench: central canvas, compact shot strip, state-driven
 * candidate tray and one right-hand Shot inspector.
 *
 * SceneWorkspaceRead remains the only server snapshot. Selection, local
 * candidate preview, reference resolution drafts and design drafts are view
 * state scoped to the current Scene; none create a second media or
 * production fact source.
 */
export function SceneWorkspace({
  projectId,
  sceneId,
  initialShotId,
  openDirector = false,
  openPrompts = false,
  openGenerate = false,
  openCandidates = false,
  onOpenEditing,
  editingReturnHref,
  onOpenOverview,
  onDirtyStateChange,
  onSelectedShotChange,
}: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(initialShotId ?? null);
  const [previewCandidate, setPreviewCandidate] = useState<ShotCandidate | null>(null);
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, ShotReferenceContext>>({});
  // Inspector section requests, tray and strip are pure UI state.
  const [focusRequest, setFocusRequest] = useState(() =>
    initialFocus(openGenerate, openPrompts, openDirector),
  );
  const [trayExpanded, setTrayExpanded] = useState(openCandidates);
  const [stripExpanded, setStripExpanded] = useState(false);
  const trayAnchor = useRef<HTMLDivElement>(null);
  const sceneHeader = useRef<HTMLElement>(null);
  const [intentSeed, setIntentSeed] = useState<{
    text: string;
    revision: number;
    shotId: string | null;
  } | null>(null);
  // Shared design draft lives here so closing the Context Sheet keeps it.
  const [designDirty, setDesignDirty] = useState(false);
  const [designDrafts, setDesignDrafts] = useState<Record<string, ShotDesignDraft>>({});
  const [suggestionDraft, setSuggestionDraft] = useState<ShotDesignDraft | null>(null);
  const [pendingShotId, setPendingShotId] = useState<string | null>(null);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [animaticOpen, setAnimaticOpen] = useState(false);
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, sceneId),
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId),
    refetchInterval: (query) =>
      hasActiveSceneRuns(query.state.data?.trace as Record<string, unknown[]> | undefined)
        ? SCENE_ACTIVE_REFETCH_MS
        : false,
  });

  const handleCloseModelSettings = useCallback(async () => {
    setModelSettingsOpen(false);
    await Promise.all([
      workspace.refetch(),
      queryClient.invalidateQueries({
        queryKey: queryKeys.model.executionPreflight(projectId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.model.catalog(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.model.projectProfile(projectId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.model.effectiveBindings(projectId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.model.generationOptionsRoot(projectId),
      }),
    ]);
  }, [projectId, queryClient, workspace]);

  useEffect(() => {
    setSelectedShotId(initialShotId ?? null);
    setPreviewCandidate(null);
    setReferenceDrafts({});
    setFocusRequest(initialFocus(openGenerate, openPrompts, openDirector));
    setTrayExpanded(openCandidates);
    setStripExpanded(false);
    setIntentSeed(null);
    setDesignDirty(false);
    setDesignDrafts({});
    setSuggestionDraft(null);
    setPendingShotId(null);
    setModelSettingsOpen(false);
    setAnimaticOpen(false);
    // Scope changes reset drafts; navigating within the same Scene must not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, sceneId]);

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
      // An explicit route selection already exists before workspace data arrives.
      // Do not issue another navigation while the router is restoring that Scene.
      if (shotId === selectedShotId || shotId === selectedShotKey) return;
      if (designDirty) {
        setPendingShotId(shotId);
        return;
      }
      setSelectedShotId(shotId);
      setPreviewCandidate(null);
      onSelectedShotChange?.(shotId);
    },
    [designDirty, selectedShotId, selectedShotKey, onSelectedShotChange],
  );
  const selectFromRoute = useRef(selectShot);
  selectFromRoute.current = selectShot;
  useEffect(() => {
    if (initialShotId) selectFromRoute.current(initialShotId);
  }, [initialShotId]);
  useEffect(() => {
    const focus = initialFocus(openGenerate, openPrompts, openDirector);
    if (focus) setFocusRequest((current) => ({ ...focus, revision: (current?.revision ?? 0) + 1 }));
    if (openCandidates) setTrayExpanded(true);
  }, [openGenerate, openPrompts, openDirector, openCandidates]);

  const requestFocus = useCallback((focus: InspectorFocus) => {
    setFocusRequest((current) => ({ focus, revision: (current?.revision ?? 0) + 1 }));
  }, []);

  const reviewCandidates = useCallback(() => {
    setTrayExpanded(true);
    trayAnchor.current?.scrollIntoView?.({ block: "nearest" });
  }, []);

  const handleExecuted = useCallback(async () => {
    // Generate fired: surface the Candidate review surface without leaving the
    // Canvas. The tray re-reads candidates from the refreshed workspace.
    setTrayExpanded(true);
    await workspace.refetch();
  }, [workspace]);

  const handleDesignSaved = useCallback(async () => {
    if (selectedShotKey !== null) {
      clearShotDraft(projectId, selectedShotKey);
      setDesignDrafts((current) => {
        const next = { ...current };
        delete next[selectedShotKey];
        return next;
      });
    }
    setDesignDirty(false);
    setSuggestionDraft(null);
    await workspace.refetch();
  }, [selectedShotKey, workspace, projectId]);

  const updateDesignDraft = useCallback(
    (draft: ShotDesignDraft) => {
      if (selectedShotKey === null || !selected) return;
      setDesignDrafts((current) => ({ ...current, [selectedShotKey]: draft }));
      saveShotDraft(
        projectId,
        selectedShotKey,
        selected.version,
        draft,
        shotDraftFromServer(selected),
      );
    },
    [selectedShotKey, selected, projectId],
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
  const candidates = useMemo(
    () => (selected ? (data?.candidates?.[selected.id] ?? []) : []),
    [data?.candidates, selected],
  );
  const parsedCandidates = useMemo(() => parseShotCandidates(candidates), [candidates]);
  const trace = selected ? (data?.trace?.[selected.id] ?? []) : [];
  const designDraft = selected ? (designDrafts[selected.id] ?? draftFromShot(selected)) : undefined;

  const [recoverableDraft, setRecoverableDraft] = useState<StoredShotDraft | null>(null);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [recoveryChoices, setRecoveryChoices] = useState<DraftConflictChoices>({});

  useEffect(() => {
    setRecoveryOpen(false);
    setRecoveryChoices({});
  }, [selected?.id, selected?.version]);

  useEffect(() => {
    if (!selectedShotKey) {
      setRecoverableDraft(null);
      return;
    }
    const stored = loadShotDraft(projectId, selectedShotKey);
    setRecoverableDraft(stored);
  }, [selectedShotKey, projectId]);

  const draftConflicts = useMemo(
    () => (selected && recoverableDraft ? detectDraftConflicts(selected, recoverableDraft) : null),
    [selected, recoverableDraft],
  );

  const handleRestoreDraft = useCallback(() => {
    if (!selected || !recoverableDraft) return;
    const conflicts = detectDraftConflicts(selected, recoverableDraft);
    if (conflicts.conflicts.some((item) => !recoveryChoices[item.field])) {
      setRecoveryOpen(true);
      return;
    }
    const restored = restoreShotDraft(selected, recoverableDraft, recoveryChoices);
    setDesignDrafts((current) => ({
      ...current,
      [selected.id]: restored,
    }));
    clearShotDraft(projectId, selected.id);
    const serverDraft = shotDraftFromServer(selected);
    const hasLocalChanges = JSON.stringify(restored) !== JSON.stringify(serverDraft);
    if (hasLocalChanges) {
      saveShotDraft(projectId, selected.id, selected.version, restored, serverDraft);
    }
    setDesignDirty(hasLocalChanges);
    setRecoveryOpen(false);
    setRecoverableDraft(null);
  }, [selected, recoverableDraft, recoveryChoices, projectId]);

  const handleDiscardDraft = useCallback(() => {
    if (!selected) return;
    clearShotDraft(projectId, selected.id);
    setRecoverableDraft(null);
    setDesignDrafts((current) => {
      if (!(selected.id in current)) return current;
      const next = { ...current };
      delete next[selected.id];
      return next;
    });
    setDesignDirty(false);
  }, [selected, projectId]);

  return (
    <div className="qc-scene-workspace" data-testid="scene-workspace">
      <header ref={sceneHeader} className="qc-scene-header">
        <div className="qc-scene-context" data-testid="scene-context">
          <a
            className="qc-scene-back"
            href={`/projects/${projectId}/scenes`}
            aria-label="返回全片分镜总览"
            onClick={(event) => {
              if (onOpenOverview) {
                event.preventDefault();
                onOpenOverview();
              }
            }}
          >
            ← 全片分镜
          </a>
          <span className="director-stage-kicker">分镜</span>
          <h1>{data?.scene.location_name ?? "场景"}</h1>
          <span>
            {data?.scene.episode_number}.{data?.scene.scene_number} ·{" "}
            {timeOfDayLabel(data?.scene.time_of_day)}
          </span>
          {data?.scene.synopsis && <p>{data.scene.synopsis}</p>}
        </div>
        <div className="qc-scene-header-actions">
          <span className="df-num">{shots.length} 个镜头</span>
          <Button
            className="df-scene-compact-jump"
            data-testid="scene-inspector-jump"
            disabled={!selected}
            onClick={() => requestFocus("design")}
          >
            编辑镜头
          </Button>
          <Button
            tone="ghost"
            data-testid="scene-animatic-play-btn"
            onClick={() => setAnimaticOpen(true)}
          >
            场景连播
          </Button>
          <BatchFillActions projectId={projectId} sceneId={sceneId} />
          <a
            className="qc-overview-primary"
            href={editingReturnHref ?? `/projects/${projectId}/edit`}
            data-testid="scene-edit-entry"
            onClick={(event) => {
              if (onOpenEditing) {
                event.preventDefault();
                onOpenEditing();
              }
            }}
          >
            {editingReturnHref ? "返回剪辑" : "进入剪辑"}
          </a>
        </div>
      </header>

      {recoverableDraft && selected && (
        <Alert
          type={draftConflicts?.hasConflict ? "warning" : "info"}
          showIcon
          style={{ margin: "8px 16px" }}
          data-testid="recoverable-draft-banner"
          title={
            draftConflicts?.hasConflict
              ? "发现未保存的本地草稿（服务端已有更新）"
              : "发现未保存的本地草稿"
          }
          description={
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>
                镜头 {selected.shot_number} 在本地保留了上次未提交的设计修改。
                {draftConflicts?.hasConflict && (
                  <span style={{ color: "var(--color-warning, #d46b08)", marginLeft: 8 }}>
                    服务端已有新版本（v{selected.version}，草稿基线 v
                    {recoverableDraft.baselineVersion}），请核对以下字段：
                    {draftConflicts.conflicts.map((c) => c.label).join("、")}。
                  </span>
                )}
              </span>
              <div style={{ display: "flex", gap: "8px" }}>
                <Button size="small" tone="ghost" onClick={handleDiscardDraft}>
                  放弃本地草稿
                </Button>
                <Button
                  size="small"
                  tone={draftConflicts?.hasConflict ? "danger" : "primary"}
                  onClick={handleRestoreDraft}
                >
                  {draftConflicts?.hasConflict ? "核对并恢复草稿" : "恢复草稿"}
                </Button>
              </div>
            </div>
          }
        />
      )}

      <Dialog
        open={recoveryOpen && Boolean(recoverableDraft)}
        title="核对草稿冲突"
        onClose={() => setRecoveryOpen(false)}
        testId="shot-draft-recovery-dialog"
        actions={
          <Button
            tone="primary"
            onClick={handleRestoreDraft}
            disabled={draftConflicts?.conflicts.some((item) => !recoveryChoices[item.field])}
          >
            恢复选定修改到草稿
          </Button>
        }
      >
        <p>仅恢复选定字段，保存前不会修改服务端。服务端版本再次变化时须重新核对。</p>
        {draftConflicts?.conflicts.map((item) => (
          <section key={item.field}>
            <strong>{item.label}</strong>
            {recoverableDraft?.baseline && (
              <p>编辑原值：{JSON.stringify(item.baselineValue) ?? "未设置"}</p>
            )}
            <p>本地草稿：{JSON.stringify(item.localValue) ?? "未设置"}</p>
            <p>服务端值：{JSON.stringify(item.serverValue) ?? "未设置"}</p>
            <Field>
              选择 {item.label}
              <Select
                aria-label={`恢复字段 ${item.field}`}
                value={recoveryChoices[item.field] ?? ""}
                onChange={(value) =>
                  setRecoveryChoices((current) => ({
                    ...current,
                    [item.field]: value as "local" | "server",
                  }))
                }
              >
                <option value="" disabled>
                  请选择
                </option>
                <option value="server">采用服务端值</option>
                <option value="local">保留本地修改</option>
              </Select>
            </Field>
          </section>
        ))}
      </Dialog>

      {data && selectedShotId !== null && !selected && (
        <p role="alert">目标镜头不在此场景，请重新选择镜头。</p>
      )}
      {workspace.isError && (
        <Alert
          data-testid="scene-sync-error"
          role="note"
          type="error"
          showIcon
          description={
            <>
              {data
                ? `连接中断，状态待同步：${String(workspace.error)}`
                : `无法读取场景工作区：${String(workspace.error)}`}
            </>
          }
        />
      )}
      {data && hasActiveSceneRuns(data.trace as Record<string, unknown[]>) && (
        <p className="qc-scene-sync" data-testid="scene-active-sync" role="status">
          正在生成，完成后会自动更新。
        </p>
      )}
      {workspace.isLoading && !data && (
        <p className="qc-scene-loading" data-testid="scene-workspace-loading">
          正在加载画面…
        </p>
      )}

      <div className="df-scene-layout" data-selected-shot-id={selectedShotKey ?? undefined}>
        <div className="df-scene-main" data-testid="scene-stage">
          <ResonanceStage
            key={`${projectId}:${sceneId}:${selectedShotKey}`}
            projectId={projectId}
            shots={shots}
            selectedShotId={selectedShotKey}
            subjects={selectedBindingRows}
            onOpenDirector={() => requestFocus("director")}
            onSelectShot={selectShot}
            onIntent={(text) => {
              setIntentSeed((current) => ({
                text,
                revision: (current?.revision ?? 0) + 1,
                shotId: selectedShotKey,
              }));
              requestFocus("director");
            }}
          >
            <CinematicCanvas
              projectId={projectId}
              shot={selected}
              candidates={candidates}
              selectedCandidate={previewCandidate}
              trace={trace}
            />
          </ResonanceStage>
          <ShotContinuityCompare
            projectId={projectId}
            shots={shots}
            shotId={selectedShotKey}
            candidate={previewCandidate}
            bindings={selectedBindingRows}
          />
          <div ref={trayAnchor}>
            <ShotCandidateTray
              projectId={projectId}
              shot={selected}
              candidates={candidates}
              references={selectedReferences}
              selectedCandidate={previewCandidate}
              expanded={trayExpanded}
              onToggleExpanded={() => setTrayExpanded((value) => !value)}
              onPreviewCandidate={setPreviewCandidate}
              onConfirmed={async () => {
                setPreviewCandidate(null);
                await workspace.refetch();
              }}
            />
          </div>
          <ShotStrip
            projectId={projectId}
            shots={shots}
            selectedShotId={selectedShotKey}
            onSelectShot={selectShot}
            expanded={stripExpanded}
            onToggleExpanded={() => setStripExpanded((value) => !value)}
            traceByShot={(data?.trace ?? {}) as Record<string, unknown[]>}
          />
        </div>
        <ShotInspector
          projectId={projectId}
          shot={selected}
          references={selectedReferences}
          referencesReady={selectedReferencesReady}
          trace={trace}
          candidates={parsedCandidates}
          onReferencesChange={updateSelectedReferences}
          onResolutionStateChange={updateReferenceResolutionState}
          onExecuted={handleExecuted}
          onReviewCandidates={reviewCandidates}
          designDirty={designDirty}
          onDesignDirtyChange={updateDesignDirty}
          designDraft={designDraft}
          onDesignDraftChange={updateDesignDraft}
          onReferenceLabelChanged={(before, after) => {
            if (!selected) return;
            setDesignDrafts((current) => {
              const draft = current[selected.id] ?? draftFromShot(selected);
              return {
                ...current,
                [selected.id]: {
                  ...draft,
                  image_prompt: replaceMentionLabel(draft.image_prompt, before, after),
                  video_prompt: replaceMentionLabel(draft.video_prompt, before, after),
                },
              };
            });
          }}
          suggestionDraft={suggestionDraft}
          onApplySuggestionDraft={setSuggestionDraft}
          onDesignSaved={handleDesignSaved}
          intentSeed={intentSeed?.shotId === selectedShotKey ? intentSeed : null}
          focusRequest={focusRequest}
          onOpenModelSettings={() => setModelSettingsOpen(true)}
          onBackToPreview={() => {
            sceneHeader.current?.scrollIntoView({ block: "start" });
            sceneHeader.current
              ?.querySelector<HTMLButtonElement>('[data-testid="scene-inspector-jump"]')
              ?.focus({ preventScroll: true });
          }}
        />
      </div>
      {pendingShotId !== null && (
        <UnsavedChangesDialog
          title="切换镜头前先处理当前草稿"
          detail="当前镜头有未保存的设计。返回保存可继续编辑；放弃后才会切换，草稿不会带到下一个镜头。"
          discardLabel="放弃并切换"
          onReturnToSave={() => {
            setPendingShotId(null);
            requestFocus("generate");
          }}
          onDiscard={() => {
            if (selectedShotKey !== null) {
              clearShotDraft(projectId, selectedShotKey);
              setDesignDrafts((current) => {
                const next = { ...current };
                delete next[selectedShotKey];
                return next;
              });
            }
            setDesignDirty(false);
            setSuggestionDraft(null);
            setSelectedShotId(pendingShotId);
            onSelectedShotChange?.(pendingShotId);
            setPreviewCandidate(null);
            setPendingShotId(null);
          }}
        />
      )}
      <Drawer
        open={modelSettingsOpen}
        onClose={handleCloseModelSettings}
        title="模型与服务设置"
        kicker="分镜工作台 · 快速配置"
        size="wide"
        testId="scene-model-settings-drawer"
      >
        <ModelConnectionSettings />
      </Drawer>
      <Dialog
        open={animaticOpen}
        title={`场景连播 · ${data?.scene.location_name ?? "预览"}`}
        size="wide"
        onClose={() => setAnimaticOpen(false)}
        testId="scene-animatic-player-dialog"
      >
        <SceneAnimaticPreview
          projectId={projectId}
          shots={shots}
          candidates={data?.candidates}
          onSelectShot={(shotId) => {
            selectShot(shotId);
            setAnimaticOpen(false);
          }}
        />
      </Dialog>
    </div>
  );
}
