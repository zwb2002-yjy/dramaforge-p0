import { useEffect, useState } from "react";

import { fetchExecutionTrace, type ExecutionTraceRead } from "../../lib/api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { shotStatusLabel } from "../../lib/shotLabels";
import { zhNode } from "../../lib/zh";
import { ShotProductionTrace } from "./ShotProductionTrace";
import type { ShotLite } from "./api";

type ShotDetailsBodyProps = {
  projectId?: string;
  shot: ShotLite;
  trace: unknown[];
};

/**
 * Technical execution metadata (NodeRun trace, shot version) for the
 * inspector's collapsed 「详情」. The default creation flow never needs it; the
 * facts themselves are unchanged.
 */
export function ShotDetailsBody({ projectId, shot, trace }: ShotDetailsBodyProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<ExecutionTraceRead | null>(null);
  const [traceDetailLoading, setTraceDetailLoading] = useState(false);
  const [traceDetailError, setTraceDetailError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedRunId(null);
    setTraceDetail(null);
    setTraceDetailError(null);
  }, [shot.id]);

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

  return (
    <div className="df-shot-details" data-testid="shot-details-sheet" data-shot-id={shot.id}>
      <dl className="df-shot-details-facts">
        <dt>版本</dt>
        <dd>v{shot.version}</dd>
        <dt>状态</dt>
        <dd data-testid="shot-details-status">{shotStatusLabel(shot.status)}</dd>
        <dt>正式画面</dt>
        <dd>{shot.formal_keyframe_artifact_id ? "已确认" : "未确认"}</dd>
        <dt>正式视频</dt>
        <dd>{shot.formal_video_artifact_id ? "已确认" : "未确认"}</dd>
      </dl>
      <ShotProductionTrace
        shotId={shot.id}
        trace={trace}
        onSelectRun={projectId ? setSelectedRunId : undefined}
      />
      {traceDetailLoading && (
        <p className="muted" role="status">
          正在读取执行记录…
        </p>
      )}
      {traceDetailError && (
        <div className="df-shot-hint err" data-testid="execution-trace-error" role="alert">
          <p>执行记录读取失败，可以稍后重试。</p>
          <details className="editing-diagnostics" data-testid="execution-trace-error-diagnostics">
            <summary>诊断详情</summary>
            <small>{traceDetailError}</small>
          </details>
        </div>
      )}
      {traceDetail && (
        <section data-testid="execution-trace-detail" className="df-shot-trace-detail">
          <h3>执行记录</h3>
          <dl className="df-shot-details-facts">
            <dt>节点</dt>
            <dd>{zhNode(traceDetail.node_key)}</dd>
            <dt>状态</dt>
            <dd>{nodeRunStatusLabel(traceDetail.status)}</dd>
            <dt>模型</dt>
            <dd>{traceDetail.actual_model ?? "—"}</dd>
          </dl>
          {traceDetail.operation_outcome_unknown && (
            <p className="df-shot-hint warn">提交结果未知，请先核对，不要直接重试。</p>
          )}
          <details className="editing-diagnostics" data-testid="execution-trace-diagnostics">
            <summary>诊断详情</summary>
            <small>
              运行 {traceDetail.run_id} · 节点 {traceDetail.node_key ?? "无"} · 状态{" "}
              {traceDetail.status} · Provider {traceDetail.actual_provider ?? "无"} · 操作状态{" "}
              {traceDetail.operation_status ?? "无"}
            </small>
          </details>
        </section>
      )}
      <details className="editing-diagnostics" data-testid="shot-details-diagnostics">
        <summary>诊断详情</summary>
        <small>
          状态 {shot.status} · 正式画面 {shot.formal_keyframe_artifact_id ?? "无"} · 正式视频{" "}
          {shot.formal_video_artifact_id ?? "无"}
        </small>
      </details>
    </div>
  );
}
