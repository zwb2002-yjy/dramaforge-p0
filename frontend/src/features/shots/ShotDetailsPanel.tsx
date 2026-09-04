import { useEffect } from "react";
import { X } from "lucide-react";

import { ShotProductionTrace } from "./ShotProductionTrace";
import type { ShotLite } from "./api";

type ShotDetailsPanelProps = {
  open: boolean;
  shot: ShotLite | null;
  trace: unknown[];
  onClose: () => void;
};

/**
 * V2 Canvas-first (UI-1): technical execution metadata (NodeRun trace,
 * shot version) sunk into an on-demand Details sheet. The default creation
 * flow never sees this surface; the facts themselves are unchanged.
 */
export function ShotDetailsPanel({ open, shot, trace, onClose }: ShotDetailsPanelProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="qc-shot-details-sheet"
      data-testid="shot-details-sheet"
      data-shot-id={shot?.id ?? undefined}
      role="dialog"
      aria-modal="false"
      aria-label="镜头生产详情"
    >
      <header>
        <div>
          <span className="director-stage-kicker">生产详情</span>
          <strong>{shot ? `#${shot.shot_number} · v${shot.version}` : "技术详情"}</strong>
        </div>
        <button
          type="button"
          className="qc-icon-button"
          data-testid="shot-details-close"
          onClick={onClose}
          aria-label="关闭生产详情"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      {shot ? (
        <div className="qc-shot-details-body">
          <dl>
            <dt>镜头状态</dt>
            <dd>{shot.status}</dd>
            <dt>时长</dt>
            <dd>{shot.duration_seconds ?? "—"}s</dd>
            <dt>正式关键帧</dt>
            <dd>{shot.formal_keyframe_artifact_id ?? "未确认"}</dd>
            <dt>正式视频</dt>
            <dd>{shot.formal_video_artifact_id ?? "未确认"}</dd>
          </dl>
          <ShotProductionTrace shotId={shot.id} trace={trace} />
        </div>
      ) : (
        <p className="muted">选择一个镜头查看生产详情。</p>
      )}
    </div>
  );
}
