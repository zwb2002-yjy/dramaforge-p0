import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Layers, RotateCw } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, Dialog } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  batchReasonLabel,
  dispatchBatchProduction,
  fetchBatchProductionPreview,
  isModelSetupReason,
  type BatchProductionPreview,
  type BatchProductionPreviewItem,
  type BatchProductionStage,
} from "./batchApi";
import "./batch-fill.css";

const STAGE_COPY: Record<
  BatchProductionStage,
  { noun: string; fill: string; done: string; running: string }
> = {
  image_keyframe: { noun: "画面", fill: "补齐画面", done: "画面已齐", running: "画面生成中" },
  video: { noun: "视频", fill: "补齐视频", done: "视频已齐", running: "视频生成中" },
};

type ReasonGroup = { reason: string; items: BatchProductionPreviewItem[] };

function isUsablePreview(value: unknown): value is BatchProductionPreview {
  if (!value || typeof value !== "object") return false;
  const preview = value as Partial<BatchProductionPreview>;
  return (
    typeof preview.fingerprint === "string" &&
    preview.fingerprint.length === 64 &&
    Number.isInteger(preview.ready_count) &&
    Array.isArray(preview.items)
  );
}

function groupByReason(items: BatchProductionPreviewItem[]): ReasonGroup[] {
  const groups = new Map<string, BatchProductionPreviewItem[]>();
  for (const item of items) {
    const key = batchReasonLabel(item.reason);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()].map(([reason, grouped]) => ({ reason, items: grouped }));
}

function summarize(preview: BatchProductionPreview) {
  const skipped = preview.items.filter((item) => item.disposition === "skipped");
  const blocked = preview.items.filter((item) => item.disposition === "blocked");
  const active = skipped.filter((item) => item.reason === "STAGE_ALREADY_ACTIVE").length;
  const complete =
    preview.items.length > 0 && preview.items.every((item) => item.reason === "ALREADY_FORMAL");
  return { skipped, blocked, active, complete };
}

function BatchFillDialog({
  projectId,
  sceneId,
  stage,
  preview,
  onClose,
  onSubmitted,
  onStale,
}: {
  projectId: string;
  sceneId?: string;
  stage: BatchProductionStage;
  preview: BatchProductionPreview;
  onClose: () => void;
  onSubmitted: (accepted: number) => Promise<void>;
  onStale: () => Promise<void>;
}) {
  const copy = STAGE_COPY[stage];
  const { skipped, blocked } = summarize(preview);
  const skippedGroups = useMemo(() => groupByReason(skipped), [skipped]);
  const blockedGroups = useMemo(() => groupByReason(blocked), [blocked]);
  const needsModelSetup = blocked.some((item) => isModelSetupReason(item.reason));
  const [stale, setStale] = useState(false);
  const dispatch = useMutation({
    mutationFn: () =>
      dispatchBatchProduction(projectId, {
        stage,
        scene_id: sceneId ?? null,
        preview_fingerprint: preview.fingerprint,
        batch_key: `${sceneId ?? "project"}:${stage}:${preview.fingerprint.slice(0, 24)}`,
        max_provider_calls: preview.ready_count,
        owner_authorized: true,
      }),
    onSuccess: (result) => onSubmitted(result.accepted_count),
    onError: async (error) => {
      if (
        error instanceof ApiError &&
        (error.code === "BATCH_PREVIEW_STALE" || error.details.code === "BATCH_PREVIEW_STALE")
      ) {
        setStale(true);
        await onStale();
      }
    },
  });

  return (
    <Dialog
      title={copy.fill}
      kicker={sceneId ? "当前场景" : "全片"}
      onClose={onClose}
      testId={`batch-fill-dialog-${stage}`}
      actions={
        <>
          <Button tone="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            tone="primary"
            disabled={preview.ready_count < 1 || dispatch.isPending}
            onClick={() => {
              setStale(false);
              dispatch.mutate();
            }}
            data-testid={`batch-fill-confirm-${stage}`}
          >
            {dispatch.isPending ? "正在创建…" : `确认生成 ${preview.ready_count} 个`}
          </Button>
        </>
      }
    >
      <dl className="df-batch-summary">
        <div>
          <dt>将生成</dt>
          <dd className="df-num">{preview.ready_count}</dd>
        </div>
        <div>
          <dt>将跳过</dt>
          <dd className="df-num">{preview.skipped_count}</dd>
        </div>
        {preview.blocked_count > 0 && (
          <div className="warn">
            <dt>不可生成</dt>
            <dd className="df-num">{preview.blocked_count}</dd>
          </div>
        )}
      </dl>

      {skippedGroups.length > 0 && (
        <section className="df-batch-reasons" aria-label="跳过原因">
          <h3>跳过</h3>
          <ul>
            {skippedGroups.map((group) => (
              <li key={group.reason}>
                <span>{group.reason}</span>
                <span className="df-num">{group.items.length}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {blockedGroups.length > 0 && (
        <section className="df-batch-reasons" aria-label="不可生成原因">
          <h3>需要先处理</h3>
          <ul>
            {blockedGroups.map((group) => (
              <li key={group.reason} className="blocked">
                <span>{group.reason}</span>
                <span className="df-batch-shots">
                  {group.items.slice(0, 12).map((item) => (
                    <Link
                      key={item.shot_id}
                      to="/projects/$projectId/scenes/$sceneId"
                      params={{ projectId, sceneId: item.scene_id }}
                      search={{ shotId: item.shot_id, tool: "generate" }}
                      onClick={onClose}
                    >
                      镜头 {item.shot_number}
                    </Link>
                  ))}
                  {group.items.length > 12 && (
                    <span className="muted">等 {group.items.length} 个</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {needsModelSetup && (
            <Link className="df-batch-setup-link" to="/settings/models">
              去设置模型
            </Link>
          )}
        </section>
      )}

      <p className="df-batch-footnote">
        只生成缺少的{copy.noun}，已有正式版本不会被替换。费用由供应商账户结算。
      </p>
      {stale && (
        <p role="status" className="df-batch-note">
          镜头状态已变化，数量已更新，请再确认一次。
        </p>
      )}
      {dispatch.isError && !stale && (
        <p role="alert" className="df-batch-note err">
          未能创建任务：{dispatch.error.message}
        </p>
      )}
    </Dialog>
  );
}

function BatchFillButton({
  projectId,
  sceneId,
  stage,
}: {
  projectId: string;
  sceneId?: string;
  stage: BatchProductionStage;
}) {
  const queryClient = useQueryClient();
  const copy = STAGE_COPY[stage];
  const [open, setOpen] = useState(false);
  const [accepted, setAccepted] = useState<number | null>(null);
  const previewQuery = useQuery({
    queryKey: queryKeys.production.batchPreview(projectId, sceneId ?? null, stage),
    queryFn: () => fetchBatchProductionPreview(projectId, stage, sceneId),
    enabled: Boolean(projectId),
    retry: false,
  });
  const preview = isUsablePreview(previewQuery.data) ? previewQuery.data : undefined;

  if (previewQuery.isPending) {
    return (
      <Button disabled aria-busy="true" className="df-batch-button">
        <Layers size={16} aria-hidden="true" />
        {copy.fill}
      </Button>
    );
  }
  if (!preview) {
    // A failed read never pretends there is nothing to fill; it offers a retry.
    return (
      <Button
        className="df-batch-button"
        title="暂时无法读取，点击重试"
        data-state="error"
        onClick={() => void previewQuery.refetch()}
      >
        <RotateCw size={16} aria-hidden="true" />
        {copy.fill}
      </Button>
    );
  }

  const { active, complete } = summarize(preview);
  const refresh = async () => {
    await previewQuery.refetch();
  };
  const submitted = async (count: number) => {
    setOpen(false);
    setAccepted(count);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.production.batchPreviewRoot(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.production.summary(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.scene.summaries(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) }),
      sceneId
        ? queryClient.invalidateQueries({ queryKey: queryKeys.scene.workspace(projectId, sceneId) })
        : Promise.resolve(),
    ]);
  };

  let label: string;
  let tone: "default" | "primary" = "default";
  if (preview.ready_count > 0) {
    label = `${copy.fill} · ${preview.ready_count}`;
  } else if (active > 0) {
    label = `${copy.running} · ${active}`;
  } else if (complete) {
    label = copy.done;
  } else {
    label = `${copy.fill} · 0`;
  }
  if (preview.ready_count > 0 && stage === "image_keyframe") tone = "primary";

  return (
    <>
      <Button
        tone={tone}
        className="df-batch-button"
        disabled={complete}
        aria-haspopup="dialog"
        data-testid={`batch-fill-${stage}`}
        data-state={
          preview.ready_count > 0
            ? "ready"
            : active > 0
              ? "running"
              : complete
                ? "complete"
                : "blocked"
        }
        onClick={() => {
          setAccepted(null);
          setOpen(true);
        }}
      >
        <Layers size={16} aria-hidden="true" />
        <span className="df-num">{label}</span>
      </Button>
      {accepted !== null && (
        <span className="df-status active" role="status">
          已创建 {accepted} 个任务
        </span>
      )}
      {open && (
        <BatchFillDialog
          projectId={projectId}
          sceneId={sceneId}
          stage={stage}
          preview={preview}
          onClose={() => setOpen(false)}
          onSubmitted={submitted}
          onStale={refresh}
        />
      )}
    </>
  );
}

/**
 * "补齐" entry: fills only what is missing. The preview classifies every shot
 * as ready / skipped / blocked on the server; confirming authorizes exactly
 * the ready count for this preview fingerprint and nothing else.
 */
export function BatchFillActions({ projectId, sceneId }: { projectId: string; sceneId?: string }) {
  return (
    <div className="df-batch-actions" role="group" aria-label="批量补齐">
      <BatchFillButton projectId={projectId} sceneId={sceneId} stage="image_keyframe" />
      <BatchFillButton projectId={projectId} sceneId={sceneId} stage="video" />
    </div>
  );
}
