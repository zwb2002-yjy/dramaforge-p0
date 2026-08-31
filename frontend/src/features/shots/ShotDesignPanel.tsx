import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { updateShotDesign } from "./api";
import type { ShotLite } from "./api";

type ShotDesignPanelProps = {
  projectId: string;
  shot: ShotLite;
  onSaved?: () => void | Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  /**
   * One-shot external draft replacement used by the Director suggestion
   * preview. Applying it only changes this editor's local draft; save remains
   * the existing explicit /design mutation.
   */
  applyDraft?: ShotDesignDraft | null;
};

export type ShotDesignDraft = {
  image_prompt: string;
  video_prompt: string;
  director_state: Record<string, unknown>;
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
  applyDraft,
}: ShotDesignPanelProps) {
  const [visual, setVisual] = useState(shot.visual_description);
  const [imagePrompt, setImagePrompt] = useState(shot.image_prompt);
  const [videoPrompt, setVideoPrompt] = useState(shot.video_prompt);
  const [directorStateText, setDirectorStateText] = useState(() =>
    serializeDirectorState(shot.director_state),
  );
  const [message, setMessage] = useState("");

  const serverDirectorStateText = serializeDirectorState(shot.director_state);
  const dirty =
    imagePrompt !== shot.image_prompt ||
    videoPrompt !== shot.video_prompt ||
    directorStateText !== serverDirectorStateText;

  // The panel remains mounted while the shot strip changes selection. Reset
  // editor state to the newly selected shot's server read model so edits and
  // subsequent production actions cannot leak across shots. A version change
  // is also a server refresh signal after a successful save.
  useEffect(() => {
    setVisual(shot.visual_description);
    setImagePrompt(shot.image_prompt);
    setVideoPrompt(shot.video_prompt);
    setDirectorStateText(serializeDirectorState(shot.director_state));
  }, [
    shot.id,
    shot.version,
    shot.visual_description,
    shot.image_prompt,
    shot.video_prompt,
    shot.director_state,
  ]);

  useEffect(() => {
    setMessage("");
  }, [shot.id]);

  useEffect(() => {
    if (!applyDraft) return;
    setImagePrompt(applyDraft.image_prompt);
    setVideoPrompt(applyDraft.video_prompt);
    setDirectorStateText(serializeDirectorState(applyDraft.director_state));
    setMessage("建议已应用到草稿；请保存镜头设计后才会成为服务器事实");
  }, [applyDraft]);

  // Keep the sibling production controls informed without persisting a
  // second copy of the design. The callback is deliberately effect-based so
  // a shot switch cannot synchronously leak the previous shot's dirty state.
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const save = useMutation({
    mutationFn: () => {
      const directorState = parseDirectorState(directorStateText);
      return updateShotDesign(projectId, shot.id, {
        expected_version: shot.version,
        director_state: directorState,
        image_prompt: imagePrompt,
        video_prompt: videoPrompt,
      });
    },
    onSuccess: async () => {
      // Do not use the mutation response as a local fake Shot/version. The
      // SceneWorkspace refetch is the only path that can make this draft
      // clean and enable production again.
      await onSaved?.();
      setMessage("已保存设计（版本已递增）");
    },
    onError: (error: unknown) => {
      // Keep the draft untouched on a stale-version or validation failure so
      // the user can compare it with the server truth and decide whether to
      // retry. ApiError.message is the backend's real detail.
      setMessage(`保存失败：${errorMessage(error)}`);
    },
  });

  return (
    <div className="qc-shot-design-panel" data-testid="shot-design-panel" data-shot-id={shot.id}>
      <header>
        <strong>#{shot.shot_number} 镜头设计</strong>
        <span>v{shot.version}</span>
      </header>
      <label>
        画面描述
        <textarea
          aria-label="画面描述"
          value={visual}
          onChange={(event) => setVisual(event.target.value)}
        />
      </label>
      <label>
        图片提示词
        <textarea
          aria-label="图片提示词"
          value={imagePrompt}
          onChange={(event) => setImagePrompt(event.target.value)}
        />
      </label>
      <label>
        视频提示词
        <textarea
          aria-label="视频提示词"
          value={videoPrompt}
          onChange={(event) => setVideoPrompt(event.target.value)}
        />
      </label>
      <label>
        导演状态（JSON）
        <textarea
          aria-label="导演状态"
          value={directorStateText}
          onChange={(event) => setDirectorStateText(event.target.value)}
          spellCheck={false}
        />
      </label>
      <button
        type="button"
        onClick={() => save.mutate()}
        disabled={save.isPending || !dirty}
        data-testid="save-shot-design"
      >
        保存设计
      </button>
      {message && <p className="qc-save-message">{message}</p>}
      {visual !== shot.visual_description && (
        <p className="muted">画面描述修改需在画布版本中保存才会成为正式事实。</p>
      )}
      {dirty && (
        <p className="canvas-dirty" data-testid="shot-design-dirty" role="status">
          有未保存的镜头设计
        </p>
      )}
    </div>
  );
}
