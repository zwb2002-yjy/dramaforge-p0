import type { ShotLite } from "./api";
import type { ShotDesignDraft } from "./ShotDesignPanel";

export interface StoredShotDraft {
  projectId: string;
  shotId: string;
  baselineVersion: number;
  draft: ShotDesignDraft;
  /** Editable input baseline; absent only in pre-existing browser recovery records. */
  baseline?: ShotDesignDraft;
  updatedAt: string;
}

export interface FieldConflict {
  field: string;
  label: string;
  localValue: unknown;
  serverValue: unknown;
  baselineValue?: unknown;
}

function storageKey(projectId: string, shotId: string): string {
  return `df:shot-draft:${projectId}:${shotId}`;
}

export function saveShotDraft(
  projectId: string,
  shotId: string,
  baselineVersion: number,
  draft: ShotDesignDraft,
  baseline?: ShotDesignDraft,
): boolean {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return false;
    const previous = loadShotDraft(projectId, shotId);
    const original = previous?.baseline ?? baseline;
    const payload: StoredShotDraft = {
      projectId,
      shotId,
      baselineVersion: previous?.baseline ? previous.baselineVersion : baselineVersion,
      draft,
      baseline: original,
      updatedAt: new Date().toISOString(),
    };
    window.sessionStorage.setItem(storageKey(projectId, shotId), JSON.stringify(payload));
    return true;
  } catch {
    // Quota exceeded or storage disabled
    return false;
  }
}

export function loadShotDraft(projectId: string, shotId: string): StoredShotDraft | null {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    const raw = window.sessionStorage.getItem(storageKey(projectId, shotId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredShotDraft;
    if (parsed.projectId !== projectId || parsed.shotId !== shotId) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearShotDraft(projectId: string, shotId: string): void {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return;
    window.sessionStorage.removeItem(storageKey(projectId, shotId));
  } catch {
    // Ignore storage errors
  }
}

export function detectDraftConflicts(
  serverShot: ShotLite,
  stored: StoredShotDraft,
): { hasConflict: boolean; conflicts: FieldConflict[] } {
  const conflicts: FieldConflict[] = [];

  // Version unchanged => clean draft, no server conflict
  if (serverShot.version === stored.baselineVersion) {
    return { hasConflict: false, conflicts: [] };
  }

  if (stored.baseline) {
    const server = editableInputs(shotDraftFromServer(serverShot));
    for (const change of changesBetween(
      editableInputs(stored.baseline),
      editableInputs(stored.draft),
    )) {
      const current = valueAt(server, change.path);
      if (!same(current, change.before) && !same(current, change.after)) {
        conflicts.push({
          field: fieldName(change.path),
          label: fieldName(change.path),
          baselineValue: change.before,
          localValue: change.after,
          serverValue: current,
        });
      }
    }
    return { hasConflict: conflicts.length > 0, conflicts };
  }

  // Check prompt differences
  if (
    stored.draft.image_prompt !== undefined &&
    stored.draft.image_prompt !== (serverShot.image_prompt ?? "")
  ) {
    conflicts.push({
      field: "image_prompt",
      label: "生图提示词",
      localValue: stored.draft.image_prompt,
      serverValue: serverShot.image_prompt ?? "",
    });
  }

  if (
    stored.draft.video_prompt !== undefined &&
    stored.draft.video_prompt !== (serverShot.video_prompt ?? "")
  ) {
    conflicts.push({
      field: "video_prompt",
      label: "视频提示词",
      localValue: stored.draft.video_prompt,
      serverValue: serverShot.video_prompt ?? "",
    });
  }

  if (
    stored.draft.dialogue !== undefined &&
    stored.draft.dialogue !== (serverShot.dialogue ?? "")
  ) {
    conflicts.push({
      field: "dialogue",
      label: "对白",
      localValue: stored.draft.dialogue,
      serverValue: serverShot.dialogue ?? "",
    });
  }

  // Check generation settings differences
  const localDirector = (stored.draft.director_state ?? {}) as Record<string, unknown>;
  const serverDirector = (serverShot.director_state ?? {}) as Record<string, unknown>;

  const localGen = (localDirector.generation_settings ?? {}) as Record<string, unknown>;
  const serverGen = (serverDirector.generation_settings ?? {}) as Record<string, unknown>;

  const allStages = Array.from(new Set([...Object.keys(localGen), ...Object.keys(serverGen)]));
  for (const stage of allStages) {
    const localStage = (localGen[stage] ?? {}) as Record<string, unknown>;
    const serverStage = (serverGen[stage] ?? {}) as Record<string, unknown>;
    const stageLabel = stage === "video" ? "视频" : stage === "image" ? "图片" : stage;

    if (localStage.mode_id !== serverStage.mode_id) {
      conflicts.push({
        field: `generation_settings.${stage}.mode_id`,
        label: `${stageLabel}生成模式`,
        localValue: localStage.mode_id,
        serverValue: serverStage.mode_id,
      });
    }

    if (localStage.request_duration_seconds !== serverStage.request_duration_seconds) {
      conflicts.push({
        field: `generation_settings.${stage}.request_duration_seconds`,
        label: `${stageLabel}生成时长`,
        localValue: localStage.request_duration_seconds,
        serverValue: serverStage.request_duration_seconds,
      });
    }

    if (localStage.prompt_override !== serverStage.prompt_override) {
      conflicts.push({
        field: `generation_settings.${stage}.prompt_override`,
        label: `${stageLabel}提示词覆盖`,
        localValue: localStage.prompt_override,
        serverValue: serverStage.prompt_override,
      });
    }

    if (
      JSON.stringify(localStage.common_options ?? {}) !==
      JSON.stringify(serverStage.common_options ?? {})
    ) {
      conflicts.push({
        field: `generation_settings.${stage}.common_options`,
        label: `${stageLabel}常用参数`,
        localValue: localStage.common_options ?? {},
        serverValue: serverStage.common_options ?? {},
      });
    }

    if (
      JSON.stringify(localStage.native_options ?? {}) !==
      JSON.stringify(serverStage.native_options ?? {})
    ) {
      conflicts.push({
        field: `generation_settings.${stage}.native_options`,
        label: `${stageLabel}专有参数`,
        localValue: localStage.native_options ?? {},
        serverValue: serverStage.native_options ?? {},
      });
    }
  }

  // Check general director state differences (outside generation_settings)
  const localOther = { ...localDirector };
  delete localOther.generation_settings;
  const serverOther = { ...serverDirector };
  delete serverOther.generation_settings;
  if (JSON.stringify(localOther) !== JSON.stringify(serverOther)) {
    conflicts.push({
      field: "director_state",
      label: "导演状态设置",
      localValue: localOther,
      serverValue: serverOther,
    });
  }

  return {
    hasConflict: conflicts.length > 0,
    conflicts,
  };
}

type InputChange = { path: string[]; before: unknown; after: unknown };
export type DraftConflictChoices = Record<string, "local" | "server">;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function editableInputs(draft: ShotDesignDraft): Record<string, unknown> {
  return {
    image_prompt: draft.image_prompt,
    video_prompt: draft.video_prompt,
    ...(draft.dialogue === undefined ? {} : { dialogue: draft.dialogue }),
    director_state: draft.director_state,
  };
}

export function shotDraftFromServer(
  shot: Pick<ShotLite, "dialogue" | "image_prompt" | "video_prompt" | "director_state">,
): ShotDesignDraft {
  return {
    dialogue: shot.dialogue ?? "",
    image_prompt: shot.image_prompt ?? "",
    video_prompt: shot.video_prompt ?? "",
    director_state: structuredClone(shot.director_state ?? {}),
    director_state_text: JSON.stringify(shot.director_state ?? {}, null, 2),
  };
}

function changesBetween(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  path: string[] = [],
): InputChange[] {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((key) => {
    if (["__proto__", "constructor", "prototype"].includes(key)) return [];
    const left = before[key],
      right = after[key],
      nextPath = [...path, key];
    if (record(left) || record(right)) {
      return changesBetween(record(left) ? left : {}, record(right) ? right : {}, nextPath);
    }
    return same(left, right) ? [] : [{ path: nextPath, before: left, after: right }];
  });
}

function valueAt(value: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = value;
  for (const key of path) current = record(current) ? current[key] : undefined;
  return current;
}

function fieldName(path: string[]): string {
  return (path[0] === "director_state" && path.length > 1 ? path.slice(1) : path).join(".");
}

function setAt(target: Record<string, unknown>, path: string[], value: unknown): void {
  let current = target;
  for (const key of path.slice(0, -1)) {
    if (!record(current[key])) current[key] = {};
    current = current[key] as Record<string, unknown>;
  }
  const key = path[path.length - 1];
  if (value === undefined) delete current[key];
  else current[key] = structuredClone(value);
}

/** Rebase only the local edits; every concurrent field needs an explicit choice. */
export function restoreShotDraft(
  serverShot: ShotLite,
  stored: StoredShotDraft,
  choices: DraftConflictChoices = {},
): ShotDesignDraft {
  const { conflicts } = detectDraftConflicts(serverShot, stored);
  if (conflicts.some((item) => !choices[item.field]))
    throw new Error("请逐项选择保留本地修改或采用服务端值");
  const result = editableInputs(shotDraftFromServer(serverShot));
  if (stored.baseline) {
    for (const change of changesBetween(
      editableInputs(stored.baseline),
      editableInputs(stored.draft),
    )) {
      if (choices[fieldName(change.path)] !== "server") setAt(result, change.path, change.after);
    }
  } else {
    // Old records have no original values, so do not infer which differences were local edits.
    Object.assign(result, structuredClone(editableInputs(stored.draft)));
    for (const conflict of conflicts) {
      if (choices[conflict.field] === "server") {
        const path =
          conflict.field === "director_state" || !conflict.field.startsWith("generation_settings.")
            ? [conflict.field]
            : ["director_state", ...conflict.field.split(".")];
        if (conflict.field === "director_state" && record(result.director_state)) {
          const generation = result.director_state.generation_settings;
          result.director_state = {
            ...(record(conflict.serverValue) ? conflict.serverValue : {}),
            ...(generation === undefined ? {} : { generation_settings: generation }),
          };
        } else setAt(result, path, conflict.serverValue);
      }
    }
  }
  const restored = result as ShotDesignDraft;
  restored.director_state_text = JSON.stringify(restored.director_state, null, 2);
  // An unfinished advanced edit remains recoverable, never parsed or sent implicitly.
  if (stored.draft.director_state_text) {
    try {
      JSON.parse(stored.draft.director_state_text);
    } catch {
      restored.director_state_text = stored.draft.director_state_text;
    }
  }
  return restored;
}
