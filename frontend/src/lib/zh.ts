/**
 * 前端中文化映射（用户可见文本）。
 *
 * 只负责把 API/领域原始值（status、error_code、node_key 等）翻译成中文展示。
 * 原始值作为契约保持不变：这里只做显示层映射，不改变调用方拿到的数据。
 */

export const ZH_STATUS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  leased: "已租约",
  completed: "已完成",
  cached: "缓存命中",
  completed_after_cancel: "取消后完成",
  failed: "失败",
  cancelled: "已取消",
  blocked_budget: "预算阻断",
};

export function zhStatus(status: string | null | undefined): string {
  if (!status) return "—";
  return ZH_STATUS[status] ?? status;
}

export const ZH_REVIEW_STATE: Record<string, string> = {
  passed: "通过",
  blocked: "被阻断",
  needs_human: "需人工复核",
  failed: "失败",
  not_applicable: "不适用",
  pending: "待定",
};

export const ZH_EVIDENCE_STATE: Record<string, string> = {
  documented: "已文档化",
  contract_tested: "已合同测试",
  account_verified: "已账号验证",
  quality_gated: "已质量门禁",
};

export function zhEvidenceState(state: string | null | undefined): string {
  if (!state) return "—";
  return ZH_EVIDENCE_STATE[state] ?? state;
}

export const ZH_NODE: Record<string, string> = {
  prompt: "提示词",
  keyframe: "关键帧",
  face_review: "人脸审核",
  video: "视频",
  video_drift_review: "视频漂移审核",
  voice: "配音",
  subtitle: "字幕",
  composite: "合成",
  continuity_review: "连续性审核",
};

export function zhNode(node: string | null | undefined): string {
  if (!node) return "?";
  return ZH_NODE[node] ?? node;
}

export const ZH_ERROR_CODE: Record<string, string> = {
  PROVIDER_NOT_CONFIGURED: "Provider 未配置",
  MODEL_BINDING_NOT_VERIFIED: "模型绑定未验证",
  CANONICAL_REFERENCE_REQUIRED: "缺少主角参考",
  UPSTREAM_RUN_MISSING: "上游运行缺失",
  UPSTREAM_TERMINAL_FAILURE: "上游阻断失败",
  UPSTREAM_ARTIFACT_MISSING: "上游产物缺失",
  PROVIDER_TASK_PENDING: "Provider 任务处理中",
  PROVIDER_SUBMISSION_UNKNOWN: "Provider 提交结果未知",
  PROVIDER_CREATE_FAILED: "Provider 创建失败",
  PROVIDER_TASK_FAILED: "Provider 任务失败",
  PROVIDER_MEDIA_DOWNLOAD_FAILED: "Provider 媒体下载失败",
  PROVIDER_FAILED: "Provider 失败",
  PROVIDER_UNAVAILABLE: "Provider 不可用",
  PROVIDER_BAD_REQUEST: "Provider 请求被拒绝",
  PROVIDER_RATE_LIMITED: "Provider 限流",
  PROVIDER_POLL_TIMEOUT: "Provider 轮询超时",
  PROVIDER_POLL_TRANSIENT: "Provider 轮询瞬时错误",
  PROVIDER_RESPONSE_INVALID: "Provider 响应无效",
  PROVIDER_REQUEST_FAILED: "Provider 请求失败",
  FACE_BELOW_THRESHOLD: "人脸分数低于阈值",
  FACE_PROBE_UNAVAILABLE: "人脸探针不可用",
  FACE_POLICY_MISSING: "人脸策略缺失",
  FACE_POLICY_MISMATCH: "人脸策略不匹配",
  VIDEO_DRIFT_BLOCKED: "视频漂移阻断",
  VIDEO_DRIFT_POLICY_UNAPPROVED: "视频漂移策略未批准",
  blocked_budget: "预算阻断",
  QUEUE_UNAVAILABLE: "队列不可用",
  APPROVE_GATE: "审核门禁未通过",
  EXPORT_GATE: "导出门禁未通过",
  COMPOSITE_INPUT_MISSING: "合成输入缺失",
  COMPOSITE_RENDER_FAILED: "合成渲染失败",
  ARTIFACT_NOT_INDEPENDENT: "产物不独立",
  TEXT_LLM_NOT_CONFIGURED: "文本模型未配置",
  NODE_EXECUTION_FAILED: "节点执行失败",
  NODE_RUN_ALREADY_CLAIMED: "节点已被占用",
  VALIDATION_ERROR: "校验失败",
  NOT_FOUND: "未找到",
  UNAUTHORIZED: "未授权",
  FORBIDDEN: "无权限",
  CONFLICT: "冲突",
  HTTP_ERROR: "网络请求失败",
};

export function zhErrorCode(code: string | null | undefined): string {
  if (!code) return "—";
  return ZH_ERROR_CODE[code] ?? code;
}

/** 常见后端 error_summary 的结构化英文模式 → 中文。 */
const SUMMARY_PATTERNS: Array<[RegExp, (...m: string[]) => string]> = [
  [
    /required review (\w+) is (blocked|needs_human|failed)/,
    (_all, node: string, state: string) => `必需审核「${zhNode(node)}」${ZH_REVIEW_STATE[state] ?? state}`,
  ],
  [
    /required upstream (\w+) ended with (failed|blocked|cancelled)/,
    (_all, node: string, state: string) =>
      `必需上游「${zhNode(node)}」已${state === "failed" ? "失败" : state === "blocked" ? "阻断" : "取消"}`,
  ],
  [
    /required upstream run is missing: (\w+)/,
    (_all, node: string) => `必需上游运行缺失：「${zhNode(node)}」`,
  ],
  [
    /required upstream (\w+) has no result Artifact/,
    (_all, node: string) => `必需上游「${zhNode(node)}」无结果产物`,
  ],
  [
    /required upstream (\w+) Artifact is unavailable/,
    (_all, node: string) => `必需上游「${zhNode(node)}」产物不可用`,
  ],
  [
    /completed after cancel without explicit adoption/,
    () => "取消后完成但未获显式采用",
  ],
  [
    /current graph node is missing or belongs to another version/,
    () => "当前图节点缺失或属于另一版本",
  ],
];

/**
 * 把 error_code + error_summary 组合成一条完整中文错误说明。
 * 结构化的上游/审核错误会整句翻译；Provider 原始错误保留原文但前缀中文错误名。
 */
export function zhErrorSummary(
  code: string | null | undefined,
  summary: string | null | undefined,
): string {
  const name = zhErrorCode(code);
  const raw = (summary ?? "").trim();
  if (!raw) return name;
  for (const [pattern, render] of SUMMARY_PATTERNS) {
    const match = raw.match(pattern);
    if (match) return render(...match);
  }
  return `${name}：${raw}`;
}
