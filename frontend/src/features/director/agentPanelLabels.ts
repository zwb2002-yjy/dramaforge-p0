import { ApiError } from "../../lib/api";

const labels: Record<string, string> = {
  queued: "等待导演处理",
  thinking: "导演分析中",
  completed: "本轮已完成",
  failed: "本轮未完成",
  cancelled: "已停止",
  stale: "内容已变化，请重新核对",
  pending: "待处理",
  running: "处理中",
  succeeded: "已完成",
};

export function agentStatusLabel(value?: string | null): string {
  return value ? (labels[value] ?? "状态待核对") : "尚未开始";
}
const errors: Record<string, string> = {
  DIRECTOR_AGENT_TOOLS_UNAVAILABLE: "当前文本模型未启用工具协作，请到模型设置选择工具协作连接。",
  DIRECTOR_CHECKPOINT_NOT_CONFIGURED: "导演服务尚未就绪，请检查服务配置后再发送。",
  DIRECTOR_AGENT_THREAD_BUSY: "此会话已有正在处理的请求，请先核对状态或停止该轮。",
  DIRECTOR_AGENT_CSRF_UNAVAILABLE: "无法确认请求身份，尚未发送。请检查连接后再次发送。",
  PROPOSAL_STALE: "镜头版本已变化，请重新核对建议。",
};

export function agentErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof ApiError) {
    const code = typeof error.details.code === "string" ? error.details.code : error.code;
    return errors[code] ?? "操作未完成，请核对状态；诊断中可查看错误详情。";
  }
  return "连接或操作未完成，请核对状态；诊断中可查看错误详情。";
}

export function agentProposalResultLabel(status: string, items: string[]): string {
  if (status === "stale" || items.includes("stale")) return "建议已过期";
  if (items.length && items.every((item) => item === "accepted")) return "建议已采纳";
  if (items.length && items.every((item) => item === "rejected")) return "建议已拒绝";
  if (items.includes("failed")) return "建议未能全部处理";
  return status === "applied" || status === "decided" ? "建议已处理" : "建议状态待核对";
}
