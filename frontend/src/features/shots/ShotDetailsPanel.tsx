import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { fetchExecutionTrace, type ExecutionTraceRead } from "../../lib/api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { shotStatusLabel } from "../../lib/shotLabels";
import { zhNode } from "../../lib/zh";
import { ShotProductionTrace } from "./ShotProductionTrace";
import type { ShotLite } from "./api";

type ShotDetailsPanelProps = {
  open: boolean;
  projectId?: string;
  shot: ShotLite | null;
  trace: unknown[];
  onClose: () => void;
};

/**
 * V2 Canvas-first (UI-1): technical execution metadata (NodeRun trace,
 * shot version) sunk into an on-demand Details sheet. The default creation
 * flow never sees this surface; the facts themselves are unchanged.
 */
export function ShotDetailsPanel({ open, projectId, shot, trace, onClose }: ShotDetailsPanelProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<ExecutionTraceRead | null>(null);
  const [traceDetailLoading, setTraceDetailLoading] = useState(false);
  const [traceDetailError, setTraceDetailError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    setSelectedRunId(null);
    setTraceDetail(null);
    setTraceDetailError(null);
  }, [shot?.id]);

  useEffect(() => {
    if (!projectId || !selectedRunId) return;
    let active = true;
    setTraceDetailLoading(true);
    setTraceDetailError(null);
    void fetchExecutionTrace(projectId, selectedRunId)
      .then((detail) => {
        if (active) setTraceDetail(detail);
      })
      .catch((cause: unknown) => {
        if (active) {
          setTraceDetail(null);
          setTraceDetailError(cause instanceof Error ? cause.message : "完整执行证据读取失败");
        }
      })
      .finally(() => {
        if (active) setTraceDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, selectedRunId]);

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
            <dt>镜头版本</dt>
            <dd>v{shot.version}</dd>
            <dt>镜头状态</dt>
            <dd data-testid="shot-details-status">{shotStatusLabel(shot.status)}</dd>
            <dt>时长</dt>
            <dd>{shot.duration_seconds ?? "—"}s</dd>
            <dt>正式关键帧</dt>
            <dd>{shot.formal_keyframe_artifact_id ? "已确认" : "未确认"}</dd>
            <dt>正式视频</dt>
            <dd>{shot.formal_video_artifact_id ? "已确认" : "未确认"}</dd>
          </dl>
          <details className="editing-diagnostics" data-testid="shot-details-diagnostics">
            <summary>开发 / 诊断详情（只读）</summary>
            <small>
              状态 {shot.status} · 正式关键帧 {shot.formal_keyframe_artifact_id ?? "无"} · 正式视频{" "}
              {shot.formal_video_artifact_id ?? "无"}
            </small>
          </details>
          <ShotProductionTrace
            shotId={shot.id}
            trace={trace}
            onSelectRun={projectId ? setSelectedRunId : undefined}
          />
          {traceDetailLoading && (
            <p className="muted" role="status">
              正在读取完整执行证据…
            </p>
          )}
          {traceDetailError && (
            <div className="flash err" data-testid="execution-trace-error" role="alert">
              <p>完整执行证据暂时读取失败，可以重开详情重试。</p>
              <details
                className="editing-diagnostics"
                data-testid="execution-trace-error-diagnostics"
              >
                <summary>开发 / 诊断详情（只读）</summary>
                <small>{traceDetailError}</small>
              </details>
            </div>
          )}
          {traceDetail && (
            <section data-testid="execution-trace-detail" className="qc-execution-trace-detail">
              <h3>完整执行证据</h3>
              <dl>
                <dt>节点</dt>
                <dd>{zhNode(traceDetail.node_key)}</dd>
                <dt>状态</dt>
                <dd>{nodeRunStatusLabel(traceDetail.status)}</dd>
                <dt>生成模型</dt>
                <dd>{traceDetail.actual_model ?? "—"}</dd>
              </dl>
              {traceDetail.operation_outcome_unknown && (
                <p className="status-bad">提交结果未知，请先完成对账，不要盲目重试。</p>
              )}
              <details className="editing-diagnostics" data-testid="execution-trace-diagnostics">
                <summary>开发 / 诊断详情（只读）</summary>
                <small>
                  运行 {traceDetail.run_id} · 节点 {traceDetail.node_key ?? "无"} · 状态{" "}
                  {traceDetail.status} · Provider {traceDetail.actual_provider ?? "无"} · 操作状态{" "}
                  {traceDetail.operation_status ?? "无"}
                </small>
              </details>
            </section>
          )}
        </div>
      ) : (
        <p className="muted">选择一个镜头查看生产详情。</p>
      )}
    </div>
  );
}
