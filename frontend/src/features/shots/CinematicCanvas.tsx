import { useEffect, useMemo, useState } from "react";

import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "./api";
import { parseShotCandidates, shotCandidateKey, type ShotCandidate } from "./shotCandidates";

type CinematicCanvasProps = {
  projectId: string;
  shot: ShotLite | null;
  /** Server-derived candidate envelope for the selected Shot. */
  candidates?: unknown[];
  /** A local-only CandidateTray selection to preview on the canvas. */
  selectedCandidate?: ShotCandidate | null;
  /** Alias useful to embedders that call the local selection a preview. */
  previewCandidate?: ShotCandidate | null;
  /** Optional uncontrolled setter for a host that renders its own tray. */
  onCandidateSelect?: (candidate: ShotCandidate) => void;
  /** Server-derived NodeRun summary for the selected Shot. */
  trace?: unknown[];
};

type TraceState = {
  status: string;
  nodeKey: string | null;
};

const ACTIVE_STATUSES = new Set(["queued", "pending", "running", "processing", "submitted"]);
const FAILED_STATUSES = new Set(["failed", "error", "cancelled", "canceled"]);

function traceStateOf(value: unknown): TraceState | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (typeof row.status !== "string" || row.status.length === 0) return null;
  return {
    status: row.status,
    nodeKey: typeof row.node_key === "string" ? row.node_key : null,
  };
}

function stateLabel(status: string): string {
  switch (status) {
    case "queued":
    case "pending":
      return "执行已排队";
    case "running":
    case "processing":
    case "submitted":
      return "正在执行";
    case "failed":
    case "error":
      return "执行失败";
    case "cancelled":
    case "canceled":
      return "执行已取消";
    case "completed":
    case "cached":
    case "completed_after_cancel":
    case "succeeded":
      return "执行完成，等待结果确认";
    default:
      return `执行状态：${status}`;
  }
}

function latestTraceState(trace: unknown[]): TraceState | null {
  return trace.map(traceStateOf).find((state): state is TraceState => state !== null) ?? null;
}

/**
 * Stage-first central canvas. The canvas renders the work itself and keeps
 * all prompts, references, generation, and formal confirmation in sibling
 * operation surfaces.
 *
 * Preview order is intentionally explicit:
 * local CandidateTray selection → formal video → formal keyframe → an
 * unconfirmed server candidate → execution state / placeholder.
 */
export function CinematicCanvas({
  projectId,
  shot,
  candidates = [],
  selectedCandidate,
  previewCandidate,
  onCandidateSelect,
  trace = [],
}: CinematicCanvasProps) {
  const [localCandidate, setLocalCandidate] = useState<ShotCandidate | null>(null);
  useEffect(() => {
    // Candidate previews are ephemeral UI state and never survive a Shot
    // switch. The parent clears its controlled selection at the same boundary.
    setLocalCandidate(null);
  }, [shot?.id]);

  const parsedCandidates = useMemo(() => parseShotCandidates(candidates), [candidates]);
  const controlledCandidate = selectedCandidate ?? previewCandidate ?? null;
  const candidate = controlledCandidate ?? localCandidate ?? parsedCandidates[0] ?? null;
  const keyframeId = shot?.formal_keyframe_artifact_id ?? null;
  const videoId = shot?.formal_video_artifact_id ?? null;
  const latestTrace = latestTraceState(trace);
  const normalizedStatus = latestTrace?.status.toLowerCase() ?? "";
  const isActive = ACTIVE_STATUSES.has(normalizedStatus);
  const isFailed = FAILED_STATUSES.has(normalizedStatus);

  const selectCandidate = (next: ShotCandidate) => {
    if (selectedCandidate === undefined && previewCandidate === undefined) {
      setLocalCandidate(next);
    }
    onCandidateSelect?.(next);
  };

  return (
    <div
      className="qc-cinematic-canvas"
      data-testid="cinematic-canvas"
      data-shot-id={shot?.id ?? undefined}
      data-preview-candidate={candidate ? shotCandidateKey(candidate) : undefined}
    >
      {!shot ? (
        <p className="qc-canvas-empty">选择镜头开始导演构图。</p>
      ) : candidate ? (
        <div
          className="qc-canvas-media"
          data-testid="shot-candidate"
          onClick={() => selectCandidate(candidate)}
        >
          <span className="qc-canvas-state">
            {candidate.stage === "video" ? "视频候选预览" : "关键帧候选预览"}
          </span>
          {candidate.artifactType === "video" ? (
            <video
              controls
              preload="metadata"
              src={artifactContentUrl(projectId, candidate.artifactId)}
              data-testid={`shot-candidate-preview-${candidate.artifactId}`}
            />
          ) : (
            <img
              src={artifactContentUrl(projectId, candidate.artifactId)}
              alt={`#${shot.shot_number} 候选 ${candidate.artifactId}`}
              data-testid={`shot-candidate-preview-${candidate.artifactId}`}
            />
          )}
          <small>
            未确认候选 · {candidate.status} · {candidate.artifactId}
          </small>
        </div>
      ) : videoId ? (
        <div className="qc-canvas-media" data-testid="shot-formal-output">
          <span className="qc-canvas-state">正式视频</span>
          <video
            controls
            preload="metadata"
            src={artifactContentUrl(projectId, videoId)}
            data-testid="shot-video-player"
          />
        </div>
      ) : keyframeId ? (
        <div className="qc-canvas-media" data-testid="shot-formal-output">
          <span className="qc-canvas-state">正式关键帧</span>
          <img
            src={artifactContentUrl(projectId, keyframeId)}
            alt={`#${shot.shot_number} 关键帧`}
            data-testid="shot-keyframe"
          />
        </div>
      ) : isActive || isFailed ? (
        <div className="qc-canvas-empty qc-canvas-status" data-testid="shot-execution-state">
          <h3>
            #{shot.shot_number} {stateLabel(normalizedStatus)}
          </h3>
          <p>{latestTrace?.nodeKey ?? "当前镜头生产链"}</p>
          <p className="qc-canvas-hint" data-testid="shot-execution-status" role="status">
            {latestTrace?.status}
          </p>
        </div>
      ) : (
        <div className="qc-canvas-empty" data-testid="shot-placeholder">
          <h3>#{shot.shot_number} 导演构图预览</h3>
          <p>{shot.visual_description || "尚未生成关键帧。"}</p>
          {latestTrace && (
            <p className="qc-canvas-hint" data-testid="shot-execution-status" role="status">
              {stateLabel(latestTrace.status)} · {latestTrace.status}
            </p>
          )}
          <p className="qc-canvas-hint" data-testid="no-formal-result">
            尚未选择正式结果
          </p>
        </div>
      )}
    </div>
  );
}
