import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { updateShotDesign } from "./api";
import type { ShotLite } from "./api";

type ShotDesignPanelProps = {
  projectId: string;
  shot: ShotLite;
  onSaved?: () => void;
};

/** P3 shot design panel: edit visual description, image/video prompt, director state. */
export function ShotDesignPanel({ projectId, shot, onSaved }: ShotDesignPanelProps) {
  const [visual, setVisual] = useState(shot.visual_description);
  const [imagePrompt, setImagePrompt] = useState(shot.image_prompt);
  const [videoPrompt, setVideoPrompt] = useState(shot.video_prompt);
  const [message, setMessage] = useState("");

  // The panel remains mounted while the shot strip changes selection. Reset
  // editor state to the newly selected shot's server read model so edits and
  // subsequent production actions cannot leak across shots.
  useEffect(() => {
    setVisual(shot.visual_description);
    setImagePrompt(shot.image_prompt);
    setVideoPrompt(shot.video_prompt);
    setMessage("");
  }, [shot.id, shot.version, shot.visual_description, shot.image_prompt, shot.video_prompt]);

  const save = useMutation({
    mutationFn: () =>
      updateShotDesign(projectId, shot.id, {
        expected_version: shot.version,
        image_prompt: imagePrompt,
        video_prompt: videoPrompt,
      }),
    onSuccess: () => {
      setMessage("已保存设计（版本已递增）");
      onSaved?.();
    },
    onError: (error: unknown) => {
      setMessage(`保存失败：${String(error)}`);
    },
  });

  return (
    <div className="qc-shot-design-panel" data-testid="shot-design-panel">
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
      <button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
        保存设计
      </button>
      {message && <p className="qc-save-message">{message}</p>}
      {visual !== shot.visual_description && (
        <p className="muted">画面描述修改需在画布版本中保存才会成为正式事实。</p>
      )}
    </div>
  );
}
