import type { DirectorStage, DirectorWorkflowStatus } from "./types";

export type DirectorStageDefinition = {
  id: DirectorStage;
  number: number;
  title: string;
  confirmation: string;
};

export const DIRECTOR_STAGES: DirectorStageDefinition[] = [
  { id: "creative", number: 1, title: "创作方案", confirmation: "故事、人物关系和对白方向" },
  { id: "shooting", number: 2, title: "拍摄方案", confirmation: "人物、声音、分镜、风险和模型方案" },
  { id: "trial", number: 3, title: "代表镜头试拍", confirmation: "试拍预算和真实效果" },
  { id: "production", number: 4, title: "正式生产与交付", confirmation: "正式预算、局部修复和成片" },
];

const STATUS_STAGE: Record<DirectorWorkflowStatus, DirectorStage> = {
  drafting_creative: "creative",
  awaiting_creative_confirmation: "creative",
  drafting_shooting_plan: "shooting",
  awaiting_shooting_confirmation: "shooting",
  awaiting_trial_authorization: "trial",
  trial_running: "trial",
  awaiting_trial_review: "trial",
  awaiting_production_authorization: "production",
  production_running: "production",
  repair_proposed: "production",
  awaiting_repair_authorization: "production",
  assembling: "production",
  final_review: "production",
  completed: "production",
  needs_human: "production",
  blocked: "production",
  cancelled: "production",
};

export function stageForStatus(status: DirectorWorkflowStatus): DirectorStage {
  return STATUS_STAGE[status];
}

export function stagePosition(stage: DirectorStage): number {
  return DIRECTOR_STAGES.findIndex((candidate) => candidate.id === stage);
}

export function stageState(
  candidate: DirectorStage,
  current: DirectorStage,
  workflowStatus: DirectorWorkflowStatus,
): "done" | "active" | "pending" {
  const candidateIndex = stagePosition(candidate);
  const currentIndex = stagePosition(current);
  if (candidateIndex < currentIndex) return "done";
  if (candidateIndex > currentIndex) return "pending";
  if (workflowStatus === "completed" && candidate === "production") return "done";
  return "active";
}

export const WORKFLOW_STATUS_ZH: Record<DirectorWorkflowStatus, string> = {
  drafting_creative: "正在准备创作方案",
  awaiting_creative_confirmation: "等待确认创作方案",
  drafting_shooting_plan: "正在准备拍摄方案",
  awaiting_shooting_confirmation: "等待确认拍摄方案",
  awaiting_trial_authorization: "等待试拍预算授权",
  trial_running: "代表镜头试拍中",
  awaiting_trial_review: "等待验收试拍",
  awaiting_production_authorization: "等待正式生产授权",
  production_running: "正式生产中",
  repair_proposed: "已有局部修复方案",
  awaiting_repair_authorization: "等待修复预算授权",
  assembling: "正在组装交付物",
  final_review: "等待逐镜验收",
  completed: "作品已完成",
  needs_human: "需要你查看证据",
  blocked: "存在必须解决的阻断项",
  cancelled: "创作已取消",
};

export const ACTION_ZH: Record<string, string> = {
  generate_concepts: "生成三个原创概念",
  import_script: "导入有权使用的剧本",
  propose_change: "提出修改并查看影响",
  confirm_creative_plan: "确认创作方案",
  generate_shooting_package: "生成拍摄方案",
  confirm_shooting_plan: "确认拍摄方案",
  authorize_trial_budget: "授权试拍预算",
  view_trial_progress: "查看试拍进度",
  review_trial: "验收代表镜头",
  authorize_production_budget: "授权正式生产预算",
  request_trial_repair: "修复代表镜头",
  view_production_progress: "查看生产进度",
  select_repair_option: "选择局部修复方案",
  authorize_repair_budget: "授权修复预算",
  view_assembly_progress: "查看组装进度",
  download_delivery: "下载完整交付包",
  open_professional_mode: "打开专业模式",
  review_evidence: "查看质量证据",
  resolve_blocker: "解决阻断项",
};

export const NEXT_ACTION_ZH: Record<DirectorWorkflowStatus, string> = {
  drafting_creative: "选择一种开始方式，先找到三个原创故事方向。",
  awaiting_creative_confirmation: "阅读完整剧本和预审结果，确认这是不是你想表达的故事。",
  drafting_shooting_plan: "让 AI 导演把已确认剧本整理成人物、声音、分镜、风险和成本方案。",
  awaiting_shooting_confirmation: "查看人物、分镜、风险和推荐模型，确认是否值得进入试拍。",
  awaiting_trial_authorization: "查看代表镜头和价格快照，设置本次试拍的最高预算。",
  trial_running: "代表镜头正在生成；完成前不会自动扩大生产范围。",
  awaiting_trial_review: "查看真实试拍与质量证据，决定修复还是继续。",
  awaiting_production_authorization: "试拍已具备决策证据；确认正式生产预算或先修复试拍。",
  production_running: "查看逐镜头进度；失败时只处理受影响的局部。",
  repair_proposed: "比较修复范围、成本和预期，选择一个定向方案。",
  awaiting_repair_authorization: "确认额外修复预算后，系统才会发起新媒体请求。",
  assembling: "镜头已通过生产门禁，正在组装成片和交付包。",
  final_review: "查看每个镜头的质量证据，逐镜接受、修复或停止。",
  completed: "作品与完整交付包已经可以下载。",
  needs_human: "自动证据不足或冲突，请查看证据后作决定。",
  blocked: "先解决当前配置、授权或硬质量阻断。",
  cancelled: "此创作流程已经取消。",
};
