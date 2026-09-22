import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import {
  batchBlockerLabel,
  dispatchBatchProduction,
  fetchBatchProductionPreview,
  type BatchProductionPreview,
  type BatchProductionStage,
} from "./batchApi";

const STAGE_LABEL: Record<BatchProductionStage, string> = {
  image_keyframe: "为全部缺失镜头生成关键帧",
  video: "为全部已有正式关键帧的镜头生成视频",
};

function durationLabel(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "暂无足够历史数据";
  if (seconds < 60) return `约 ${Math.max(1, seconds)} 秒`;
  return `约 ${Math.ceil(seconds / 60)} 分钟`;
}

function isUsablePreview(value: unknown): value is BatchProductionPreview {
  if (!value || typeof value !== "object") return false;
  const preview = value as Partial<BatchProductionPreview>;
  return (
    typeof preview.fingerprint === "string" &&
    preview.fingerprint.length === 64 &&
    Number.isInteger(preview.estimated_provider_calls) &&
    Number.isInteger(preview.blocked_count) &&
    Number.isInteger(preview.currently_queued) &&
    Array.isArray(preview.items)
  );
}

function BatchStageCard({
  projectId,
  sceneId,
  stage,
  preview,
  loading,
  failed,
  authorized,
  maxCostPerCall,
  onAuthorizedChange,
  onMaxCostPerCallChange,
  onSubmitted,
}: {
  projectId: string;
  sceneId?: string;
  stage: BatchProductionStage;
  preview?: BatchProductionPreview;
  loading: boolean;
  failed: boolean;
  authorized: boolean;
  maxCostPerCall: string;
  onAuthorizedChange: (value: boolean) => void;
  onMaxCostPerCallChange: (value: string) => void;
  onSubmitted: () => Promise<void>;
}) {
  const dispatch = useMutation({
    mutationFn: async () => {
      if (!preview || preview.estimated_provider_calls < 1) throw new Error("当前没有可入队镜头");
      return dispatchBatchProduction(projectId, {
        stage,
        scene_id: sceneId ?? null,
        preview_fingerprint: preview.fingerprint,
        batch_key: `${sceneId ?? "project"}:${stage}:${preview.fingerprint.slice(0, 24)}`,
        max_provider_calls: preview.estimated_provider_calls,
        max_cost_per_call: maxCostPerCall,
        currency: "CNY",
        owner_authorized: true,
      });
    },
    onSuccess: onSubmitted,
  });
  return (
    <article className="panel" data-testid={`batch-production-${stage}`}>
      <h3>{STAGE_LABEL[stage]}</h3>
      {loading ? (
        <p role="status">正在预检模型、提示词、引用与正式素材…</p>
      ) : failed ? (
        <p role="alert">批量预检读取失败；不会提交任何生成。</p>
      ) : preview ? (
        <>
          <dl className="monitor-resource-stats">
            <div>
              <dt>预计 Provider 调用</dt>
              <dd>{preview.estimated_provider_calls}</dd>
            </div>
            <div>
              <dt>阻塞镜头</dt>
              <dd>{preview.blocked_count}</dd>
            </div>
            <div>
              <dt>本作品待执行</dt>
              <dd>{preview.currently_queued}</dd>
            </div>
            <div>
              <dt>本作品可见等待估算</dt>
              <dd>{durationLabel(preview.estimated_queue_seconds)}</dd>
            </div>
          </dl>
          {preview.blocked_count > 0 && (
            <details>
              <summary>查看 {preview.blocked_count} 个阻塞镜头</summary>
              <ul className="dense">
                {preview.items
                  .filter((item) => !item.ready)
                  .map((item) => (
                    <li key={item.shot_id}>
                      镜头 {item.shot_number}：{batchBlockerLabel(item.blocker)}
                    </li>
                  ))}
              </ul>
            </details>
          )}
          <label>
            单次 Provider 调用预算上限（人民币）
            <input
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={maxCostPerCall}
              onChange={(event) => {
                onMaxCostPerCallChange(event.target.value);
                onAuthorizedChange(false);
              }}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={authorized}
              onChange={(event) => onAuthorizedChange(event.target.checked)}
            />
            我是 Owner，并逐次授权本批 {preview.estimated_provider_calls} 个操作；每次最多 ¥
            {maxCostPerCall || "—"}
          </label>
          <p className="muted">
            本批总授权上限：¥
            {Number(maxCostPerCall) > 0
              ? (Number(maxCostPerCall) * preview.estimated_provider_calls).toFixed(2)
              : "—"}
            。服务端记录调用次数与每次授权上限，并写入每个任务快照；这不是 Provider 报价，实际费用以
            Provider 账单为准。
          </p>
          <button
            type="button"
            disabled={
              !authorized ||
              !(Number(maxCostPerCall) > 0) ||
              preview.estimated_provider_calls < 1 ||
              dispatch.isPending
            }
            onClick={() => dispatch.mutate()}
          >
            {dispatch.isPending
              ? "正在整批入队…"
              : `确认并入队 ${preview.estimated_provider_calls} 个镜头`}
          </button>
          {dispatch.isSuccess && (
            <p role="status">
              已接受 {dispatch.data.accepted_count} 个任务；请在作品进度或场景页查看本作品可见序位。
            </p>
          )}
          {dispatch.isError && <p role="alert">批量入队失败：{String(dispatch.error)}</p>}
        </>
      ) : null}
    </article>
  );
}

export function BatchProductionPanel({
  projectId,
  sceneId,
}: {
  projectId: string;
  sceneId?: string;
}) {
  const queryClient = useQueryClient();
  const [authorized, setAuthorized] = useState<Record<BatchProductionStage, boolean>>({
    image_keyframe: false,
    video: false,
  });
  const [maxCostPerCall, setMaxCostPerCall] = useState<Record<BatchProductionStage, string>>({
    image_keyframe: "",
    video: "",
  });
  const keyframes = useQuery({
    queryKey: queryKeys.production.batchPreview(projectId, sceneId ?? null, "image_keyframe"),
    queryFn: () => fetchBatchProductionPreview(projectId, "image_keyframe", sceneId),
    enabled: projectId !== "demo",
    retry: false,
  });
  const videos = useQuery({
    queryKey: queryKeys.production.batchPreview(projectId, sceneId ?? null, "video"),
    queryFn: () => fetchBatchProductionPreview(projectId, "video", sceneId),
    enabled: projectId !== "demo",
    retry: false,
  });
  const keyframePreview = isUsablePreview(keyframes.data) ? keyframes.data : undefined;
  const videoPreview = isUsablePreview(videos.data) ? videos.data : undefined;
  const submitted = async () => {
    setAuthorized({ image_keyframe: false, video: false });
    await Promise.all([
      keyframes.refetch(),
      videos.refetch(),
      queryClient.invalidateQueries({ queryKey: queryKeys.production.summary(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.scene.summaries(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) }),
      sceneId
        ? queryClient.invalidateQueries({ queryKey: queryKeys.scene.workspace(projectId, sceneId) })
        : Promise.resolve(),
    ]);
  };
  return (
    <section
      className="batch-production-panel"
      aria-label={sceneId ? "场景批量生成" : "作品批量生成"}
    >
      <header>
        <h2>{sceneId ? "按场景批量生成" : "全片批量生成"}</h2>
        <p className="muted">
          先预检、再确认调用上限；阻塞镜头不会混入本批。等待估算只覆盖本作品记录，不代表 Provider
          全局队列。
        </p>
      </header>
      <div className="director-professional-columns">
        <BatchStageCard
          projectId={projectId}
          sceneId={sceneId}
          stage="image_keyframe"
          preview={keyframePreview}
          loading={keyframes.isPending}
          failed={keyframes.isError || (keyframes.isSuccess && !keyframePreview)}
          authorized={authorized.image_keyframe}
          maxCostPerCall={maxCostPerCall.image_keyframe}
          onAuthorizedChange={(value) =>
            setAuthorized((current) => ({ ...current, image_keyframe: value }))
          }
          onMaxCostPerCallChange={(value) =>
            setMaxCostPerCall((current) => ({ ...current, image_keyframe: value }))
          }
          onSubmitted={submitted}
        />
        <BatchStageCard
          projectId={projectId}
          sceneId={sceneId}
          stage="video"
          preview={videoPreview}
          loading={videos.isPending}
          failed={videos.isError || (videos.isSuccess && !videoPreview)}
          authorized={authorized.video}
          maxCostPerCall={maxCostPerCall.video}
          onAuthorizedChange={(value) => setAuthorized((current) => ({ ...current, video: value }))}
          onMaxCostPerCallChange={(value) =>
            setMaxCostPerCall((current) => ({ ...current, video: value }))
          }
          onSubmitted={submitted}
        />
      </div>
    </section>
  );
}
