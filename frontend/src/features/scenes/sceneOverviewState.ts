import type { SceneSummary, ShotLite, ShotOverviewRead } from "./api";

export type SceneMediaFilter =
  | "all"
  | "missing-keyframe"
  | "missing-video"
  | "pending-review"
  | "generating"
  | "failed"
  | "outcome-unknown";
export const SCENE_MEDIA_FILTERS: { value: SceneMediaFilter; label: string }[] = [
  { value: "all", label: "全部镜头" },
  { value: "missing-keyframe", label: "缺正式画面" },
  { value: "missing-video", label: "缺正式视频" },
  { value: "pending-review", label: "待审镜头" },
  { value: "generating", label: "生成中" },
  { value: "failed", label: "失败或阻断" },
  { value: "outcome-unknown", label: "状态待核对" },
];

export function sceneMatchesFilter(scene: SceneSummary, filter: SceneMediaFilter): boolean {
  if (filter === "missing-keyframe") return scene.formal_keyframe_count < scene.shot_count;
  if (filter === "missing-video") return scene.formal_video_count < scene.shot_count;
  if (filter === "pending-review") return scene.pending_review_count > 0;
  if (filter === "generating") return scene.generating_count > 0;
  if (filter === "failed") return scene.failed_count > 0;
  if (filter === "outcome-unknown") return scene.unknown_count > 0;
  return true;
}

export function shotMatchesFilter(
  shot: ShotLite,
  facts: ShotOverviewRead | undefined,
  filter: SceneMediaFilter,
): boolean {
  if (filter === "missing-keyframe") return !shot.formal_keyframe_artifact_id;
  if (filter === "missing-video") return !shot.formal_video_artifact_id;
  if (filter === "pending-review") return facts?.pending_review === true;
  if (filter === "generating") return facts?.generating === true;
  if (filter === "failed") return facts?.generation_failed === true;
  if (filter === "outcome-unknown") return facts?.outcome_unknown === true;
  return true;
}
