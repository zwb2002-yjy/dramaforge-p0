import { useEffect, useReducer, useRef } from "react";
import { formalClipSource, type PublicCutSelection } from "./publicCutSource";
import type { components } from "../../shared/api/generated";
import type {
  EditSessionRead,
  EditTimelinePayload,
  TimelineWrite,
  EditingDirectorSuggestionRead,
} from "./api";

export type EditableClip = NonNullable<EditTimelinePayload["clips"]>[number];
export type EditableMetadata = NonNullable<EditTimelinePayload["metadata"]>;
export type EditableTimeline = {
  schema_version?: number;
  clips: EditableClip[];
  metadata: EditableMetadata;
};
type JsonValue = components["schemas"]["JsonValue"];
type Operations = EditingDirectorSuggestionRead["suggestion"]["plan"]["operations"];
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
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
  return {
    ...(typeof session.timeline.schema_version === "number" && {
      schema_version: session.timeline.schema_version,
    }),
    clips,
    metadata,
  };
}

export function timelineForSave(timeline: EditableTimeline): TimelineWrite {
  // Deliberately construct the allow-listed payload. A session's readonly
  // production_lineage never enters this object, even if a caller hands the
  // component an object with extra keys at runtime.
  return {
    ...(timeline.schema_version !== undefined && { schema_version: timeline.schema_version }),
    clips: timeline.clips.map((clip) => ({ ...clip })),
    metadata: { ...timeline.metadata },
  };
}

export type TimelineSaveInput = {
  projectId: string;
  sessionId: string;
  expectedVersion: number;
  timeline: TimelineWrite;
  scopeToken: symbol;
};

type DraftState = {
  scope: string;
  draft: EditableTimeline | null;
  baseline: EditableTimeline | null;
  baselineVersion: number | null;
};
type Action = { scope: string } & (
  | { type: "seed"; session?: EditSessionRead }
  | { type: "saved"; session: EditSessionRead; input: TimelineSaveInput }
  | { type: "edit"; update: (draft: EditableTimeline) => EditableTimeline }
);
const empty = (scope: string): DraftState => ({
  scope,
  draft: null,
  baseline: null,
  baselineVersion: null,
});
function reducer(state: DraftState, action: Action): DraftState {
  if (action.type === "seed") {
    const current = state.scope === action.scope ? state : empty(action.scope);
    if (!action.session || !same(current.draft, current.baseline)) return current;
    if (current.baselineVersion !== null && action.session.version < current.baselineVersion)
      return current;
    const next = editableTimeline(action.session);
    if (current.baselineVersion === action.session.version && same(current.baseline, next))
      return current;
    return {
      scope: action.scope,
      draft: next,
      baseline: next,
      baselineVersion: action.session.version,
    };
  }
  if (action.scope !== state.scope) return state;
  if (action.type === "saved") {
    if (action.input.expectedVersion !== state.baselineVersion) return state;
    const next = editableTimeline(action.session);
    return {
      scope: action.scope,
      draft: same(state.draft, action.input.timeline) ? next : state.draft,
      baseline: next,
      baselineVersion: action.session.version,
    };
  }
  if (action.type === "edit" && state.draft) return { ...state, draft: action.update(state.draft) };
  return state;
}

/** Owns draft/baseline/version transitions; never writes production or sends a request. */
export function useTimelineDraft(
  projectId: string,
  sessionId: string | undefined,
  persisted?: EditSessionRead,
) {
  const scope = JSON.stringify([projectId, sessionId]);
  const currentScope = useRef({ key: scope, token: Symbol(scope) });
  if (currentScope.current.key !== scope)
    currentScope.current = { key: scope, token: Symbol(scope) };
  const scopeToken = currentScope.current.token;
  const [stored, dispatch] = useReducer(reducer, scope, empty);
  const state = stored.scope === scope ? stored : empty(scope);
  const dirty =
    state.draft !== null && state.baseline !== null && !same(state.draft, state.baseline);
  useEffect(() => {
    dispatch({
      type: "seed",
      scope,
      session:
        persisted && persisted.id === sessionId && persisted.project_id === projectId
          ? persisted
          : undefined,
    });
  }, [scope, projectId, sessionId, persisted, dirty]);
  const edit = (update: (draft: EditableTimeline) => EditableTimeline) =>
    dispatch({ type: "edit", scope, update });
  function captureSave(): TimelineSaveInput {
    if (!sessionId || !state.draft) throw new Error("没有可保存的剪辑会话草稿");
    if (
      !Number.isInteger(state.baselineVersion) ||
      state.baselineVersion === null ||
      state.baselineVersion < 1
    ) {
      throw new Error("当前 EditSession 版本尚未加载，无法安全保存。");
    }
    return {
      projectId,
      sessionId,
      expectedVersion: state.baselineVersion,
      timeline: timelineForSave(state.draft),
      scopeToken,
    };
  }
  const isCurrentSave = (input: TimelineSaveInput) =>
    input.scopeToken === currentScope.current.token;
  const acceptSaved = (session: EditSessionRead, input: TimelineSaveInput) => {
    if (
      !isCurrentSave(input) ||
      session.project_id !== projectId ||
      session.id !== sessionId ||
      state.baselineVersion !== input.expectedVersion ||
      session.version < input.expectedVersion
    )
      return false;
    dispatch({ type: "saved", scope, session, input });
    return true;
  };
  function updateClipField(index: number, key: string, value: JsonValue) {
    edit((draft) => ({
      ...draft,
      clips: draft.clips.map((clip, i) =>
        i === index ? ({ ...clip, [key]: value } as EditableClip) : clip,
      ),
    }));
  }
  function updateTimelineMetadata(key: string, value: JsonValue) {
    edit((draft) => ({ ...draft, metadata: { ...draft.metadata, [key]: value } }));
  }
  function replaceClip(index: number, clip: EditableClip) {
    edit((draft) => ({
      ...draft,
      clips: draft.clips.map((current, i) =>
        i === index && current.id === clip.id ? { ...clip } : current,
      ),
    }));
  }
  function usePublicSource(selection: PublicCutSelection, selectedId: string) {
    const { action, source, seconds, resetCrop } = selection;
    const id =
      action === "append"
        ? `clip-${Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("")}`
        : selectedId;
    edit((draft) => {
      if (action === "append")
        return {
          ...draft,
          schema_version: 2,
          clips: [
            ...draft.clips,
            {
              id,
              order: draft.clips.length + 1,
              duration_seconds: seconds,
              source,
            },
          ],
        };
      const index = draft.clips.findIndex((c) => c.id === selectedId);
      if (index < 0) return draft;
      return {
        ...draft,
        schema_version: 2,
        clips: draft.clips.map((clip, i) => {
          if (i !== index) return clip;
          if (action === "audio")
            return { ...clip, audio_source: source, audio_id: null, muted: false };
          return {
            ...clip,
            source,
            ...(resetCrop ? { source_in_seconds: 0, source_out_seconds: seconds } : {}),
          };
        }),
      };
    });
    return id;
  }
  function moveClip(index: number, offset: -1 | 1) {
    reorderClip(index, index + offset);
  }
  function reorderClip(index: number, target: number) {
    edit((draft) => {
      if (index < 0 || index >= draft.clips.length || target < 0 || target >= draft.clips.length)
        return draft;
      const clips = draft.clips.map((clip) => ({ ...clip }));
      const [moved] = clips.splice(index, 1);
      clips.splice(target, 0, moved);
      return {
        ...draft,
        clips: clips.map((clip, order) =>
          Object.prototype.hasOwnProperty.call(clip, "order")
            ? { ...clip, order: order + 1 }
            : clip,
        ),
      };
    });
  }
  function applySuggestion(operations: Operations, baseVersion: number): string | null {
    const draft = state.draft;
    if (!draft) return "没有可编辑的时间线草稿。";
    let clips = draft.clips.map((clip) => ({ ...clip }));
    for (const operation of operations) {
      if (operation.operation === "reorder_clips") {
        const byId = new Map(
          clips.filter((clip) => typeof clip.id === "string").map((clip) => [clip.id, clip]),
        );
        const reordered = operation.clip_ids.map((id) => byId.get(id));
        if (
          reordered.length !== clips.length ||
          new Set(operation.clip_ids).size !== clips.length ||
          reordered.some((clip) => !clip)
        )
          return "无法应用建议：重排片段不在当前草稿中，请重新请求。";
        clips = reordered.map((clip, index) => ({ ...clip!, order: index + 1 }));
      } else if (operation.operation === "set_clip_duration") {
        clips = clips.map((clip) =>
          clip.id === operation.clip_id || formalClipSource(clip)?.shotId === operation.clip_id
            ? { ...clip, duration_seconds: operation.duration_seconds }
            : clip,
        );
      } else if (operation.operation === "set_clip_subtitle") {
        clips = clips.map((clip) =>
          clip.id === operation.clip_id || formalClipSource(clip)?.shotId === operation.clip_id
            ? { ...clip, subtitle: operation.subtitle }
            : clip,
        );
      }
    }
    edit((current) => ({
      ...current,
      clips,
      metadata: { ...current.metadata, director_suggestion_applied: baseVersion },
    }));
    return null;
  }
  return {
    ...state,
    dirty,
    captureSave,
    isCurrentSave,
    acceptSaved,
    updateClipField,
    usePublicSource,
    replaceClip,
    updateTimelineMetadata,
    moveClip,
    reorderClip,
    applySuggestion,
  };
}
