import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchOpenCutManifest, type OpenCutManifestRead } from "../../lib/api";
import type { components } from "../../shared/api/generated";
import {
  createEditSession,
  exportEditSession,
  fetchEditSession,
  prepareFinalFilm,
  renderFinalFilm,
  requestEditingDirectorSuggestion,
  requestProactiveEditingDirectorSuggestion,
  routeEditingDirectorRepair,
  saveEditTimeline,
  type EditExportRead,
  type FinalFilmRead,
  type EditingRepairRoutingRead,
  type EditSessionRead,
  type EditTimelinePayload,
  type EditingDirectorSuggestionRead,
} from "./api";

type EditingWorkspaceProps = {
  projectId: string;
  /** Exact persisted EditSession identity from the route search. */
  sessionId?: string;
  /** The route owns URL identity and navigates after explicit creation. */
  onSessionCreated?: (sessionId: string) => void;
};

type EditableClip = NonNullable<EditTimelinePayload["clips"]>[number];
type EditableMetadata = NonNullable<EditTimelinePayload["metadata"]>;
type EditableTimeline = {
  clips: EditableClip[];
  metadata: EditableMetadata;
};
type JsonValue = components["schemas"]["JsonValue"];
type EditingSuggestionMutationInput = {
  projectId: string;
  sessionId: string;
  expectedSessionVersion: number;
  userInstruction: string;
  proactive?: boolean;
  sequence: number;
};
type EditingSuggestionPreviewContext = {
  projectId: string;
  sessionId: string;
  sessionVersion: number;
};

function clipsByTrack(manifest: OpenCutManifestRead | undefined) {
  return (manifest?.tracks ?? []).flatMap((track) =>
    track.clips.map((clip) => ({ track: track.name, clip })),
  );
}

function videoClips(manifest: OpenCutManifestRead | undefined) {
  return clipsByTrack(manifest).filter(({ clip }) => clip.track_kind === "video");
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function editableTimeline(session: EditSessionRead): EditableTimeline {
  const rawClips = session.timeline.clips;
  const clips = Array.isArray(rawClips)
    ? rawClips.filter(isJsonObject).map((clip) => ({ ...clip }) as EditableClip)
    : [];
  const rawMetadata = session.timeline.metadata;
  const metadata = isJsonObject(rawMetadata) ? { ...rawMetadata } : {};
  return { clips, metadata };
}

function clipDuration(clip: EditableClip): string {
  const value = clip.duration_seconds;
  return typeof value === "number" || typeof value === "string" ? String(value) : "";
}

function clipValue(clip: EditableClip, key: string): string {
  const value = clip[key];
  return value === undefined || value === null ? "—" : String(value);
}

function sameTimeline(left: EditableTimeline | null, right: EditableTimeline | null): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isSessionVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function timelineForSave(
  timeline: EditableTimeline,
): Pick<EditTimelinePayload, "clips" | "metadata"> {
  // Deliberately construct the allow-listed payload. A session's readonly
  // production_lineage never enters this object, even if a caller hands the
  // component an object with extra keys at runtime.
  return {
    clips: timeline.clips.map((clip) => ({ ...clip })),
    metadata: { ...timeline.metadata },
  };
}

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
}: EditingWorkspaceProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EditableTimeline | null>(null);
  const [baseline, setBaseline] = useState<EditableTimeline | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [exported, setExported] = useState<EditExportRead | null>(null);
  const [finalFilm, setFinalFilm] = useState<FinalFilmRead | null>(null);
  const [finalFilmError, setFinalFilmError] = useState<string | null>(null);
  const [finalFilmPending, setFinalFilmPending] = useState<"prepare" | "render" | null>(null);
  const [suggestionInstruction, setSuggestionInstruction] = useState("");
  const [suggestionPreview, setSuggestionPreview] = useState<EditingDirectorSuggestionRead | null>(
    null,
  );
  const [suggestionPreviewContext, setSuggestionPreviewContext] =
    useState<EditingSuggestionPreviewContext | null>(null);
  const [suggestionStale, setSuggestionStale] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [repairRouting, setRepairRouting] = useState<EditingRepairRoutingRead | null>(null);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [selectedSuggestionOps, setSelectedSuggestionOps] = useState<Record<number, boolean>>({});
  const suggestionSequenceRef = useRef(0);
  const suggestionIdentityRef = useRef<EditingSuggestionPreviewContext | null>(null);

  const hasSession = Boolean(sessionId);
  const manifest = useQuery({
    queryKey: ["opencut-manifest", projectId],
    queryFn: () => fetchOpenCutManifest(projectId),
    enabled: Boolean(projectId) && projectId !== "demo" && !hasSession,
  });
  const persistedSession = useQuery({
    queryKey: ["edit-session", projectId, sessionId],
    queryFn: () => fetchEditSession(projectId, sessionId!),
    enabled: Boolean(projectId) && projectId !== "demo" && hasSession,
  });

  const currentSessionVersion = persistedSession.data?.version;
  suggestionIdentityRef.current =
    sessionId && isSessionVersion(currentSessionVersion)
      ? { projectId, sessionId, sessionVersion: currentSessionVersion }
      : null;

  const dirty = useMemo(
    () => draft !== null && baseline !== null && !sameTimeline(draft, baseline),
    [baseline, draft],
  );

  useEffect(() => {
    // Route identity is the isolation boundary: never carry a local timeline
    // or export result from session A into session B or the manifest preview.
    setDraft(null);
    setBaseline(null);
    setFeedback(null);
    setExported(null);
    setFinalFilm(null);
    setFinalFilmError(null);
    setFinalFilmPending(null);
    setSuggestionInstruction("");
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    setRepairRouting(null);
    setRepairError(null);
    setSelectedSuggestionOps({});
    suggestionSequenceRef.current += 1;
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!persistedSession.data) return;
    // A failed save leaves the query data unchanged, so this effect does not
    // discard the user's dirty draft. If a clean session is refreshed, seed
    // from the new server response.
    if (dirty) return;
    const next = editableTimeline(persistedSession.data);
    setDraft(next);
    setBaseline(next);
  }, [dirty, persistedSession.data]);

  const create = useMutation({
    mutationFn: () => createEditSession(projectId),
    onSuccess: (created) => {
      setFeedback(null);
      onSessionCreated?.(created.id);
    },
    onError: (error: unknown) => {
      setFeedback(`创建 EditSession 失败：${errorMessage(error)}`);
    },
  });

  const save = useMutation({
    mutationFn: () => {
      if (!sessionId || !draft) throw new Error("没有可保存的 EditSession 草稿");
      return saveEditTimeline(projectId, sessionId, timelineForSave(draft));
    },
    onSuccess: (saved) => {
      const next = editableTimeline(saved);
      setDraft(next);
      setBaseline(next);
      setFeedback("时间线已保存（服务器响应已成为新的 clean baseline）");
      setExported(null);
      setSuggestionPreview(null);
      setSuggestionPreviewContext(null);
      setSuggestionStale(false);
      setSuggestionError(null);
      setSelectedSuggestionOps({});
      queryClient.setQueryData(["edit-session", projectId, sessionId], saved);
    },
    onError: (error: unknown) => {
      // Keep draft/baseline untouched so failed saves leave the editor dirty.
      setFeedback(`保存时间线失败：${errorMessage(error)}`);
    },
  });

  const exportMutation = useMutation({
    mutationFn: () => {
      if (!sessionId) throw new Error("请先创建或选择 EditSession");
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

  async function runFinalFilmExport() {
    if (!sessionId || !isSessionVersion(currentSessionVersion)) {
      setFinalFilmError("请先创建并加载 EditSession 后再导出 Final Film。");
      return;
    }
    const idempotencyKey = `final-${projectId}-${sessionId}-${currentSessionVersion}`;
    try {
      setFinalFilmError(null);
      setFinalFilmPending("prepare");
      await prepareFinalFilm(projectId, sessionId, currentSessionVersion);
      setFinalFilmPending("render");
      const result = await renderFinalFilm(
        projectId,
        sessionId,
        currentSessionVersion,
        idempotencyKey,
      );
      setFinalFilm(result);
      setFinalFilmPending(null);
    } catch (error: unknown) {
      setFinalFilmError(`Final Film 导出失败：${errorMessage(error)}`);
      setFinalFilmPending(null);
    }
  }

  const suggestionRequest = useMutation<
    EditingDirectorSuggestionRead,
    unknown,
    EditingSuggestionMutationInput
  >({
    mutationFn: ({
      projectId: requestProjectId,
      sessionId: requestSessionId,
      expectedSessionVersion,
      userInstruction,
      proactive = false,
    }) =>
      proactive
        ? requestProactiveEditingDirectorSuggestion(
            requestProjectId,
            requestSessionId,
            expectedSessionVersion,
          )
        : requestEditingDirectorSuggestion(requestProjectId, requestSessionId, {
            expected_session_version: expectedSessionVersion,
            user_instruction: userInstruction,
          }),
    onSuccess: (result, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== variables.projectId ||
        currentIdentity.sessionId !== variables.sessionId ||
        currentIdentity.sessionVersion !== variables.expectedSessionVersion
      ) {
        // A late response is intentionally ignored. It cannot become the
        // preview for a newer session/version/request.
        return;
      }
      setSuggestionPreview(result);
      setSuggestionPreviewContext(currentIdentity);
      setSuggestionStale(false);
      setSuggestionError(null);
      setSelectedSuggestionOps({});
    },
    onError: (error: unknown, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== variables.projectId ||
        currentIdentity.sessionId !== variables.sessionId ||
        currentIdentity.sessionVersion !== variables.expectedSessionVersion
      ) {
        // A late error is just as stale as a late success; it must not replace
        // the error/preview belonging to the current route and version.
        return;
      }
      setSuggestionPreview(null);
      setSuggestionPreviewContext(null);
      setSuggestionStale(false);
      setSuggestionError(`建议请求失败：${errorMessage(error)}`);
      setSelectedSuggestionOps({});
    },
  });
  const repairRoutingMutation = useMutation<
    EditingRepairRoutingRead,
    unknown,
    { sequence: number }
  >({
    mutationFn: () => {
      if (!sessionId || !persistedSession.data || !isSessionVersion(currentSessionVersion)) {
        throw new Error("无法判定修复路由：当前 EditSession 版本尚未加载。");
      }
      return routeEditingDirectorRepair(projectId, sessionId, {
        expected_session_version: currentSessionVersion,
        user_instruction: suggestionInstruction.trim(),
      });
    },
    onSuccess: (result, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== projectId ||
        currentIdentity.sessionId !== sessionId ||
        currentIdentity.sessionVersion !== result.session_version
      ) {
        return;
      }
      setRepairRouting(result);
      setRepairError(null);
    },
    onError: (error: unknown, variables) => {
      if (variables.sequence !== suggestionSequenceRef.current) return;
      setRepairRouting(null);
      setRepairError(`修复路由判定失败：${errorMessage(error)}`);
    },
  });
  const suggestionRequestResetRef = useRef(suggestionRequest.reset);
  suggestionRequestResetRef.current = suggestionRequest.reset;
  const repairRoutingMutationResetRef = useRef(repairRoutingMutation.reset);
  repairRoutingMutationResetRef.current = repairRoutingMutation.reset;

  useEffect(() => {
    // Route changes invalidate any in-flight mutation state as well as the
    // local preview. The sequence guard above still ignores its eventual
    // response if the transport cannot be cancelled.
    suggestionRequestResetRef.current();
    repairRoutingMutationResetRef.current();
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!suggestionPreview || !suggestionPreviewContext) return;
    const currentIdentity = suggestionIdentityRef.current;
    if (
      !currentIdentity ||
      currentIdentity.projectId !== suggestionPreviewContext.projectId ||
      currentIdentity.sessionId !== suggestionPreviewContext.sessionId ||
      currentIdentity.sessionVersion !== suggestionPreviewContext.sessionVersion
    ) {
      setSuggestionStale(true);
    }
  }, [currentSessionVersion, projectId, sessionId, suggestionPreview, suggestionPreviewContext]);

  const suggestionIsStale =
    suggestionPreview !== null &&
    suggestionPreviewContext !== null &&
    (suggestionStale ||
      suggestionPreviewContext.projectId !== projectId ||
      suggestionPreviewContext.sessionId !== sessionId ||
      suggestionPreviewContext.sessionVersion !== currentSessionVersion);

  function submitSuggestion() {
    const userInstruction = suggestionInstruction.trim();
    if (!sessionId || !persistedSession.data || !isSessionVersion(currentSessionVersion)) {
      setSuggestionError("无法请求建议：当前 EditSession 版本尚未加载。");
      return;
    }
    if (!userInstruction) {
      setSuggestionError("请输入导演要求后再请求建议。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    suggestionRequest.mutate({
      projectId,
      sessionId,
      expectedSessionVersion: currentSessionVersion,
      userInstruction,
      sequence,
    });
    setSelectedSuggestionOps({});
  }

  function submitProactiveSuggestion() {
    if (!sessionId || !persistedSession.data || !isSessionVersion(currentSessionVersion)) {
      setSuggestionError("无法主动分析：当前 EditSession 版本尚未加载。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    suggestionRequest.mutate({
      projectId,
      sessionId,
      expectedSessionVersion: currentSessionVersion,
      userInstruction: "",
      proactive: true,
      sequence,
    });
    setSelectedSuggestionOps({});
  }

  function submitRepairRouting() {
    if (!sessionId || !persistedSession.data || !isSessionVersion(currentSessionVersion)) {
      setRepairError("无法判定修复路由：当前 EditSession 版本尚未加载。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setRepairRouting(null);
    setRepairError(null);
    repairRoutingMutation.mutate({ sequence });
  }

  function moveClip(index: number, offset: -1 | 1) {
    setDraft((current) => {
      if (!current) return current;
      const target = index + offset;
      if (target < 0 || target >= current.clips.length) return current;
      const clips = current.clips.map((clip) => ({ ...clip }));
      [clips[index], clips[target]] = [clips[target], clips[index]];
      const orderedClips = clips.map((clip, clipIndex) =>
        Object.prototype.hasOwnProperty.call(clip, "order")
          ? { ...clip, order: clipIndex + 1 }
          : clip,
      );
      return { ...current, clips: orderedClips };
    });
    setFeedback(null);
    setExported(null);
  }

  function applySuggestionToDraft(operationIndices: number[] | null) {
    if (!suggestionPreview || !draft) return;
    const operations = suggestionPreview.suggestion.plan.operations;
    const indices = operationIndices ?? operations.map((_operation, index) => index);
    if (indices.length === 0) {
      setFeedback("请先选择至少一条剪辑操作。");
      return;
    }

    let nextClips = draft.clips.map((clip) => ({ ...clip }));
    for (const index of indices) {
      const operation = operations[index];
      if (!operation) continue;
      if (operation.operation === "reorder_clips") {
        const byId = new Map(
          nextClips
            .filter((clip) => typeof clip.id === "string")
            .map((clip) => [clip.id as string, clip]),
        );
        const reordered = operation.clip_ids
          .map((clipId) => byId.get(clipId))
          .filter((clip): clip is EditableClip => clip !== undefined);
        if (reordered.length !== nextClips.length) {
          setFeedback("无法应用建议：重排片段不在当前草稿中，请重新请求。");
          return;
        }
        nextClips = reordered.map((clip, order) => ({
          ...clip,
          order: order + 1,
        }));
      } else if (operation.operation === "set_clip_duration") {
        nextClips = nextClips.map((clip) =>
          clip.id === operation.clip_id || clipValue(clip, "shot_id") === operation.clip_id
            ? { ...clip, duration_seconds: operation.duration_seconds }
            : clip,
        );
      }
    }
    setDraft({
      ...draft,
      clips: nextClips,
      metadata: {
        ...draft.metadata,
        director_suggestion_applied: suggestionPreview.suggestion.base_session_version,
      },
    });
    setFeedback("建议已应用到时间线草稿；请检查后显式保存。");
    setExported(null);
  }

  function rejectSuggestion() {
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSelectedSuggestionOps({});
    setFeedback("已拒绝当前剪辑建议预览。");
  }

  function updateClipDuration(index: number, value: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) return;
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        clips: current.clips.map((clip, clipIndex) =>
          clipIndex === index ? { ...clip, duration_seconds: parsed } : { ...clip },
        ),
      };
    });
    setFeedback(null);
    setExported(null);
  }

  const clips = clipsByTrack(manifest.data);
  const formalVideoClips = videoClips(manifest.data);
  const formalShotIds = new Set(formalVideoClips.map(({ clip }) => clip.shot_id));
  const incompleteShotCount =
    manifest.data?.shots.filter((shot) => !formalShotIds.has(shot.shot_id)).length ?? 0;
  const isEmptyProject = manifest.data?.shots.length === 0 && clips.length === 0;

  if (hasSession) {
    return (
      <div className="qc-project-page" data-testid="editing-workspace" data-session-id={sessionId}>
        <header className="qc-page-heading">
          <p>剪辑</p>
          <h1>持久化 EditSession</h1>
          <span>
            当前会话来自服务器；编辑层只保存时间线，不会反向修改 Shot 或 Production Graph。
          </span>
          <p className="callout" data-testid="editing-session-read-only">
            production lineage 只读 · 不渲染媒体、不调用 Provider。
          </p>
        </header>

        {persistedSession.isLoading && (
          <p className="muted" data-testid="editing-session-loading">
            正在读取 EditSession…
          </p>
        )}
        {persistedSession.isError && (
          <div className="flash err" data-testid="editing-session-error">
            无法读取 EditSession：{errorMessage(persistedSession.error)}
          </div>
        )}

        {persistedSession.data && draft && baseline && (
          <>
            <section className="editing-session-facts" data-testid="edit-session-facts">
              <h2>{persistedSession.data.name}</h2>
              <dl>
                <dt>Session ID</dt>
                <dd>{persistedSession.data.id}</dd>
                <dt>状态</dt>
                <dd>{persistedSession.data.status}</dd>
                <dt>版本</dt>
                <dd data-testid="edit-session-version">
                  {isSessionVersion(persistedSession.data.version)
                    ? `v${persistedSession.data.version}`
                    : "尚未加载"}
                </dd>
                <dt>镜头数量</dt>
                <dd>{draft.clips.length}</dd>
              </dl>
              <h3>Production lineage（只读）</h3>
              <pre data-testid="edit-session-lineage">
                {formatJson(persistedSession.data.production_lineage)}
              </pre>
            </section>

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
                disabled={suggestionRequest.isPending || !isSessionVersion(currentSessionVersion)}
              >
                {suggestionRequest.isPending ? "正在分析…" : "主动分析剪辑节奏"}
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
                  disabled={suggestionRequest.isPending}
                />
              </label>
              <button
                type="button"
                data-testid="request-editing-director-suggestion"
                onClick={submitSuggestion}
                disabled={
                  suggestionRequest.isPending ||
                  !suggestionInstruction.trim() ||
                  !isSessionVersion(currentSessionVersion)
                }
              >
                {suggestionRequest.isPending ? "正在请求建议…" : "请求剪辑建议"}
              </button>

              {suggestionRequest.isPending && (
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
                disabled={
                  repairRoutingMutation.isPending || !isSessionVersion(currentSessionVersion)
                }
              >
                {repairRoutingMutation.isPending ? "正在判定…" : "判断是否需要生产 Repair"}
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
                        Repair Proposal 已创建但不会自动执行；请到审片/镜头生产层打开 Repair Plan
                        人工确认后执行。
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
                  data-base-session-version={suggestionPreview.suggestion.base_session_version}
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
                    <dd data-testid="editing-suggestion-item-id">{suggestionPreview.item_id}</dd>
                    <dt>基于版本</dt>
                    <dd data-testid="editing-suggestion-base-version">
                      v{suggestionPreview.suggestion.base_session_version}
                    </dd>
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
                        {suggestionPreview.suggestion.plan.operations.map((operation, index) => (
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
                                disabled={suggestionIsStale}
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
                            ) : (
                              <span>
                                片段 {operation.clip_id} · 时长 {operation.duration_seconds}s
                              </span>
                            )}
                            <pre>{formatJson(operation)}</pre>
                          </li>
                        ))}
                      </ol>
                    )}
                    <div className="editing-suggestion-apply-actions">
                      <button
                        type="button"
                        data-testid="editing-suggestion-apply-all"
                        onClick={() => applySuggestionToDraft(null)}
                        disabled={
                          suggestionIsStale ||
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
                          suggestionIsStale || !Object.values(selectedSuggestionOps).some(Boolean)
                        }
                      >
                        采用所选到草稿
                      </button>
                      <button
                        type="button"
                        data-testid="editing-suggestion-reject"
                        onClick={rejectSuggestion}
                        disabled={suggestionIsStale}
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
                    <li key={`${clipValue(clip, "id")}-${index}`} data-testid="edit-session-clip">
                      <div>
                        <strong>
                          {index + 1}. 镜头 {clipValue(clip, "shot_id")} · Artifact{" "}
                          {clipValue(clip, "artifact_id")}
                        </strong>
                        <small>
                          {clipValue(clip, "episode_id")} · {clipValue(clip, "scene_id")} ·
                          保留其它片段字段
                        </small>
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
              <div className="editing-session-actions">
                <button
                  type="button"
                  data-testid="save-edit-timeline"
                  onClick={() => save.mutate()}
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
                  {exportMutation.isPending ? "读取导出…" : "导出时间线"}
                </button>
                <button
                  type="button"
                  data-testid="export-final-film"
                  onClick={() => void runFinalFilmExport()}
                  disabled={finalFilmPending !== null || save.isPending}
                >
                  {finalFilmPending === "prepare"
                    ? "准备尾链…"
                    : finalFilmPending === "render"
                      ? "渲染 Final Film…"
                      : "导出 Final Film Artifact"}
                </button>
              </div>
            </section>

            {finalFilm && (
              <section className="final-film-result" data-testid="final-film-result">
                <h2>Final Film Artifact</h2>
                <dl>
                  <dt>EditSession</dt>
                  <dd>{finalFilm.edit_session_id}</dd>
                  <dt>Timeline version</dt>
                  <dd>{finalFilm.timeline_version}</dd>
                  <dt>Artifact</dt>
                  <dd>{finalFilm.artifact_id}</dd>
                  <dt>duration_seconds</dt>
                  <dd>{finalFilm.duration_seconds}</dd>
                  <dt>mime_type</dt>
                  <dd>{finalFilm.mime_type}</dd>
                  <dt>byte_size</dt>
                  <dd>{finalFilm.byte_size}</dd>
                  <dt>content_hash</dt>
                  <dd>{finalFilm.content_hash}</dd>
                  <dt>storage_state</dt>
                  <dd>{finalFilm.storage_state}</dd>
                  <dt>可播放性断言</dt>
                  <dd>
                    {finalFilm.ffprobe?.assertions &&
                    typeof finalFilm.ffprobe.assertions === "object" &&
                    !Array.isArray(finalFilm.ffprobe.assertions)
                      ? Object.entries(finalFilm.ffprobe.assertions as Record<string, unknown>)
                          .map(([key, value]) => `${key}=${String(value)}`)
                          .join(" · ")
                      : "未提供"}
                  </dd>
                </dl>
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
                  <dt>format</dt>
                  <dd>{exported.format}</dd>
                  <dt>clip_count</dt>
                  <dd>{exported.clip_count}</dd>
                  <dt>duration_seconds</dt>
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
      <header className="qc-page-heading">
        <p>剪辑</p>
        <h1>OpenCut 剪辑交接</h1>
        <span>未选择持久化 EditSession；下面仅是正式生产 manifest 预览。</span>
        <p className="callout" data-testid="editing-read-only">
          只读交接预览 · 仅展示已确认的正式视频，不会触发生成或写回生产事实。
        </p>
      </header>
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
          {projectId === "demo"
            ? "演示项目没有真实 OpenCut manifest。"
            : "项目暂无可交接的正式视频。"}
        </p>
      )}
      {!manifest.isError && (
        <button
          type="button"
          data-testid="create-edit-session"
          onClick={() => create.mutate()}
          disabled={
            create.isPending || manifest.isLoading || projectId === "demo" || !manifest.data
          }
        >
          {create.isPending ? "正在创建 EditSession…" : "创建可编辑 EditSession"}
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
                {clips.map(({ track, clip }) => (
                  <li key={clip.id} data-testid="editing-clip">
                    <strong>{track}</strong> · {clip.timeline_start_seconds}s–
                    {clip.timeline_end_seconds}s · 项目 {manifest.data.project_id} · 场景{" "}
                    {clip.scene_id} · 镜头 {clip.shot_id}
                    <br />
                    <small>
                      正式 Artifact {clip.artifact_id ?? "未知"}
                      {clip.source_url ? ` · 存储 ${clip.source_url}` : ""}
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
