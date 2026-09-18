/**
 * Experiment branch stage vocabulary.
 *
 * A model experiment replaces exactly one production stage and compares its
 * candidate against the formal result, so the stage is part of the experiment's
 * identity: it selects which model purpose applies (image/keyframe versus
 * video) and which adoption scopes are legal — `keyframe_keep_video` and
 * `keyframe_rerun_downstream` only exist for a keyframe branch. The stage is
 * therefore chosen when the experiment is created, never defaulted silently by
 * the caller: an image model started on a video branch is refused by the
 * backend with `MODEL_BINDING_MISSING`, and a keyframe experiment created as a
 * video branch can never offer the keyframe adoption scopes.
 */

import { ApiError } from "../../lib/api";
import type { ModelCandidateOperation } from "./modelCandidatesApi";

export type ExperimentStage = "keyframe" | "video";

export const EXPERIMENT_STAGE_ORDER: ExperimentStage[] = ["keyframe", "video"];

export const EXPERIMENT_STAGE_LABEL: Record<ExperimentStage, string> = {
  keyframe: "关键帧（图片模型）",
  video: "视频（视频模型）",
};

export const EXPERIMENT_STAGE_SHORT_LABEL: Record<ExperimentStage, string> = {
  keyframe: "关键帧",
  video: "视频",
};

export const EXPERIMENT_STAGE_OPERATION: Record<ExperimentStage, ModelCandidateOperation> = {
  keyframe: "image.generate",
  video: "video.generate",
};

/** Normalize a stored `parameters.target_node_key` into a known stage. */
export function experimentStageOf(value: unknown): ExperimentStage {
  return value === "keyframe" ? "keyframe" : "video";
}

/**
 * Chinese wording for the eligibility issue codes the provider layer reports.
 *
 * The raw codes stay available in the collapsed diagnostics; the open surface
 * explains what the Owner can act on.
 */
export const MODEL_ISSUE_LABEL: Record<string, string> = {
  MODEL_BINDING_DISABLED: "该模型的绑定已停用",
  PROVIDER_CONNECTION_DISABLED: "该模型所属的供应商连接已停用",
  MODEL_NOT_DOCUMENTED: "该模型尚未登记能力文档",
  MODEL_NOT_CONTRACT_TESTED: "该模型尚未完成契约测试",
  MODEL_NOT_ACCOUNT_VERIFIED: "该模型尚未完成账号验证",
  MODEL_QUALITY_GATE_MISSING: "该模型尚未通过画质验收",
  MODEL_NOT_IN_CATALOG: "该模型不在模型目录中",
  MODEL_NO_INVOKE_VALUE: "该模型缺少调用标识",
  MODEL_LIFECYCLE_INACTIVE: "该模型已下线",
  CATALOG_MISMATCH: "模型目录与供应商连接不一致",
  MANIFEST_HASH_MISMATCH: "模型能力清单与目录不一致",
  CAPABILITY_REQUIRED_MISSING: "该模型缺少本阶段需要的能力",
  REFERENCE_MODE_CONFLICT: "参考图模式冲突",
};

export function modelIssueLabels(codes: string[]): string {
  const labels = codes.map((code) => MODEL_ISSUE_LABEL[code] ?? "未通过资格检查");
  return [...new Set(labels)].join("；");
}

/**
 * Quality certification is evidence, not an admission gate (decision 2026-09-19).
 *
 * A binding without it runs — normal production and the experiment line — so the
 * form states what is missing instead of refusing the model.
 */
export function certificationNotice(): string {
  return "尚未通过质量验收（可用于生成，正式支持证据待补齐）。";
}

/**
 * Explain a refused experiment request in product terms.
 *
 * `start` re-resolves the frozen model binding for the chosen stage, so a model
 * that has no binding for that stage (an image model on a video branch, for
 * example) is refused there. Saying which stage failed keeps the next action
 * obvious instead of surfacing the backend's English detail.
 */
export function experimentErrorMessage(error: unknown, stage: ExperimentStage): string {
  const stageLabel = EXPERIMENT_STAGE_SHORT_LABEL[stage];
  if (error instanceof ApiError) {
    const details = error.details as { code?: unknown; issues?: unknown } | null;
    const code = typeof details?.code === "string" ? details.code : error.code;
    if (code === "MODEL_BINDING_MISSING") {
      return `所选模型没有可用于${stageLabel}阶段的绑定，请改选阶段或模型。`;
    }
    if (code === "MODEL_INELIGIBLE") {
      const issues = Array.isArray(details?.issues)
        ? details.issues.filter((item): item is string => typeof item === "string")
        : [];
      return `所选模型当前不可用于${stageLabel}阶段：${
        issues.length ? modelIssueLabels(issues) : "未通过资格检查"
      }。`;
    }
    if (code === "QUEUE_UNAVAILABLE") {
      return "实验任务已记录，但未能进入执行队列，请在“高级恢复”中续跑这次实验。";
    }
    if (code === "DELIVERY_REVIEW_REQUIRED") {
      return "实验采用前需要先补齐人工审查决定。";
    }
    if (error.status === 409) {
      return "该实验已经做出决定，请刷新后查看最新状态。";
    }
  }
  return "实验请求未被接受，请确认镜头、阶段与模型后重试。";
}

/** Raw backend detail, kept for the collapsed read-only diagnostics block. */
export function experimentErrorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
