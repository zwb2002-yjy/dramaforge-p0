const MODEL_SOURCE_LABELS: Record<string, string> = {
  project_profile: "项目模型方案",
  workspace_profile: "工作空间默认方案",
  system_default: "项目供应商绑定",
  request_override: "本次请求显式指定",
};

const MODEL_BLOCKER_LABELS: Record<string, string> = {
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
