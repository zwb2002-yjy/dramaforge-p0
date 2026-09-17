import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import {
  artifactContentUrl,
  createReviewAnnotation,
  decideReviewAnnotation,
  fetchProjectShots,
  fetchReviewAnnotations,
  type ReviewAnnotationRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { fetchShotWorkbench } from "../shots/api";
import { isConfirmableShotCandidate, parseShotCandidates } from "../shots/shotCandidates";
import { readRepair } from "./repairApi";
import { parseReviewTarget, type ReviewTargetSearch } from "./reviewTarget";
import { HumanReviewDecisionPanel } from "./HumanReviewDecisionPanel";
import { MediaReviewCanvas, type NormalizedRegion } from "./MediaReviewCanvas";
import { RepairPlanPanel } from "./RepairPlanPanel";
import { VideoReviewTimeline, type VideoAnnotation } from "./VideoReviewTimeline";

type ReviewWorkspaceProps = {
  projectId: string;
  targetSearch?: ReviewTargetSearch;
};

function asNumber(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function imageRegion(annotation: ReviewAnnotationRead): NormalizedRegion | null {
  const x = asNumber(annotation.x);
  const y = asNumber(annotation.y);
  const width = asNumber(annotation.width);
  const height = asNumber(annotation.height);
  if (x === null || y === null || width === null || height === null) return null;
  return { x, y, width, height };
}

const ANNOTATION_SEVERITY_LABEL: Record<string, string> = {
  note: "提示",
  warning: "警告",
  blocker: "阻断",
};

function videoAnnotation(annotation: ReviewAnnotationRead): VideoAnnotation | null {
  const start = asNumber(annotation.time_start);
  if (start === null) return null;
  return {
    id: annotation.id,
    startSeconds: start,
    endSeconds: asNumber(annotation.time_end),
    note: annotation.note,
  };
}

/** Canonical review surface over the existing Shot/ReviewAnnotation facts. */
export function ReviewWorkspace(props: ReviewWorkspaceProps) {
  return (
    <ReviewWorkspaceSession
      key={JSON.stringify([props.projectId, props.targetSearch])}
      {...props}
    />
  );
}

function ReviewWorkspaceSession({ projectId, targetSearch = {} }: ReviewWorkspaceProps) {
  const explicitTarget = Object.keys(targetSearch).length > 0;
  const target = parseReviewTarget(targetSearch);
  const queryClient = useQueryClient();
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [repairOpen, setRepairOpen] = useState(false);
  const shots = useQuery({
    queryKey: queryKeys.shot.review(projectId),
    queryFn: () => fetchProjectShots(projectId),
    enabled: projectId !== "demo",
  });
  const shotId = explicitTarget
    ? (target?.shotId ?? null)
    : (selectedShotId ?? shots.data?.[0]?.id ?? null);
  const currentShot = useRef(shotId);
  currentShot.current = shotId;
  useEffect(() => {
    setNote("");
    setRepairOpen(false);
  }, [shotId]);

  const workbench = useQuery({
    queryKey: queryKeys.shot.reviewWorkbench(projectId, shotId),
    queryFn: () => fetchShotWorkbench(projectId, shotId!),
    enabled: projectId !== "demo" && Boolean(shotId),
  });
  const annotations = useQuery({
    queryKey: queryKeys.review.annotations(projectId, shotId),
    queryFn: () => fetchReviewAnnotations(projectId, shotId!),
    enabled: projectId !== "demo" && Boolean(shotId),
  });
  const addAnnotation = useMutation({
    mutationFn: (input: Parameters<typeof createReviewAnnotation>[2] & { shotId: string }) => {
      const { shotId: targetShotId, ...body } = input;
      return createReviewAnnotation(projectId, targetShotId, body);
    },
    retry: false,
    onSuccess: (saved) => {
      if (saved.shot_id === currentShot.current) setNote("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.review.annotations(projectId, saved.shot_id),
      });
    },
  });

  const decideAnnotation = useMutation({
    mutationFn: ({ annotationId, status }: { annotationId: string; status: "open" | "resolved" }) =>
      decideReviewAnnotation(projectId, shotId!, annotationId, status),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.review.annotations(projectId, shotId),
      });
    },
  });

  const shot = workbench.data?.shot ?? null;
  const repair = useQuery({
    queryKey: ["review-target-repair", projectId, target?.shotId, target?.repairRequestId],
    queryFn: () => readRepair(projectId, target!.shotId, target!.repairRequestId!),
    enabled: Boolean(target?.repairRequestId),
  });
  const candidateStage = target?.stage === "formal_keyframe" ? "image_keyframe" : "video";
  const matchesCandidate =
    target &&
    parseShotCandidates(workbench.data?.candidates).some(
      (item) =>
        item.artifactId === target.artifactId &&
        item.stage === candidateStage &&
        isConfirmableShotCandidate(item),
    );
  const matchesFormal =
    target &&
    (target.stage === "formal_keyframe"
      ? shot?.formal_keyframe_artifact_id
      : shot?.formal_video_artifact_id) === target.artifactId;
  const repairStep = repair.data?.steps.find((step) => step.id === target?.repairStepId);
  const matchesRepair =
    !target?.repairRequestId ||
    (repair.data?.shot_id === target.shotId &&
      repairStep?.result_artifact_id === target.artifactId &&
      repairStep.stage ===
        (candidateStage === "image_keyframe" ? "keyframe_regenerate" : "video_rerun"));
  const targetValid = Boolean(
    target && shot?.id === target.shotId && (matchesCandidate || matchesFormal) && matchesRepair,
  );
  const keyframeId = explicitTarget
    ? targetValid && target?.stage === "formal_keyframe"
      ? target.artifactId
      : null
    : shot?.formal_keyframe_artifact_id;
  const videoId = explicitTarget
    ? targetValid && target?.stage === "formal_video"
      ? target.artifactId
      : null
    : shot?.formal_video_artifact_id;
  const rows = (annotations.data ?? []).filter(
    (row) => !explicitTarget || row.artifact_id === target?.artifactId,
  );
  const regions = rows
    .filter(
      (annotation) =>
        annotation.target_kind === "image_region" && annotation.artifact_id === keyframeId,
    )
    .map(imageRegion)
    .filter((region): region is NormalizedRegion => region !== null);
  const videoRows = rows
    .filter(
      (annotation) => annotation.target_kind === "video_time" && annotation.artifact_id === videoId,
    )
    .map(videoAnnotation)
    .filter((annotation): annotation is VideoAnnotation => annotation !== null);
  const durationSeconds = Number(shot?.duration_seconds ?? 0);

  if (
    explicitTarget &&
    (!target ||
      workbench.isError ||
      repair.isError ||
      (workbench.isSuccess && (!target.repairRequestId || repair.isSuccess) && !targetValid))
  ) {
    return (
      <div role="alert">
        无法审查指定结果：目标不存在、不属于当前镜头或与修复步骤不匹配。不会改为显示正式版本。
      </div>
    );
  }
  if (explicitTarget && !targetValid) return <p role="status">正在核对指定审查结果…</p>;

  return (
    <div className="qc-project-page" data-testid="review-workspace">
      <nav className="qc-local-tabs" aria-label="制作视图">
        <Link to="/projects/$projectId/production" params={{ projectId }}>
          生产概览
        </Link>
        <Link to="/projects/$projectId/review" params={{ projectId }} aria-current="page">
          待审内容
        </Link>
      </nav>
      <header className="qc-page-heading">
        <h1>镜头审片与批注</h1>
        <span>在关键帧或时间线上标注并填写说明；批注不会改动正式产物。</span>
      </header>

      {shots.isError && <div className="flash err">无法读取镜头：{String(shots.error)}</div>}
      <label>
        当前镜头
        <select
          aria-label="当前镜头"
          disabled={explicitTarget}
          value={shotId ?? ""}
          onChange={(event) => setSelectedShotId(event.target.value || null)}
        >
          {(shots.data ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              #{item.shot_number} {item.visual_description || "未命名镜头"}
            </option>
          ))}
        </select>
      </label>
      <label>
        批注说明
        <input
          aria-label="批注说明"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="说明需要检查的内容"
        />
      </label>

      {shot && keyframeId ? (
        <section>
          <h2>关键帧</h2>
          <MediaReviewCanvas
            imageUrl={artifactContentUrl(projectId, keyframeId)}
            regions={regions}
            mode="region"
            onAddRegion={(region) => {
              if (!shotId || !note.trim() || addAnnotation.isPending) return;
              addAnnotation.mutate({
                shotId,
                note: note.trim(),
                artifact_id: keyframeId,
                target_kind: "image_region",
                x: String(region.x),
                y: String(region.y),
                width: String(region.width),
                height: String(region.height),
              });
            }}
          />
        </section>
      ) : (
        <p className="muted">尚未选择正式关键帧，当前没有可供图片批注的正式产物。</p>
      )}

      <section>
        <h2>人工判断</h2>
        <p className="muted">
          自动检查的结论只是证据；“人工通过”和“设为正式”是两个独立动作，前者不会自动推进正式版本。
        </p>
        {shot && keyframeId ? (
          <HumanReviewDecisionPanel
            projectId={projectId}
            shotId={shot.id}
            artifactId={keyframeId}
            reviewKind="identity"
            stage="formal_keyframe"
            shotVersion={shot.version}
            title="关键帧身份审查"
          />
        ) : (
          <p className="muted" data-testid="review-keyframe-missing">
            尚未选择正式关键帧，暂时没有可判断的素材。
          </p>
        )}
        {shot && videoId && (
          <HumanReviewDecisionPanel
            projectId={projectId}
            shotId={shot.id}
            artifactId={videoId}
            reviewKind="video_drift"
            stage="formal_video"
            shotVersion={shot.version}
            title="视频漂移审查"
          />
        )}
      </section>

      <section>
        <h2>修复</h2>
        <button
          type="button"
          data-testid="review-open-repair"
          onClick={() => setRepairOpen((open) => !open)}
          disabled={!shotId}
        >
          {repairOpen ? "收起修复计划" : "创建修复计划"}
        </button>
        {repairOpen && shotId && (
          <RepairPlanPanel
            projectId={projectId}
            shotId={shotId}
            onClose={() => setRepairOpen(false)}
          />
        )}
      </section>

      <section>
        <h2>视频时间线</h2>
        {shot && videoId ? (
          <VideoReviewTimeline
            key={`${shot.id}:${videoId}`}
            videoUrl={artifactContentUrl(projectId, videoId)}
            mediaLabel={explicitTarget ? "指定视频" : "正式视频"}
            durationSeconds={durationSeconds}
            annotations={videoRows}
            note={note}
            pending={addAnnotation.isPending}
            onAddAnnotation={async (startSeconds, endSeconds) => {
              if (!shotId || !note.trim() || addAnnotation.isPending) return;
              await addAnnotation.mutateAsync({
                shotId,
                artifact_id: videoId,
                target_kind: "video_time",
                note: note.trim(),
                time_start: String(startSeconds),
                time_end: endSeconds === null ? null : String(endSeconds),
              });
            }}
          />
        ) : (
          <p className="muted">尚未选择正式视频，当前没有可供时间批注的正式产物。</p>
        )}
      </section>
      <section data-testid="review-annotation-list">
        <h2>批注清单</h2>
        <p className="muted">
          批注只是审片证据；标记为“已解决”只更新批注状态，不会改动正式产物或放行任何生产动作。
        </p>
        {annotations.isLoading ? (
          <p className="muted" role="status">
            正在读取批注…
          </p>
        ) : rows.length === 0 ? (
          <p className="muted" data-testid="review-annotation-empty">
            当前镜头还没有批注。
          </p>
        ) : (
          <ul className="dense">
            {rows.map((row) => {
              const resolved = row.status === "resolved";
              return (
                <li key={row.id} data-testid="review-annotation-row">
                  <div>
                    <strong>{row.note}</strong>
                    <small>
                      {ANNOTATION_SEVERITY_LABEL[row.severity] ?? row.severity} ·{" "}
                      {resolved ? "已解决" : "待处理"}
                      {row.target_kind === "video_time" && row.time_start !== null
                        ? ` · ${row.time_start}s${row.time_end ? `–${row.time_end}s` : ""}`
                        : ""}
                    </small>
                  </div>
                  <button
                    type="button"
                    data-testid="review-annotation-decision"
                    disabled={decideAnnotation.isPending}
                    onClick={() =>
                      decideAnnotation.mutate({
                        annotationId: row.id,
                        status: resolved ? "open" : "resolved",
                      })
                    }
                  >
                    {resolved ? "重新打开" : "标记为已解决"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {decideAnnotation.isError && (
          <div className="flash err">批注状态更新失败：{String(decideAnnotation.error)}</div>
        )}
      </section>
      {addAnnotation.isError && addAnnotation.variables?.shotId === shotId && (
        <div className="flash err">批注保存失败：{String(addAnnotation.error)}</div>
      )}
    </div>
  );
}
