import type { components } from "../../shared/api/generated";
import type { ProjectRead } from "./api";

export type ProjectWorkType = components["schemas"]["ProjectCreate"]["work_type"];
export type ProjectPatch = components["schemas"]["ProjectUpdate"];
export const WORK_TYPE_LABELS: Record<ProjectWorkType, string> = {
  animation_promo: "动画宣传片",
  single_comic: "单集漫剧",
  serial_comic: "多集连续漫剧",
};

export type ProjectIntentValues = {
  name: string;
  workType: ProjectWorkType | "";
  creativeGoal: string;
  audience: string;
  duration: string;
  episodeCount: string;
};

export const EMPTY_PROJECT_INTENT: ProjectIntentValues = {
  name: "新作品",
  workType: "",
  creativeGoal: "",
  audience: "",
  duration: "",
  episodeCount: "",
};

export function projectIntentValues(project: ProjectRead): ProjectIntentValues {
  return {
    name: project.name,
    workType: project.work_type ?? "",
    creativeGoal: project.creative_goal ?? "",
    audience: project.audience ?? "",
    duration: project.planned_duration_seconds ?? "",
    episodeCount:
      project.planned_episode_count == null ? "" : String(project.planned_episode_count),
  };
}

type IntentInput = Pick<
  ProjectRead,
  "name" | "creative_goal" | "audience" | "planned_duration_seconds" | "planned_episode_count"
> & { work_type?: ProjectWorkType };

export function projectIntentInput(values: ProjectIntentValues): IntentInput {
  return {
    name: values.name.trim(),
    work_type: values.workType || undefined,
    creative_goal: values.creativeGoal ?? "",
    audience: values.audience ?? "",
    planned_duration_seconds: values.duration?.trim() || null,
    planned_episode_count:
      values.workType === "animation_promo" || !values.episodeCount?.trim()
        ? null
        : Number(values.episodeCount),
  };
}

export const INTENT_FIELDS = [
  "name",
  "work_type",
  "creative_goal",
  "audience",
  "planned_duration_seconds",
  "planned_episode_count",
] as const;

export const INTENT_LABELS: Record<(typeof INTENT_FIELDS)[number], string> = {
  name: "项目名",
  work_type: "作品类型",
  creative_goal: "创作目标",
  audience: "受众",
  planned_duration_seconds: "目标总时长（秒）",
  planned_episode_count: "计划集数",
};

export function projectIntentPatch(
  project: ProjectRead,
  values: ProjectIntentValues,
): ProjectPatch {
  const before = projectIntentInput(projectIntentValues(project));
  const after = projectIntentInput(values);
  const patch: Omit<ProjectPatch, "expected_version"> = {};
  function copyChange<K extends keyof IntentInput>(key: K) {
    if (after[key] !== undefined && after[key] !== before[key]) patch[key] = after[key];
  }
  INTENT_FIELDS.forEach(copyChange);
  return { expected_version: project.version, ...patch };
}

export function rebaseProjectIntent(
  previous: ProjectRead,
  current: ProjectRead,
  draft: ProjectIntentValues,
): ProjectIntentValues {
  const before = projectIntentValues(previous);
  const merged = projectIntentValues(current);
  function retain<K extends keyof ProjectIntentValues>(key: K) {
    if (draft[key] !== before[key]) merged[key] = draft[key];
  }
  const fields: (keyof ProjectIntentValues)[] = [
    "name",
    "workType",
    "creativeGoal",
    "audience",
    "duration",
    "episodeCount",
  ];
  fields.forEach(retain);
  return merged;
}
