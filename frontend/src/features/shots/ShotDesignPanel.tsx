import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Disclosure, Field, Textarea } from "../../components/ui";
import { ApiError, updateShotCanvas } from "../../lib/api";
import { shotTypeOptionsFor } from "../../lib/shotLabels";
import { updateShotDesign } from "./api";
import { fetchShotWorkbench } from "./api";
import type { ShotLite, ShotVoiceSettings as ShotVoiceSettingsValue } from "./api";
import { ShotVoiceSettings } from "./ShotVoiceSettings";

export type ShotDesignFocus = "prompts" | "character" | "camera" | "motion" | "look" | "all";

type ShotDesignPanelProps = {
  projectId: string;
  shot: ShotLite;
  onSaved?: () => void | Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  /** Optional Scene-owned draft so closing the Context Sheet cannot drop it. */
  draft?: ShotDesignDraft;
  onDraftChange?: (draft: ShotDesignDraft) => void;
  /**
   * One-shot external draft replacement used by the Director suggestion
   * preview. Applying it only changes this editor's local draft; save remains
   * the existing explicit /design mutation.
   */
  applyDraft?: ShotDesignDraft | null;
  /** Context Dock tool focus. Hidden fields stay in the draft and still save. */
  focus?: ShotDesignFocus;
};

export type ShotDesignDraft = {
  /** Scene-owned canvas draft; omitted by visual-only Director suggestions. */
  dialogue?: string;
  image_prompt: string;
  video_prompt: string;
  director_state: Record<string, unknown>;
  /** Preserve an in-progress JSON edit, including temporarily invalid text. */
  director_state_text?: string;
};

function serializeDirectorState(state: Record<string, unknown> | null | undefined): string {
  return JSON.stringify(state ?? {}, null, 2);
}

function parseDirectorState(text: string): Record<string, unknown> {
  const value = JSON.parse(text.trim() || "{}");
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("导演状态必须是 JSON 对象");
  }
  return value as Record<string, unknown>;
}

function readVoiceSettings(state: Record<string, unknown>): ShotVoiceSettingsValue {
  const value = state.voice;
  if (value === undefined) return { voice_id: null, rate_percent: 0 };
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("配音设置必须是对象");
  }
  const settings = value as Record<string, unknown>;
  const voiceId = settings.voice_id === undefined ? null : settings.voice_id;
  const rate = settings.rate_percent === undefined ? 0 : settings.rate_percent;
  if (voiceId !== null && typeof voiceId !== "string") {
    throw new Error("配音音色必须是音色标识或 null");
  }
  if (typeof rate !== "number" || !Number.isInteger(rate) || rate < -30 || rate > 30) {
    throw new Error("配音语速必须是 -30 到 30 之间的整数");
  }
  return { voice_id: voiceId, rate_percent: rate };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * A save that the server refused because the Shot moved on.
 *
 * The local draft is kept: the user compares it with the server truth and
 * decides whether to reload. Nothing is overwritten automatically.
 */
type SaveConflict = {
  expectedVersion: number;
  actualVersion: number;
  message: string;
};

function conflictOf(error: unknown, attemptedVersion: number): SaveConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const details = error.details as { expected_version?: unknown; actual_version?: unknown } | null;
  const actual = details?.actual_version;
  return {
    expectedVersion:
      typeof details?.expected_version === "number" ? details.expected_version : attemptedVersion,
    actualVersion: typeof actual === "number" ? actual : attemptedVersion + 1,
    message: error.message,
  };
}

function serverDesign(shot: {
  dialogue?: string | null;
  image_prompt?: string | null;
  video_prompt?: string | null;
  director_state?: Record<string, unknown> | null;
}): ShotDesignDraft {
  const directorState = { ...(shot.director_state ?? {}) };
  return {
    dialogue: shot.dialogue ?? "",
    image_prompt: shot.image_prompt ?? "",
    video_prompt: shot.video_prompt ?? "",
    director_state: directorState,
    director_state_text: serializeDirectorState(directorState),
  };
}

/**
 * P3 shot design panel with an explicitly controlled, server-seeded draft.
 *
 * The draft never becomes authoritative by itself: saving uses the current
 * server version, and the parent must refetch the SceneWorkspace before the
 * panel reports the draft as clean. This keeps production actions tied to
 * server truth rather than a browser-only version or prompt.
 */
export function ShotDesignPanel({
  projectId,
  shot,
  onSaved,
  onDirtyChange,
  draft: controlledDraft,
  onDraftChange,
  applyDraft,
  focus = "all",
}: ShotDesignPanelProps) {
  const showCharacter = focus === "all" || focus === "character";
  const showCamera = focus === "all" || focus === "camera";
  const showMotion = focus === "all" || focus === "motion" || focus === "prompts";
  const showLook = focus === "all" || focus === "look" || focus === "prompts";
  const [visual, setVisual] = useState(shot.visual_description);
  // Canvas facts: stored on the Shot itself and written through the CanvasRevision
  // gate (`PATCH /shots/{id}/canvas`), which is the only endpoint that advances
  // visual_description / shot_type / camera_move / duration_seconds.
  const [shotType, setShotType] = useState(shot.shot_type);
  const [cameraMove, setCameraMove] = useState(shot.camera_move ?? "");
  const [durationSeconds, setDurationSeconds] = useState(shot.duration_seconds ?? "");
  const [localDraft, setLocalDraft] = useState<ShotDesignDraft>(() => serverDesign(shot));
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState<SaveConflict | null>(null);
  const draft = controlledDraft ?? localDraft;
  const dialogue = draft.dialogue ?? shot.dialogue ?? "";
  const directorStateText =
    draft.director_state_text ?? serializeDirectorState(draft.director_state);
  const updateDraft = (next: ShotDesignDraft) => {
    if (onDraftChange) {
      onDraftChange(next);
      return;
    }
    setLocalDraft(next);
  };

  let parsedDirectorState: Record<string, unknown> | null = null;
  let voiceSettings: ShotVoiceSettingsValue | null = null;
  try {
    parsedDirectorState = parseDirectorState(directorStateText);
    voiceSettings = readVoiceSettings(parsedDirectorState);
  } catch {
    // Keep invalid advanced JSON intact; structured controls must not erase it.
  }
  const updateVoice = (voice: ShotVoiceSettingsValue) => {
    if (!parsedDirectorState) return;
    const state = { ...parsedDirectorState, voice };
    updateDraft({
      ...draft,
      director_state: state,
      director_state_text: serializeDirectorState(state),
    });
  };

  const serverDirectorStateText = serializeDirectorState(shot.director_state);
  const designDirty =
    draft.image_prompt !== shot.image_prompt ||
    draft.video_prompt !== shot.video_prompt ||
    directorStateText !== serverDirectorStateText;
  const canvasDirty =
    dialogue !== (shot.dialogue ?? "") ||
    visual !== shot.visual_description ||
    shotType !== shot.shot_type ||
    cameraMove !== (shot.camera_move ?? "") ||
    durationSeconds !== (shot.duration_seconds ?? "");
  const dirty = designDirty || canvasDirty;

  // The panel remains mounted while the shot strip changes selection. Reset
  // editor state to the newly selected shot's server read model so edits and
  // subsequent production actions cannot leak across shots. A version change
  // is also a server refresh signal after a successful save.
  useEffect(() => {
    setVisual(shot.visual_description);
    setShotType(shot.shot_type);
    setCameraMove(shot.camera_move ?? "");
    setDurationSeconds(shot.duration_seconds ?? "");
    if (!onDraftChange) {
      setLocalDraft({
        dialogue: shot.dialogue ?? "",
        image_prompt: shot.image_prompt,
        video_prompt: shot.video_prompt,
        director_state: { ...shot.director_state },
        director_state_text: serializeDirectorState(shot.director_state),
      });
    }
  }, [
    shot.id,
    shot.version,
    shot.visual_description,
    shot.shot_type,
    shot.camera_move,
    shot.duration_seconds,
    shot.dialogue,
    shot.image_prompt,
    shot.video_prompt,
    shot.director_state,
    onDraftChange,
  ]);

  useEffect(() => {
    setMessage("");
    setConflict(null);
  }, [shot.id]);

  useEffect(() => {
    if (!applyDraft) return;
    const state = { ...applyDraft.director_state };
    // A visual-only suggestion must not reset the creator's voice or dialogue.
    if (!("voice" in state) && parsedDirectorState?.voice !== undefined) {
      state.voice = parsedDirectorState.voice;
    }
    updateDraft({
      dialogue: applyDraft.dialogue ?? dialogue,
      image_prompt: applyDraft.image_prompt,
      video_prompt: applyDraft.video_prompt,
      director_state: state,
      director_state_text: serializeDirectorState(state),
    });
    setMessage("建议已应用到草稿；请保存镜头设计后才会成为服务器事实");
  }, [applyDraft]); // eslint-disable-line react-hooks/exhaustive-deps -- apply is one-shot

  // Keep the sibling production controls informed without persisting a
  // second copy of the design. The callback is deliberately effect-based so
  // a shot switch cannot synchronously leak the previous shot's dirty state.
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const save = useMutation({
    mutationFn: async () => {
      const directorState = parseDirectorState(directorStateText);
      readVoiceSettings(directorState);
      // Two explicit server gates, in the order that keeps the version chain
      // honest: the CanvasRevision gate owns the Shot's canvas facts and is the
      // only writer of a new Shot version, so the design write that follows must
      // use the version that write produced instead of the stale prop.
      let expectedVersion = shot.version;
      if (canvasDirty) {
        const canvas = await updateShotCanvas(projectId, shot.id, {
          expected_version: expectedVersion,
          visual_description: visual,
          shot_type: shotType,
          camera_move: cameraMove,
          dialogue,
          duration_seconds: durationSeconds,
        });
        expectedVersion = canvas?.shot?.version ?? expectedVersion;
      }
      if (designDirty) {
        await updateShotDesign(projectId, shot.id, {
          expected_version: expectedVersion,
          director_state: directorState,
          image_prompt: draft.image_prompt,
          video_prompt: draft.video_prompt,
        });
      }
      return { canvasChanged: canvasDirty, designChanged: designDirty };
    },
    onSuccess: async (result) => {
      // Do not use the mutation response as a local fake Shot/version. The
      // SceneWorkspace refetch is the only path that can make this draft
      // clean and enable production again.
      setConflict(null);
      await onSaved?.();
      setMessage(
        result.canvasChanged && result.designChanged
          ? "已保存画布版本与设计设置（版本已递增）"
          : result.canvasChanged
            ? "已保存画布版本（版本已递增）"
            : "已保存设计（版本已递增）",
      );
    },
    onError: (error: unknown, _variables, context) => {
      // Keep the draft untouched on a stale-version or validation failure so
      // the user can compare it with the server truth and decide whether to
      // retry. ApiError.message is the backend's real detail.
      void context;
      setConflict(conflictOf(error, shot.version));
      setMessage(`保存失败：${errorMessage(error)}`);
    },
  });

  /** Explicitly adopt the server's design after a version conflict. */
  const reloadServer = useMutation({
    mutationFn: async () => {
      const workbench = await fetchShotWorkbench(projectId, shot.id);
      const freshShot = workbench.shot;
      if (!freshShot) throw new Error("服务器未返回该镜头的当前设计");
      setVisual(freshShot.visual_description);
      setShotType(freshShot.shot_type);
      setCameraMove(freshShot.camera_move ?? "");
      setDurationSeconds(freshShot.duration_seconds ?? "");
      updateDraft(serverDesign(freshShot));
      return freshShot;
    },
    onSuccess: async () => {
      setConflict(null);
      await onSaved?.();
      setMessage("已载入服务器最新设计；请检查后再保存。");
    },
    onError: (error: unknown) => {
      setMessage(`载入服务器设计失败：${errorMessage(error)}`);
    },
  });

  const focusTitle =
    focus === "prompts"
      ? "提示词"
      : focus === "character"
        ? "角色"
        : focus === "camera"
          ? "机位"
          : focus === "motion"
            ? "运动"
            : focus === "look"
              ? "画面"
              : "镜头设计";

  return (
    <div
      className="qc-shot-design-panel"
      data-testid="shot-design-panel"
      data-shot-id={shot.id}
      data-design-focus={focus}
    >
      <header>
        <strong>
          #{shot.shot_number} {focusTitle}
        </strong>
      </header>
      {showCharacter ? (
        <label>
          画面描述
          <textarea
            aria-label="画面描述"
            value={visual}
            onChange={(event) => setVisual(event.target.value)}
          />
        </label>
      ) : null}
      {showCharacter ? (
        <section className="shot-voice-settings" aria-label="对白与配音">
          <strong>对白与配音</strong>
          <Field>
            对白／旁白文本
            <Textarea
              aria-label="对白／旁白文本"
              rows={3}
              value={dialogue}
              onChange={(event) => updateDraft({ ...draft, dialogue: event.target.value })}
              placeholder="填写实际需要朗读的台词或旁白"
            />
          </Field>
          {voiceSettings ? (
            <ShotVoiceSettings projectId={projectId} value={voiceSettings} onChange={updateVoice} />
          ) : (
            <p role="alert">
              高级导演参数中的配音设置暂时无效；原文已保留，请修正后再调整音色和语速。
            </p>
          )}
          <p className="muted">
            保存只更新本镜头设置，不会生成或试听。保存后，到剪辑页显式「导出成片 MP4」时生成配音；
            沿用实例默认的音色会在生成时确定并记录。已有成片不会因修改设置而自动重做。
          </p>
        </section>
      ) : null}
      {showCamera ? (
        <div className="qc-shot-design-canvas-fields" data-testid="shot-design-camera-facts">
          <label>
            镜头类型
            <select
              aria-label="镜头类型"
              value={shotType}
              onChange={(event) => setShotType(event.target.value)}
            >
              {shotTypeOptionsFor(shotType).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            机位运动
            <input
              aria-label="机位运动"
              value={cameraMove}
              onChange={(event) => setCameraMove(event.target.value)}
              placeholder="例如：缓慢推近"
            />
          </label>
          <label>
            时长（秒）
            <input
              aria-label="时长（秒）"
              type="number"
              min="0.1"
              max="30"
              step="0.1"
              value={durationSeconds}
              onChange={(event) => setDurationSeconds(event.target.value)}
            />
          </label>
        </div>
      ) : null}
      {showLook ? (
        <label>
          图片提示词
          <textarea
            aria-label="图片提示词"
            value={draft.image_prompt}
            onChange={(event) => updateDraft({ ...draft, image_prompt: event.target.value })}
          />
        </label>
      ) : null}
      {showMotion ? (
        <label>
          视频提示词
          <textarea
            aria-label="视频提示词"
            value={draft.video_prompt}
            onChange={(event) => updateDraft({ ...draft, video_prompt: event.target.value })}
          />
        </label>
      ) : null}
      {focus === "all" || focus === "camera" || !voiceSettings ? (
        <Disclosure title="高级导演参数（可选）" description="普通创作不需要修改这些参数">
          <label>
            导演状态（JSON）
            <textarea
              aria-label="导演状态"
              value={directorStateText}
              onChange={(event) =>
                updateDraft({ ...draft, director_state_text: event.target.value })
              }
              spellCheck={false}
            />
          </label>
        </Disclosure>
      ) : null}
      <button
        type="button"
        onClick={() => save.mutate()}
        disabled={save.isPending || !dirty}
        data-testid="save-shot-design"
      >
        保存设计
      </button>
      {message && (
        <p className="qc-save-message" data-testid="shot-design-message">
          {message}
        </p>
      )}
      {conflict && (
        <div className="flash err" data-testid="shot-design-conflict" role="alert">
          <p>
            服务器已有更新：本地草稿基于 v{conflict.expectedVersion}，服务器当前为 v
            {conflict.actualVersion}。草稿已保留，不会被自动覆盖。
          </p>
          <button
            type="button"
            data-testid="shot-design-reload-server"
            disabled={reloadServer.isPending}
            onClick={() => reloadServer.mutate()}
          >
            载入服务器最新设计并重新检查
          </button>
        </div>
      )}
      {canvasDirty && (
        <p className="muted" data-testid="shot-design-canvas-note">
          对白、画面描述、镜头类型、机位运动与时长会作为新的画布版本保存，并成为后续执行的事实源。
        </p>
      )}
      {dirty ? (
        <p className="canvas-dirty" data-testid="shot-design-dirty" role="status">
          有未保存的镜头设计
        </p>
      ) : (
        <p className="muted" data-testid="shot-design-saved-state" role="status">
          已保存设计 v{shot.version}；生成执行使用已保存的服务器事实。
        </p>
      )}
    </div>
  );
}
