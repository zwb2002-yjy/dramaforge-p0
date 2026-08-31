import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  artifactContentUrl,
  createReviewAnnotation,
  fetchProjectShots,
  fetchReviewAnnotations,
  type ReviewAnnotationRead,
} from "../../lib/api";
import { fetchShotWorkbench } from "../shots/api";
import { MediaReviewCanvas, type NormalizedRegion } from "./MediaReviewCanvas";
import { VideoReviewTimeline, type VideoAnnotation } from "./VideoReviewTimeline";

type ReviewWorkspaceProps = {
  projectId: string;
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
export function ReviewWorkspace({ projectId }: ReviewWorkspaceProps) {
  const queryClient = useQueryClient();
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const shots = useQuery({
    queryKey: ["review-shots", projectId],
    queryFn: () => fetchProjectShots(projectId),
    enabled: projectId !== "demo",
  });
  const shotId = selectedShotId ?? shots.data?.[0]?.id ?? null;
  const workbench = useQuery({
    queryKey: ["review-shot-workbench", projectId, shotId],
    queryFn: () => fetchShotWorkbench(projectId, shotId!),
    enabled: projectId !== "demo" && Boolean(shotId),
  });
  const annotations = useQuery({
    queryKey: ["review-annotations", projectId, shotId],
    queryFn: () => fetchReviewAnnotations(projectId, shotId!),
    enabled: projectId !== "demo" && Boolean(shotId),
  });
  const addAnnotation = useMutation({
    mutationFn: (
      input: Omit<Parameters<typeof createReviewAnnotation>[2], "note">,
    ) =>
      createReviewAnnotation(projectId, shotId!, { ...input, note }),
    onSuccess: () => {
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["review-annotations", projectId, shotId] });
    },
  });

  const shot = workbench.data?.shot ?? null;
  const rows = annotations.data ?? [];
  const regions = rows
    .filter((annotation) => annotation.target_kind === "image_region")
    .map(imageRegion)
    .filter((region): region is NormalizedRegion => region !== null);
  const videoRows = rows
    .filter((annotation) => annotation.target_kind === "video_time")
    .map(videoAnnotation)
    .filter((annotation): annotation is VideoAnnotation => annotation !== null);
  const durationSeconds = Number(shot?.duration_seconds ?? 0);

  return (
    <div className="qc-project-page" data-testid="review-workspace">
      <header className="qc-page-heading">
        <p>审片</p>
        <h1>镜头审片与批注</h1>
        <span>批注写入 ReviewAnnotation；正式产物与生产血缘保持不变。</span>
      </header>

      {shots.isError && <div className="flash err">无法读取镜头：{String(shots.error)}</div>}
      <label>
        当前镜头
        <select
          aria-label="当前镜头"
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

      {shot?.formal_keyframe_artifact_id ? (
        <section>
          <h2>关键帧</h2>
          <MediaReviewCanvas
            imageUrl={artifactContentUrl(projectId, shot.formal_keyframe_artifact_id)}
            regions={regions}
            mode="region"
            onAddRegion={(region) => {
              if (!shotId || !note.trim()) return;
              addAnnotation.mutate({
                artifact_id: shot.formal_keyframe_artifact_id,
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
        <h2>视频时间线</h2>
        {shot?.formal_video_artifact_id ? (
          <VideoReviewTimeline durationSeconds={durationSeconds} annotations={videoRows} />
        ) : (
          <p className="muted">尚未选择正式视频，当前没有可供时间批注的正式产物。</p>
        )}
      </section>
      {addAnnotation.isError && (
        <div className="flash err">批注保存失败：{String(addAnnotation.error)}</div>
      )}
    </div>
  );
}
