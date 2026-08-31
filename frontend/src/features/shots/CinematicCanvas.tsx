import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "./api";

type CinematicCanvasProps = {
  projectId: string;
  shot: ShotLite | null;
  /** Server-derived candidate envelope for the selected Shot. */
  candidates?: unknown[];
  /** Server-derived NodeRun summary for the selected Shot. */
  trace?: unknown[];
};

type CanvasCandidate = {
  artifactId: string;
  artifactType: "image" | "video";
  stage: "image_keyframe" | "video";
  status: string;
};

type TraceState = {
  status: string;
  nodeKey: string | null;
};

const ACTIVE_STATUSES = new Set(["queued", "pending", "running", "processing", "submitted"]);
const FAILED_STATUSES = new Set(["failed", "error", "cancelled", "canceled"]);

function candidateOf(value: unknown): CanvasCandidate | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  const artifactId = row.artifact_id ?? row.result_artifact_id ?? row.id;
  const rawType = row.artifact_type;
  if (
    typeof artifactId !== "string" ||
    artifactId.length === 0 ||
    (rawType !== "image" && rawType !== "video")
  ) {
    return null;
  }
  const rawStage = row.stage ?? row.node_key;
  const stage = rawStage === "video" || rawType === "video" ? "video" : ("image_keyframe" as const);
  return {
    artifactId,
    artifactType: rawType,
    stage,
    status: typeof row.status === "string" ? row.status : "completed",
  };
}

function traceStateOf(value: unknown): TraceState | null {
  if (typeof value !== "object" || value === null) return null;
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

function renderCandidate(candidates: unknown[]): CanvasCandidate | null {
  return (
    candidates
      .map(candidateOf)
      .find((candidate): candidate is CanvasCandidate => candidate !== null) ?? null
  );
}

function latestTraceState(trace: unknown[]): TraceState | null {
  return trace.map(traceStateOf).find((state): state is TraceState => state !== null) ?? null;
}

/**
 * Central canvas: formal output first, then a server candidate, then an
 * execution/empty state.  It deliberately contains no prompt, reference, or
 * production controls; those live in DirectorSidebar.
 */
export function CinematicCanvas({
  projectId,
  shot,
  candidates = [],
  trace = [],
}: CinematicCanvasProps) {
  const keyframeId = shot?.formal_keyframe_artifact_id ?? null;
  const videoId = shot?.formal_video_artifact_id ?? null;
  const candidate = renderCandidate(candidates);
  const latestTrace = latestTraceState(trace);
  const normalizedStatus = latestTrace?.status.toLowerCase() ?? "";
  const isActive = ACTIVE_STATUSES.has(normalizedStatus);
  const isFailed = FAILED_STATUSES.has(normalizedStatus);
  return (
    <div
      className="qc-cinematic-canvas"
      data-testid="cinematic-canvas"
      data-shot-id={shot?.id ?? undefined}
    >
      {!shot ? (
        <p className="qc-canvas-empty">选择左侧镜头开始导演构图。</p>
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
      ) : candidate ? (
        <div className="qc-canvas-media" data-testid="shot-candidate">
          <span className="qc-canvas-state">
            {candidate.stage === "video" ? "视频候选" : "关键帧候选"}
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
            候选 · {candidate.status} · {candidate.artifactId}
          </small>
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
