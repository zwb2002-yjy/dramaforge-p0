const MODEL_SOURCE_LABELS: Record<string, string> = {
  project_profile: "项目模型方案",
  workspace_profile: "工作空间默认方案",
  system_default: "项目供应商绑定",
  legacy_project_binding: "历史项目绑定（兼容配置）",
  request_override: "本次请求显式指定",
};

export const modelPreflightCopy = {
  failed: "预检未通过",
  configure: "去设置模型",
  diagnostics: "诊断详情",
};

export const MODEL_CONTRACT_BLOCKER_LABELS: Record<string, string> = {
  MODEL_OFFICIAL_EVIDENCE_GAP: "官方证据尚未覆盖当前合同的全部执行字段",
  MODEL_LIFECYCLE_INACTIVE: "当前模型版本不可用于生成",
  DYNAMIC_MODEL_CAPABILITY_UNVERIFIED: "远端模型的精确能力尚未确认",
  MODEL_CONTRACT_NOT_TESTED: "候选能力尚未接入执行",
  CATALOG_MANIFEST_HASH_MISMATCH: "合同内容不一致，需要维护核对",
  MODEL_CONTRACT_SCHEMA_UNSUPPORTED: "该合同版本尚未支持执行",
};

const MODEL_BLOCKER_LABELS: Record<string, string> = {
  ...MODEL_CONTRACT_BLOCKER_LABELS,
  MODEL_BINDING_MISSING: "尚未选择可执行的供应商模型绑定",
  MODEL_BINDING_UNAVAILABLE: "已选模型绑定当前不可用",
  MODEL_ACCOUNT_NOT_VERIFIED: "模型所属连接尚未完成认证",
  MODEL_CAPABILITY_MISMATCH: "已选模型不支持此生成环节",
  MODEL_CONNECTION_REVISION_MISSING: "模型连接缺少可冻结的凭证版本",
  PROVIDER_CONNECTION_UNAVAILABLE: "模型所属供应商连接当前不可用",
  PROVIDER_CONNECTION_REVISION_MISSING: "供应商连接缺少不可变执行修订",
  PROVIDER_CREDENTIAL_REVISION_MISSING: "供应商连接引用的凭据修订不可用",
  REQUESTED_MODEL_ID_MISMATCH: "本次指定模型与绑定不一致",
};

export function executionModelSourceLabel(source: string): string {
  return MODEL_SOURCE_LABELS[source] ?? "已解析来源";
}

export function executionModelBlockerLabel(reason: string | null | undefined): string {
  if (!reason) return "没有返回可执行绑定";
  return MODEL_BLOCKER_LABELS[reason] ?? "模型配置尚未满足执行条件";
}
