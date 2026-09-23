import { PageHeader, Disclosure } from "../../components/ui";
import { EditingSourcePreview } from "./EditingSourcePreview";
import { AudioArtifactPicker } from "./AudioArtifactPicker";
import { FinalFilmPlayback } from "./FinalFilmPlayback";
import "./editing-recovery.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useEditingDirector } from "./useEditingDirector";
import { useFinalFilmExport } from "./useFinalFilmExport";
import {
  useTimelineDraft,
  type TimelineSaveInput,
  type EditableClip,
  type EditableMetadata,
} from "./useTimelineDraft";
import { EditingSessionPicker } from "./EditingSessionPicker";
import { queryKeys } from "../../lib/queryKeys";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import {
  ApiError,
  artifactContentUrl,
  fetchOpenCutManifest,
  type OpenCutManifestRead,
} from "../../lib/api";
import type { components } from "../../shared/api/generated";
import {
  createEditSession,
  exportEditSession,
  fetchEditSession,
  saveEditTimeline,
  type EditExportRead,
} from "./api";

type EditingWorkspaceProps = {
  projectId: string;
  /** Exact persisted EditSession identity from the route search. */
  sessionId?: string;
  /** The route owns URL identity and navigates after explicit creation. */
  onSessionCreated?: (sessionId: string) => void;
  onSessionSelected?: (sessionId: string) => void;
};

type JsonValue = components["schemas"]["JsonValue"];
function clipsByTrack(manifest: OpenCutManifestRead | undefined) {
  return (manifest?.tracks ?? []).flatMap((track) =>
    track.clips.map((clip) => ({ track: track.name, clip })),
  );
}

function videoClips(manifest: OpenCutManifestRead | undefined) {
  return clipsByTrack(manifest).filter(({ clip }) => clip.track_kind === "video");
}

function formatTimelineSeconds(value: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(parsed);
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function clipDuration(clip: EditableClip): string {
  const value = clip.duration_seconds;
  return typeof value === "number" || typeof value === "string" ? String(value) : "";
}

function clipValue(clip: EditableClip, key: string): string {
  const value = clip[key];
  return value === undefined || value === null ? "—" : String(value);
}

function editableValue(clip: EditableClip, key: string, fallback = ""): string {
  const value = clip[key];
  return value === undefined || value === null ? fallback : String(value);
}

function metadataValue(metadata: EditableMetadata, key: string, fallback = ""): string {
  const value = metadata[key];
  return value === undefined || value === null ? fallback : String(value);
}

function transitionKind(clip: EditableClip): "cut" | "crossfade" {
  const value = clip.transition;
  if (typeof value === "string" && value.toLowerCase() === "crossfade") return "crossfade";
  if (isJsonObject(value) && String(value.kind ?? value.type ?? "").toLowerCase() === "crossfade") {
    return "crossfade";
  }
  return "cut";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

/**
 * Short human reference for a server identity.
 *
 * Raw UUIDs and hashes are development/diagnostic facts: the creative surface
 * shows a short reference and keeps the full identifier in the collapsed
 * diagnostics block below it.
 */
function shortReference(value: unknown): string {
  const text = typeof value === "string" ? value : String(value ?? "");
  return text ? text.slice(0, 8) : "—";
}

/** Human label for one clip, e.g. "镜头 #4". */
function clipLabel(shotNumberById: Map<string, number>, shotId: unknown, index: number): string {
  const text = typeof shotId === "string" ? shotId : "";
  const number = text ? shotNumberById.get(text) : undefined;
  return number === undefined ? `片段 ${index + 1}` : `镜头 #${number}`;
}

function isSessionVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

const EDIT_SESSION_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  active: "编辑中",
  archived: "已归档",
};

const STORAGE_STATE_LABEL: Record<string, string> = {
  available: "可用",
  missing: "缺失",
  deleted: "已删除",
  pending: "处理中",
};

/**
 * Editing workspace over the persisted EditingAdapter session.
 *
 * Without a sessionId this remains the existing read-only formal OpenCut
 * manifest preview. A session is created only by an explicit button click;
 * after that, all editing state comes from the exact persisted session query.
 */
export function EditingWorkspace({
  projectId,
  sessionId,
  onSessionCreated,
  onSessionSelected,
}: EditingWorkspaceProps) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<string | null>(null);
  const [exported, setExported] = useState<EditExportRead | null>(null);
  const hasSession = Boolean(sessionId);
  const manifest = useQuery({
    queryKey: queryKeys.production.opencutManifest(projectId),
    queryFn: () => fetchOpenCutManifest(projectId),
    enabled: Boolean(projectId) && !hasSession,
  });
  const persistedSession = useQuery({
    queryKey: queryKeys.editing.session(projectId, sessionId),
    queryFn: () => fetchEditSession(projectId, sessionId!),
    enabled: Boolean(projectId) && hasSession,
  });
  const currentSessionVersion = persistedSession.data?.version;
  const timeline = useTimelineDraft(projectId, sessionId, persistedSession.data);
  const { draft, baseline, dirty, updateClipField, updateTimelineMetadata } = timeline;

  const {
    filmHistory,
    displayedFilm,
    selectHistoryRun,
    exportFilm: runFinalFilmExport,
    pending: finalFilmPending,
    error: finalFilmError,
  } = useFinalFilmExport({
    projectId,
    sessionId,
    version: currentSessionVersion,
    dirty,
  });

  useEffect(() => {
    setFeedback(null);
    setExported(null);
  }, [projectId, sessionId]);

  const {
    suggestionInstruction,
    setSuggestionInstruction,
    suggestionPreview,
    suggestionIsStale,
    suggestionError,
    repairRouting,
    repairError,
    selectedSuggestionOps,
    setSelectedSuggestionOps,
    suggestionPending,
    rejectionPending,
    repairPending,
    submitSuggestion,
    submitProactiveSuggestion,
    submitRepairRouting,
    rejectSuggestion,
    clearAfterSave,
  } = useEditingDirector({
    projectId,
    sessionId,
    session: persistedSession.data,
    onFeedback: setFeedback,
  });

  const create = useMutation({
    mutationFn: () => createEditSession(projectId),
    onSuccess: (created) => {
      setFeedback(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.editing.sessions(projectId) });
      onSessionCreated?.(created.id);
    },
    onError: (error: unknown) => {
      setFeedback(`创建 EditSession 失败：${errorMessage(error)}`);
    },
  });

  const save = useMutation({
    mutationFn: (input: TimelineSaveInput) =>
      saveEditTimeline(input.projectId, input.sessionId, input.timeline, input.expectedVersion),
    onSuccess: (saved, input) => {
      if (!timeline.acceptSaved(saved, input)) return;
      setFeedback("时间线已保存。");
      setExported(null);
      clearAfterSave();
      queryClient.setQueryData(["edit-session", projectId, sessionId], saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.editing.sessions(projectId) });
    },
    onError: (error: unknown, input: TimelineSaveInput) => {
      if (!timeline.isCurrentSave(input)) return;
      // Keep draft/baseline untouched so failed saves leave the editor dirty.
      setFeedback(
        error instanceof ApiError && error.status === 409
          ? "保存时间线失败：服务器时间线已更新；本地未保存草稿已保留。请重新加载后手动合并，再次保存。"
          : `保存时间线失败：${errorMessage(error)}`,
      );
    },
  });

  function submitSave() {
    if (save.isPending) return;
    try {
      save.mutate(timeline.captureSave());
    } catch (error: unknown) {
      setFeedback(`保存时间线失败：${errorMessage(error)}`);
    }
  }

  const exportMutation = useMutation({
    mutationFn: () => {
      if (!sessionId) throw new Error("请先创建或选择剪辑会话");
      return exportEditSession(projectId, sessionId);
    },
    onSuccess: (result) => {
      setExported(result);
      setFeedback(null);
    },
    onError: (error: unknown) => {
      setFeedback(`导出时间线失败：${errorMessage(error)}`);
    },
  });

  function moveClip(index: number, offset: -1 | 1) {
    timeline.moveClip(index, offset);
    setFeedback(null);
    setExported(null);
  }

  function applySuggestionToDraft(operationIndices: number[] | null) {
    if (!suggestionPreview || !draft || suggestionIsStale || rejectionPending) return;
    const operations = suggestionPreview.suggestion.plan.operations;
    const indices = operationIndices ?? operations.map((_operation, index) => index);
    if (indices.length === 0) {
      setFeedback("请先选择至少一条剪辑操作。");
      return;
    }

    const failure = timeline.applySuggestion(
      indices.map((index) => operations[index]).filter((op) => op !== undefined),
      suggestionPreview.suggestion.base_session_version,
    );
    if (failure) {
      setFeedback(failure);
      return;
    }
    setFeedback("建议已应用到时间线草稿；请检查后显式保存。");
    setExported(null);
  }

  function updateClipDuration(index: number, value: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) return;
    timeline.updateClipField(index, "duration_seconds", parsed);
    setFeedback(null);
    setExported(null);
  }

  const clips = clipsByTrack(manifest.data);
  const formalVideoClips = videoClips(manifest.data);
  const formalShotIds = new Set(formalVideoClips.map(({ clip }) => clip.shot_id));
  const shotNumberById = new Map(
    (manifest.data?.shots ?? []).map((shot) => [shot.shot_id, shot.shot_number]),
  );
  const incompleteShotCount =
    manifest.data?.shots.filter((shot) => !formalShotIds.has(shot.shot_id)).length ?? 0;
  const isEmptyProject = manifest.data?.shots.length === 0 && clips.length === 0;

  if (hasSession) {
    return (
      <div className="qc-project-page" data-testid="editing-workspace" data-session-id={sessionId}>
        <PageHeader title="剪辑成片" />
        <Disclosure title="切换已有剪辑">
          <EditingSessionPicker
            projectId={projectId}
            sessionId={sessionId}
            disabled={
              dirty || finalFilmPending !== null || save.isPending || exportMutation.isPending
            }
            onSelect={onSessionSelected}
          />
        </Disclosure>
        <p className="muted" data-testid="editing-session-read-only">
          保存时间线后导出，不重做源素材。
        </p>

        {persistedSession.isLoading && (
          <p className="muted" data-testid="editing-session-loading">
            正在读取剪辑会话…
          </p>
        )}
        {persistedSession.isError && (
          <div className="flash err" data-testid="editing-session-error">
            无法读取剪辑会话，请刷新页面重试。
          </div>
        )}

        {persistedSession.data && draft && baseline && (
          <>
            <div className="editing-cut-layout">
              <EditingSourcePreview projectId={projectId} clips={draft.clips} />
              <div className="editing-cut-controls">
                <Disclosure title="版本与来源">
                  <section className="editing-session-facts" data-testid="edit-session-facts">
                    <h2>{persistedSession.data.name}</h2>
                    <dl>
                      <dt>会话编号</dt>
                      <dd data-testid="edit-session-reference">
                        {shortReference(persistedSession.data.id)}
                      </dd>
                      <dt>状态</dt>
                      <dd>
                        {EDIT_SESSION_STATUS_LABEL[persistedSession.data.status] ??
                          persistedSession.data.status}
                      </dd>
                      <dt>版本</dt>
                      <dd data-testid="edit-session-version">
                        {isSessionVersion(persistedSession.data.version)
                          ? `v${persistedSession.data.version}`
                          : "尚未加载"}
                      </dd>
                      <dt>镜头数量</dt>
                      <dd>{draft.clips.length}</dd>
                    </dl>
                    <details className="editing-diagnostics" data-testid="edit-session-diagnostics">
                      <summary>开发 / 诊断详情（只读）</summary>
                      <p className="muted">
                        完整编号、生产血缘与内部字段；仅供排障，不参与创作操作。
                      </p>
                      <dl>
                        <dt>剪辑会话编号</dt>
                        <dd>{persistedSession.data.id}</dd>
                      </dl>
                      <h4>生产血缘（只读）</h4>
                      <pre data-testid="edit-session-lineage">
                        {formatJson(persistedSession.data.production_lineage)}
                      </pre>
                    </details>
                  </section>
                </Disclosure>
                <Disclosure title="导演剪辑建议">
                  <section
                    className="editing-director-suggestion"
                    data-testid="editing-director-suggestion"
                    data-project-id={projectId}
                    data-session-id={sessionId}
                  >
                    <header>
                      <div>
                        <p className="editing-director-suggestion-kicker">Director suggestion</p>
                        <h2>剪辑建议预览</h2>
                      </div>
                      <span data-testid="editing-suggestion-current-version">
                        当前 EditSession v
                        {isSessionVersion(currentSessionVersion) ? currentSessionVersion : "—"}
                      </span>
                    </header>
                    <p className="editing-director-suggestion-note">
                      建议只形成待审核
                      Proposal，不会应用到时间线；应用后的时间线仍由下方手动编辑和显式保存控制。
                    </p>
                    <button
                      type="button"
                      data-testid="request-proactive-editing-suggestion"
                      onClick={submitProactiveSuggestion}
                      disabled={suggestionPending || !isSessionVersion(currentSessionVersion)}
                    >
                      {suggestionPending ? "正在分析…" : "主动分析剪辑节奏"}
                    </button>
                    <label htmlFor="editing-director-suggestion-instruction">
                      导演要求
                      <textarea
                        id="editing-director-suggestion-instruction"
                        data-testid="editing-director-suggestion-instruction"
                        aria-label="剪辑导演要求"
                        value={suggestionInstruction}
                        onChange={(event) => setSuggestionInstruction(event.target.value)}
                        placeholder="例如：让前两个镜头之间多留一点停顿"
                        disabled={suggestionPending}
                      />
                    </label>
                    <button
                      type="button"
                      data-testid="request-editing-director-suggestion"
                      onClick={submitSuggestion}
                      disabled={
                        suggestionPending ||
                        !suggestionInstruction.trim() ||
                        !isSessionVersion(currentSessionVersion)
                      }
                    >
                      {suggestionPending ? "正在请求建议…" : "请求剪辑建议"}
                    </button>

                    {suggestionPending && (
                      <p
                        className="editing-director-suggestion-status"
                        data-testid="editing-suggestion-pending"
                        role="status"
                      >
                        正在基于当前 EditSession v{currentSessionVersion} 生成建议…
                      </p>
                    )}
                    {suggestionError && (
                      <p
                        className="editing-director-suggestion-error"
                        data-testid="editing-suggestion-error"
                        role="alert"
                      >
                        {suggestionError}
                      </p>
                    )}

                    <button
                      type="button"
                      data-testid="request-repair-routing"
                      onClick={submitRepairRouting}
                      disabled={repairPending || !isSessionVersion(currentSessionVersion)}
                    >
                      {repairPending ? "正在判定…" : "判断是否需要生产 Repair"}
                    </button>
                    {repairError && (
                      <p
                        className="editing-repair-routing-error"
                        data-testid="editing-repair-routing-error"
                        role="alert"
                      >
                        {repairError}
                      </p>
                    )}
                    {repairRouting && (
                      <article
                        className="editing-repair-routing-result"
                        data-testid="editing-repair-routing-result"
                        data-can-fix={repairRouting.can_fix_in_timeline}
                        data-proposal-id={repairRouting.proposal_id ?? ""}
                        data-session-version={repairRouting.session_version}
                      >
                        <h3>
                          {repairRouting.can_fix_in_timeline
                            ? "可以在时间线内修复"
                            : "需要 Production Repair"}
                        </h3>
                        <p data-testid="editing-repair-routing-reason">{repairRouting.reason}</p>
                        {!repairRouting.can_fix_in_timeline && (
                          <>
                            <p className="callout" data-testid="editing-repair-routing-notice">
                              Repair Proposal 已创建但不会自动执行；请到审片/镜头生产层打开 Repair
                              Plan 人工确认后执行。
                            </p>
                            <dl>
                              <dt>proposal_id</dt>
                              <dd>{repairRouting.proposal_id}</dd>
                              <dt>item_id</dt>
                              <dd>{repairRouting.item_id}</dd>
                              <dt>需要修复的镜头</dt>
                              <dd>{repairRouting.shot_ids?.join(", ") || "—"}</dd>
                            </dl>
                          </>
                        )}
                      </article>
                    )}

                    {suggestionPreview && (
                      <article
                        className="editing-director-suggestion-preview"
                        data-testid="editing-suggestion-preview"
                        data-proposal-id={suggestionPreview.proposal_id}
                        data-item-id={suggestionPreview.item_id}
                        data-base-session-version={
                          suggestionPreview.suggestion.base_session_version
                        }
                      >
                        <header>
                          <div>
                            <h3>Pending proposal（未应用）</h3>
                            <p>这是待审核建议预览，不是已应用的时间线事件。</p>
                          </div>
                          <span data-testid="editing-suggestion-pending-status">pending</span>
                        </header>
                        <dl className="editing-director-suggestion-identities">
                          <dt>proposal_id</dt>
                          <dd data-testid="editing-suggestion-proposal-id">
                            {suggestionPreview.proposal_id}
                          </dd>
                          <dt>item_id</dt>
                          <dd data-testid="editing-suggestion-item-id">
                            {suggestionPreview.item_id}
                          </dd>
                          <dt>基于版本</dt>
                          <dd data-testid="editing-suggestion-base-version">
                            v{suggestionPreview.suggestion.base_session_version}
                          </dd>
                          {suggestionPreview.director_evidence && (
                            <>
                              <dt>文本模型</dt>
                              <dd data-testid="editing-suggestion-model-evidence">
                                {suggestionPreview.director_evidence.actual_model ??
                                  suggestionPreview.director_evidence.model_id}
                                · {suggestionPreview.director_evidence.turn_id.slice(0, 8)}
                              </dd>
                            </>
                          )}
                        </dl>

                        <section
                          className="editing-director-suggestion-operations"
                          data-testid="editing-suggestion-operations"
                        >
                          <h4>Typed operations</h4>
                          {suggestionPreview.suggestion.plan.operations.length === 0 ? (
                            <p className="muted">没有可展示的 typed operation。</p>
                          ) : (
                            <ol>
                              {suggestionPreview.suggestion.plan.operations.map(
                                (operation, index) => (
                                  <li
                                    key={`${operation.operation}-${index}`}
                                    data-testid="editing-suggestion-operation"
                                    data-operation={operation.operation}
                                  >
                                    <label>
                                      <input
                                        type="checkbox"
                                        data-testid={`editing-suggestion-op-select-${index}`}
                                        aria-label={`采用第 ${index + 1} 条剪辑操作`}
                                        checked={selectedSuggestionOps[index] === true}
                                        disabled={suggestionIsStale || rejectionPending}
                                        onChange={(event) =>
                                          setSelectedSuggestionOps((current) => ({
                                            ...current,
                                            [index]: event.target.checked,
                                          }))
                                        }
                                      />
                                      采用
                                    </label>
                                    <strong>{operation.operation}</strong>
                                    {operation.operation === "reorder_clips" ? (
                                      <span>顺序：{operation.clip_ids.join(" → ")}</span>
                                    ) : operation.operation === "set_clip_duration" ? (
                                      <span>
                                        片段 {operation.clip_id} · 时长 {operation.duration_seconds}
                                        s
                                      </span>
                                    ) : (
                                      <span>
                                        片段 {operation.clip_id} · 字幕{" "}
                                        {operation.subtitle || "（关闭）"}
                                      </span>
                                    )}
                                  </li>
                                ),
                              )}
                            </ol>
                          )}
                          <div className="editing-suggestion-apply-actions">
                            <button
                              type="button"
                              data-testid="editing-suggestion-apply-all"
                              onClick={() => applySuggestionToDraft(null)}
                              disabled={
                                suggestionIsStale ||
                                rejectionPending ||
                                suggestionPreview.suggestion.plan.operations.length === 0
                              }
                            >
                              全部采用到草稿
                            </button>
                            <button
                              type="button"
                              data-testid="editing-suggestion-apply-selected"
                              onClick={() =>
                                applySuggestionToDraft(
                                  Object.entries(selectedSuggestionOps)
                                    .filter(([, selected]) => selected)
                                    .map(([index]) => Number(index)),
                                )
                              }
                              disabled={
                                suggestionIsStale ||
                                rejectionPending ||
                                !Object.values(selectedSuggestionOps).some(Boolean)
                              }
                            >
                              采用所选到草稿
                            </button>
                            <button
                              type="button"
                              data-testid="editing-suggestion-reject"
                              onClick={rejectSuggestion}
                              disabled={suggestionIsStale || rejectionPending}
                            >
                              拒绝建议
                            </button>
                          </div>
                        </section>

                        <dl className="editing-director-suggestion-explanations">
                          <dt>rationale / 原因</dt>
                          <dd data-testid="editing-suggestion-rationale">
                            {suggestionPreview.suggestion.rationale}
                          </dd>
                          <dt>benefit / 收益</dt>
                          <dd data-testid="editing-suggestion-benefit">
                            {suggestionPreview.suggestion.benefit}
                          </dd>
                          <dt>cost / 创作代价</dt>
                          <dd data-testid="editing-suggestion-cost">
                            {suggestionPreview.suggestion.cost}
                          </dd>
                          <dt>risk / 风险</dt>
                          <dd data-testid="editing-suggestion-risk">
                            {suggestionPreview.suggestion.risk}
                          </dd>
                          <dt>impact / 影响范围</dt>
                          <dd data-testid="editing-suggestion-impact">
                            {suggestionPreview.suggestion.impact}
                          </dd>
                        </dl>
                        {suggestionIsStale && (
                          <p
                            className="editing-director-suggestion-stale"
                            data-testid="editing-suggestion-stale"
                            role="alert"
                          >
                            当前 EditSession
                            版本已变化，这条建议已过期；请重新请求。它不会自动重试、保存或修改时间线。
                          </p>
                        )}
                        <p className="editing-director-suggestion-footer">
                          采用操作会写入时间线草稿；必须显式保存后才会成为新时间线版本。
                        </p>
                      </article>
                    )}
                  </section>
                </Disclosure>
                <section className="editing-session-editor" data-testid="edit-session-editor">
                  <header>
                    <h2>时间线草稿</h2>
                    {dirty && (
                      <span data-testid="edit-session-dirty" role="status">
                        有未保存修改
                      </span>
                    )}
                  </header>
                  {draft.clips.length === 0 ? (
                    <p className="muted" data-testid="edit-session-no-clips">
                      当前 EditSession 没有正式视频片段。
                    </p>
                  ) : (
                    <ol>
                      {draft.clips.map((clip, index) => (
                        <li
                          key={`${clipValue(clip, "id")}-${index}`}
                          data-testid="edit-session-clip"
                        >
                          <div>
                            <strong>
                              {index + 1}.{" "}
                              {clipLabel(shotNumberById, clipValue(clip, "shot_id"), index)}
                            </strong>
                            <small>
                              {clipValue(clip, "artifact_id") ? "正式素材已绑定" : "未绑定正式素材"}
                            </small>
                            <details
                              className="editing-diagnostics"
                              data-testid={`clip-diagnostics-${index}`}
                            >
                              <summary>开发 / 诊断详情（只读）</summary>
                              <small>
                                片段 {clipValue(clip, "id")} · 素材 {clipValue(clip, "artifact_id")}
                              </small>
                              <small>
                                集 {clipValue(clip, "episode_id")} · 场景{" "}
                                {clipValue(clip, "scene_id")} · 镜头 {clipValue(clip, "shot_id")}
                              </small>
                            </details>
                          </div>
                          <label>
                            时长（秒）
                            <input
                              type="number"
                              min="0"
                              step="0.001"
                              aria-label={`镜头 ${index + 1} 时长`}
                              value={clipDuration(clip)}
                              onChange={(event) => updateClipDuration(index, event.target.value)}
                            />
                          </label>
                          <label>
                            入点（秒）
                            <input
                              type="number"
                              min="0"
                              step="0.001"
                              data-testid={`clip-source-in-${index}`}
                              aria-label={`镜头 ${index + 1} 入点`}
                              value={editableValue(clip, "source_in_seconds", "0")}
                              onChange={(event) =>
                                updateClipField(index, "source_in_seconds", event.target.value)
                              }
                            />
                          </label>
                          <label>
                            字幕文本
                            <textarea
                              rows={2}
                              data-testid={`clip-subtitle-${index}`}
                              aria-label={`镜头 ${index + 1} 字幕`}
                              value={editableValue(clip, "subtitle")}
                              onChange={(event) =>
                                updateClipField(index, "subtitle", event.target.value)
                              }
                            />
                          </label>
                          <AudioArtifactPicker
                            key={`${projectId}:${sessionId}:${String(clip.id ?? index)}:audio`}
                            projectId={projectId}
                            label={`镜头 ${index + 1} 配音`}
                            testId={`clip-audio-${index}`}
                            value={editableValue(clip, "audio_id")}
                            defaultLabel="沿用镜头对白"
                            allowMute
                            muted={clip.muted === true}
                            onChange={(artifactId, muted) => {
                              updateClipField(index, "audio_id", artifactId);
                              updateClipField(index, "muted", muted);
                            }}
                          />
                          <label>
                            转场
                            <select
                              data-testid={`clip-transition-${index}`}
                              aria-label={`镜头 ${index + 1} 转场`}
                              value={transitionKind(clip)}
                              onChange={(event) =>
                                updateClipField(
                                  index,
                                  "transition",
                                  event.target.value === "crossfade"
                                    ? { kind: "crossfade", duration_seconds: 0.25 }
                                    : { kind: "cut" },
                                )
                              }
                            >
                              <option value="cut">直接切换</option>
                              <option value="crossfade">交叉淡化</option>
                            </select>
                          </label>
                          <div className="editing-session-clip-actions">
                            <button
                              type="button"
                              data-testid={`move-clip-up-${index}`}
                              onClick={() => moveClip(index, -1)}
                              disabled={index === 0}
                            >
                              上移
                            </button>
                            <button
                              type="button"
                              data-testid={`move-clip-down-${index}`}
                              onClick={() => moveClip(index, 1)}
                              disabled={index === draft.clips.length - 1}
                            >
                              下移
                            </button>
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                  <Disclosure title="背景音乐（可选）">
                    <div className="editing-session-music" data-testid="timeline-music-controls">
                      <AudioArtifactPicker
                        key={`${projectId}:${sessionId}:music`}
                        projectId={projectId}
                        label="背景音乐"
                        testId="timeline-music-artifact"
                        value={metadataValue(draft.metadata, "music_artifact_id")}
                        defaultLabel="不使用背景音乐"
                        onChange={(artifactId) =>
                          updateTimelineMetadata("music_artifact_id", artifactId)
                        }
                      />
                      <label>
                        音乐音量
                        <input
                          type="number"
                          min="0"
                          max="1"
                          step="0.01"
                          data-testid="timeline-music-volume"
                          value={
                            draft.metadata.music_volume === undefined
                              ? "0.12"
                              : String(draft.metadata.music_volume)
                          }
                          onChange={(event) =>
                            updateTimelineMetadata("music_volume", event.target.value)
                          }
                        />
                      </label>
                    </div>
                  </Disclosure>
                  <div className="editing-session-actions">
                    <button
                      type="button"
                      data-testid="save-edit-timeline"
                      onClick={submitSave}
                      disabled={!dirty || save.isPending}
                    >
                      {save.isPending ? "保存中…" : "保存时间线"}
                    </button>
                    <button
                      type="button"
                      data-testid="export-edit-session"
                      onClick={() => exportMutation.mutate()}
                      disabled={exportMutation.isPending}
                    >
                      {exportMutation.isPending ? "正在导出…" : "导出时间线"}
                    </button>
                    <button
                      type="button"
                      data-testid="export-final-film"
                      onClick={() => void runFinalFilmExport()}
                      disabled={dirty || finalFilmPending !== null || save.isPending}
                    >
                      {finalFilmPending === "prepare"
                        ? "准备素材…"
                        : finalFilmPending === "tail"
                          ? "等待成片任务…"
                          : finalFilmPending === "render"
                            ? "正在生成成片…"
                            : "导出成片 MP4"}
                    </button>
                  </div>
                  {dirty && (
                    <p
                      className="editing-final-film-dirty-gate"
                      data-testid="final-film-dirty-gate"
                    >
                      时间线有未保存修改；保存后才能导出成片，避免导出旧的服务器版本。
                    </p>
                  )}
                </section>
              </div>
            </div>
            <section aria-label="历史成片与导出状态">
              <h2>成片历史</h2>
              <p>这些是已经生成的成片；查看不会重新生成。</p>
              <button type="button" onClick={() => void filmHistory.refetch()}>
                刷新成片历史
              </button>
              {filmHistory.isLoading && <p role="status">正在读取成片历史…</p>}
              {filmHistory.isError && <p role="alert">无法读取成片历史，请稍后重试。</p>}
              {filmHistory.data?.length === 0 && <p>此会话还没有成片导出记录。</p>}
              <ul>
                {(filmHistory.data ?? []).map((job) => (
                  <li key={job.node_run_id}>
                    时间线 v{job.timeline_version} · {nodeRunStatusLabel(job.status)}
                    {job.error_summary && <p role="status">{job.error_summary}</p>}
                    {job.result && (
                      <button
                        type="button"
                        onClick={() => {
                          selectHistoryRun(job.node_run_id);
                        }}
                      >
                        查看成片 · v{job.timeline_version}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            {displayedFilm && (
              <section className="final-film-result" data-testid="final-film-result">
                <h2>成片</h2>
                <p>
                  {displayedFilm.timeline_version === currentSessionVersion
                    ? "当前时间线版本的已完成成片"
                    : `历史成片 · 时间线 v${displayedFilm.timeline_version}（当前 v${currentSessionVersion}）`}
                </p>
                <dl>
                  <dt>剪辑会话</dt>
                  <dd data-testid="final-film-session-reference">
                    {shortReference(displayedFilm.edit_session_id)}
                  </dd>
                  <dt>时间线版本</dt>
                  <dd>{displayedFilm.timeline_version}</dd>
                  <dt>时长（秒）</dt>
                  <dd>{displayedFilm.duration_seconds}</dd>
                  <dt>格式</dt>
                  <dd>{displayedFilm.mime_type}</dd>
                  <dt>文件大小（字节）</dt>
                  <dd>{displayedFilm.byte_size}</dd>
                  <dt>存储状态</dt>
                  <dd>
                    {STORAGE_STATE_LABEL[displayedFilm.storage_state] ??
                      displayedFilm.storage_state}
                  </dd>
                </dl>
                <details className="editing-diagnostics" data-testid="final-film-diagnostics">
                  <summary>开发 / 诊断详情（只读）</summary>
                  <p className="muted">
                    素材编号、内容校验值与可播放性断言；仅供排障，不参与创作操作。
                  </p>
                  <dl>
                    <dt>剪辑会话编号</dt>
                    <dd>{displayedFilm.edit_session_id}</dd>
                    <dt>素材编号</dt>
                    <dd>{displayedFilm.artifact_id}</dd>
                    <dt>内容校验值</dt>
                    <dd>{displayedFilm.content_hash}</dd>
                    {displayedFilm.subtitle_artifact_id && (
                      <>
                        <dt>字幕素材编号</dt>
                        <dd>{displayedFilm.subtitle_artifact_id}</dd>
                        <dt>字幕内容校验值</dt>
                        <dd>{displayedFilm.subtitle_content_hash ?? "未提供"}</dd>
                      </>
                    )}
                    <dt>可播放性断言</dt>
                    <dd>
                      {displayedFilm.ffprobe?.assertions &&
                      typeof displayedFilm.ffprobe.assertions === "object" &&
                      !Array.isArray(displayedFilm.ffprobe.assertions)
                        ? Object.entries(
                            displayedFilm.ffprobe.assertions as Record<string, unknown>,
                          )
                            .map(([key, value]) => `${key}=${String(value)}`)
                            .join(" · ")
                        : "未提供"}
                    </dd>
                  </dl>
                </details>
                <FinalFilmPlayback
                  key={`${projectId}:${displayedFilm.artifact_id}`}
                  projectId={projectId}
                  artifactId={displayedFilm.artifact_id}
                />
                <a
                  data-testid="final-film-download"
                  href={artifactContentUrl(projectId, displayedFilm.artifact_id)}
                  download={`dramaforge-final-film-${displayedFilm.content_hash.slice(0, 12)}.mp4`}
                >
                  下载成片 MP4
                </a>
                {displayedFilm.subtitle_artifact_id ? (
                  <a
                    data-testid="final-film-subtitle-download"
                    href={artifactContentUrl(projectId, displayedFilm.subtitle_artifact_id)}
                    download={`dramaforge-final-film-${displayedFilm.content_hash.slice(0, 12)}.srt`}
                  >
                    下载字幕 SRT（{displayedFilm.subtitle_cue_count} 条）
                  </a>
                ) : (
                  <p data-testid="final-film-no-subtitles">此版本无字幕内容，无独立 SRT 文件。</p>
                )}
              </section>
            )}
            {finalFilmError && (
              <p className="flash err" data-testid="final-film-error" role="alert">
                {finalFilmError}
              </p>
            )}

            {exported && (
              <section className="editing-session-export" data-testid="edit-session-export">
                <h2>导出结果</h2>
                <dl>
                  <dt>格式</dt>
                  <dd>{exported.format}</dd>
                  <dt>片段数</dt>
                  <dd>{exported.clip_count}</dd>
                  <dt>时长（秒）</dt>
                  <dd>{exported.duration_seconds}</dd>
                </dl>
              </section>
            )}
          </>
        )}
        {feedback && (
          <p
            className="editing-session-feedback"
            role={feedback.includes("失败") ? "alert" : "status"}
          >
            {feedback}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="qc-project-page" data-testid="editing-workspace">
      <EditingSessionPicker projectId={projectId} onSelect={onSessionSelected} />

      <PageHeader title="剪辑成片" description="选择已有剪辑，或用正式镜头创建时间线。">
        <p className="callout" data-testid="editing-read-only">
          只读预览 · 仅展示已确认的正式视频，不会触发生成或写回生产事实。
        </p>
      </PageHeader>
      {manifest.isLoading && (
        <p className="muted" data-testid="editing-loading">
          正在读取正式剪辑时间线…
        </p>
      )}
      {manifest.isError && (
        <div className="flash err">无法读取剪辑时间线：{errorMessage(manifest.error)}</div>
      )}
      {!manifest.isLoading && !manifest.isError && !manifest.data && (
        <p className="muted" data-testid="editing-empty-project">
          项目暂无可交接的正式视频。
        </p>
      )}
      {!manifest.isError && (
        <button
          type="button"
          data-testid="create-edit-session"
          onClick={() => create.mutate()}
          disabled={create.isPending || manifest.isLoading || !manifest.data}
        >
          {create.isPending ? "正在创建剪辑会话…" : "创建可编辑剪辑会话"}
        </button>
      )}
      {manifest.data && !manifest.isError && (
        <>
          <dl>
            <dt>时长</dt>
            <dd>{manifest.data.timeline.duration_seconds}s</dd>
            <dt>画幅</dt>
            <dd>{manifest.data.timeline.aspect_ratio}</dd>
            <dt>正式镜头</dt>
            <dd>
              {formalVideoClips.length} / {manifest.data.shots.length}
            </dd>
          </dl>
          {isEmptyProject && (
            <p className="muted" data-testid="editing-empty-project">
              项目暂无镜头或正式视频可交接。
            </p>
          )}
          {incompleteShotCount > 0 && (
            <p className="callout" data-testid="editing-partial-state">
              {`已交接 ${formalVideoClips.length} 个正式视频；另有 ${incompleteShotCount} 个镜头尚未确认正式视频，已跳过，不会进入时间线。`}
            </p>
          )}
          <section aria-label="正式时间线">
            <h2>正式时间线</h2>
            {clips.length === 0 ? (
              <p className="muted" data-testid="editing-no-clips">
                暂无正式视频产物可交接。
              </p>
            ) : (
              <ol>
                {clips.map(({ track, clip }, index) => (
                  <li key={clip.id} data-testid="editing-clip">
                    <strong>{track}</strong> · {formatTimelineSeconds(clip.timeline_start_seconds)}–
                    {formatTimelineSeconds(clip.timeline_end_seconds)} 秒 · 片段 {index + 1}
                    {shotNumberById.has(clip.shot_id)
                      ? ` · 镜头 #${shotNumberById.get(clip.shot_id)}`
                      : ""}
                    <br />
                    <small>
                      {clip.source_url
                        ? "正式素材已交付"
                        : clip.artifact_id
                          ? "正式素材待交付"
                          : "未绑定正式素材"}
                    </small>
                  </li>
                ))}
              </ol>
            )}
          </section>
          {feedback && (
            <p
              className="editing-session-feedback"
              role={feedback.includes("失败") ? "alert" : "status"}
            >
              {feedback}
            </p>
          )}
        </>
      )}
    </div>
  );
}
