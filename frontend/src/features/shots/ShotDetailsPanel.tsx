import { Button, Disclosure } from "../../components/ui";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../lib/queryKeys";

import { fetchExecutionTrace } from "./api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { shotStatusLabel } from "../../lib/shotLabels";
import { zhNode } from "../../lib/zh";
import { ShotProductionTrace } from "./ShotProductionTrace";
import type { ShotLite } from "./api";
import { shotDetailsCopy as copy } from "./shotDetailsCopy";

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
  const [selection, setSelection] = useState<{ shotId: string; runId: string } | null>(null);
  // Scene/Shot trace contract: created_at, attempt_no, id descending. Keep
  // this server order; finished_at can make an older run look newer.
  const latestFailureRunId =
    trace.flatMap((row) =>
      typeof row === "object" &&
      row !== null &&
      "status" in row &&
      row.status === "failed" &&
      "node_run_id" in row &&
      typeof row.node_run_id === "string"
        ? [row.node_run_id]
        : [],
    )[0] ?? null;
  const selectedRunId = selection?.shotId === shot.id ? selection.runId : latestFailureRunId;
  const detail = useQuery({
    queryKey: queryKeys.shot.executionTrace(projectId, shot.id, selectedRunId),
    queryFn: ({ signal }) => fetchExecutionTrace(projectId!, selectedRunId!, signal),
    enabled: Boolean(projectId && selectedRunId),
    retry: false,
  });
  const traceDetail = selectedRunId ? detail.data : undefined;
  const traceDetailLoading = Boolean(selectedRunId && detail.isPending);
  const traceDetailError =
    selectedRunId && detail.error
      ? detail.error instanceof Error
        ? detail.error.message
        : copy.unknownError
      : null;

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
        onSelectRun={projectId ? (runId) => setSelection({ shotId: shot.id, runId }) : undefined}
      />
      {traceDetailLoading && (
        <p className="muted" role="status">
          {copy.loading}
        </p>
      )}
      {traceDetailError && (
        <div className="df-shot-hint err" data-testid="execution-trace-error" role="alert">
          <p>{copy.failed}</p>
          <Button onClick={() => void detail.refetch()}>{copy.retry}</Button>
          <Disclosure
            compact
            className="editing-diagnostics"
            data-testid="execution-trace-error-diagnostics"
            title={<>诊断详情</>}
          >
            <small>{traceDetailError}</small>
          </Disclosure>
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
          <dl className="df-shot-details-facts" data-testid="execution-submission-status">
            <dt>发送步骤</dt>
            <dd>
              {traceDetail.submission_diagnostics
                ? {
                    not_sent: "配置检查未通过，尚未发送",
                    connection_failed: "连接失败，尚未发送 HTTP 请求",
                    outcome_unknown: "等待响应时中断，发送结果未知",
                    response_received: "已收到 HTTP 响应，未取得远端任务 ID",
                    accepted:
                      (traceDetail.submission_diagnostics.http_status ?? 200) >= 300
                        ? "已取得远端任务 ID，但 HTTP 回应异常，需查询原任务确认"
                        : "已取得远端任务 ID",
                  }[traceDetail.submission_diagnostics.phase]
                : traceDetail.operation_status
                  ? "该历史记录未保存发送诊断，无法补造"
                  : "尚未发现模型调用记录"}
            </dd>
            {traceDetail.submission_diagnostics?.http_status != null && (
              <>
                <dt>接口回应</dt>
                <dd>HTTP {traceDetail.submission_diagnostics.http_status}</dd>
              </>
            )}
            {traceDetail.submission_diagnostics?.response_error && (
              <>
                <dt>接口错误摘要</dt>
                <dd>{traceDetail.submission_diagnostics.response_error}</dd>
              </>
            )}
            {traceDetail.error_summary && !traceDetail.submission_diagnostics?.response_error && (
              <>
                <dt>失败信息</dt>
                <dd>{traceDetail.error_summary}</dd>
              </>
            )}
          </dl>
          <Disclosure
            compact
            className="editing-diagnostics"
            data-testid="execution-trace-diagnostics"
            title={<>诊断详情</>}
          >
            <small>
              运行 {traceDetail.run_id} · 节点 {traceDetail.node_key ?? "无"} · 状态{" "}
              {traceDetail.status} · Provider {traceDetail.actual_provider ?? "无"} · 操作状态{" "}
              {traceDetail.operation_status ?? "无"}
              {traceDetail.submission_diagnostics && (
                <>
                  <br />
                  请求 {traceDetail.submission_diagnostics.method}{" "}
                  {traceDetail.submission_diagnostics.endpoint}
                  <br />
                  耗时 {traceDetail.submission_diagnostics.duration_ms} 毫秒
                  <br />
                  接口追踪 ID{" "}
                  {traceDetail.submission_diagnostics.response_request_id ?? "接口未返回"}
                  <br />
                  边缘追踪 ID {traceDetail.submission_diagnostics.edge_request_id ?? "接口未返回"}
                  <br />
                  响应服务 {traceDetail.submission_diagnostics.response_server ?? "接口未返回"}
                  <br />
                  网络错误 {traceDetail.submission_diagnostics.network_error ?? "无"}
                </>
              )}
            </small>
          </Disclosure>
        </section>
      )}
      <Disclosure
        compact
        className="editing-diagnostics"
        data-testid="shot-details-diagnostics"
        title={<>诊断详情</>}
      >
        <small>
          状态 {shot.status} · 正式画面 {shot.formal_keyframe_artifact_id ?? "无"} · 正式视频{" "}
          {shot.formal_video_artifact_id ?? "无"}
        </small>
      </Disclosure>
    </div>
  );
}
