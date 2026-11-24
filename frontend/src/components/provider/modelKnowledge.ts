import type { components } from "../../shared/api/generated";
import { executionModelBlockerLabel } from "../../lib/modelResolutionLabels";

export type ModelKnowledge = components["schemas"]["ModelKnowledgeRead"];
export type KnowledgeOperation = components["schemas"]["TypedOperation"];
export type KnowledgeParameter = components["schemas"]["TypedParameter"];
export type KnowledgeBound = components["schemas"]["CapabilityBound"];
export type KnowledgeContract = components["schemas"]["TypedInputContract"];
export type KnowledgeConstraint = components["schemas"]["TypedConstraint"];

export const OPERATION_LABEL: Record<string, string> = {
  "image.generate": "图像生成",
  "image.edit": "图像编辑",
  "image.extend": "图像扩展",
  "image.layer_decomposition": "图像分层",
  "image.interactive_edit": "交互式图像编辑",
  "video.generate": "视频生成",
  "video.edit": "视频编辑",
  "video.extend": "视频延长",
};
export const ROLE_LABEL: Record<string, string> = {
  first_frame: "首帧",
  last_frame: "尾帧",
  reference_image: "参考图像",
  reference_video: "参考视频",
  reference_audio: "参考音频",
  source_image: "源图像",
  source_video: "源视频",
};
const PARAMETER_LABEL: Record<string, string> = {
  prompt: "提示词",
  duration_seconds: "时长（秒）",
  seconds: "时长",
  resolution: "分辨率",
  size: "尺寸",
  aspect_ratio: "画面比例",
  seed: "随机种子",
  n: "输出数量",
  generate_audio: "生成音频",
  watermark: "水印",
  aigc_watermark: "生成内容标识",
  response_format: "返回格式",
  output_format: "输出格式",
  draft: "样片模式",
  prompt_expansion_mode: "提示词扩展",
  mode: "输入方式（自动确定）",
  remote_id_field: "任务标识字段",
  result_field: "结果字段",
  terminal_states: "结束状态",
  maximum_layers: "图层上限",
  fps: "帧率",
  container: "产物容器",
};
const DIMENSION_LABEL: Record<string, string> = {
  min_pixels: "最少像素",
  max_pixels: "最多像素",
  min_aspect_ratio: "最小宽高比",
  max_aspect_ratio: "最大宽高比",
  min_width: "最小宽度",
  max_width: "最大宽度",
  min_height: "最小高度",
  max_height: "最大高度",
};
export const CLAIM_LABEL: Record<string, string> = {
  documented_supported: "已审核记录",
  documented_unsupported: "官方明确不支持",
  conflicting: "来源存在冲突",
  unknown: "尚未核实",
};
export const CONTROL_LABEL: Record<string, string> = {
  native: "原生字段",
  derived: "按规则计算",
  prompt_only: "仅提示词",
  unsupported: "不支持",
  unknown: "尚未确认",
};

export function parameterLabel(name: string): string {
  return PARAMETER_LABEL[name] ?? ROLE_LABEL[name] ?? name;
}

export function createBlockerLabel(code: string | null | undefined): string {
  if (!code) return "仍需核验当前连接和输入";
  return executionModelBlockerLabel(code);
}

export function boundLabel(bound: KnowledgeBound | undefined, unit = ""): string {
  if (!bound || bound.kind === "unknown") return "待核实";
  if (bound.claim_status !== "documented_supported") return "尚未核实或存在冲突";
  if (bound.kind === "unlimited") return "无上限（官方明确）";
  return `${bound.value}${unit}${bound.inclusive === false ? "（不含边界）" : ""}`;
}

export function literalLabel(value: unknown): string {
  if (value === true) return "是";
  if (value === false) return "否";
  if (value === null || value === undefined) return "未声明";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function valueLabel(name: string, value: unknown): string {
  if (name === "mode" && typeof value === "string")
    return (
      ({ text: "文本", keyframe: "关键帧", reference: "参考素材" } as Record<string, string>)[
        value
      ] ?? "其他输入方式"
    );
  return literalLabel(value);
}

export function pointerSegment(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

export function parameterValue(parameter: KnowledgeParameter, name = ""): string {
  if (parameter.claim_status === "documented_unsupported") return "不可使用该参数";
  const parts: string[] = [];
  if (parameter.required) parts.push("必填");
  else if (parameter.required == null) parts.push("必填规则待核实");
  if (parameter.enum.length)
    parts.push(parameter.enum.map((value) => valueLabel(name, value)).join("、"));
  else if (["integer", "number"].includes(parameter.type))
    parts.push(`最小 ${boundLabel(parameter.minimum)}；最大 ${boundLabel(parameter.maximum)}`);
  else if (parameter.type === "string")
    parts.push(
      `最短 ${boundLabel(parameter.min_length, " 字符")}；最长 ${boundLabel(parameter.max_length, " 字符")}`,
    );
  if (parameter.default_status === "documented_supported")
    parts.push(`默认 ${literalLabel(parameter.default)}`);
  if (parameter.multiple_of) parts.push(`${parameter.multiple_of} 的倍数`);
  const dimensions = Object.entries(parameter.dimension_bounds ?? {});
  if (dimensions.length)
    parts.push(
      `自定义宽×高：${dimensions.map(([key, limit]) => `${DIMENSION_LABEL[key] ?? key} ${boundLabel(limit)}`).join("；")}`,
    );
  return parts.join("；") || "取值限制尚未核实";
}

export function protocolFactValue(fact: KnowledgeParameter): string {
  if (fact.enum.length) return fact.enum.map(literalLabel).join("、");
  return literalLabel(fact.default);
}

export function constraintLabel(rule: KnowledgeConstraint): string {
  const when = Object.entries(rule.when ?? {}).map(
    ([name, value]) => `${parameterLabel(name)}为${valueLabel(name, value)}`,
  );
  when.push(...rule.when_present.map((name) => `提供${parameterLabel(name)}`));
  const effects: string[] = [];
  if (rule.require.length)
    effects.push(
      `${rule.kind === "requires_any" ? "至少包含其中一项" : "必须包含"}：${rule.require.map(parameterLabel).join("、")}`,
    );
  if (rule.forbid.length)
    effects.push(`不能同时提供：${rule.forbid.map(parameterLabel).join("、")}`);
  for (const [name, values] of Object.entries(rule.allowed ?? {}))
    effects.push(`${parameterLabel(name)}仅允许${values.map(literalLabel).join("、")}`);
  if (rule.kind === "forced" && rule.target)
    effects.push(`${parameterLabel(rule.target)}自动固定为${valueLabel(rule.target, rule.value)}`);
  if (rule.kind === "derived" && rule.target)
    effects.push(
      `${parameterLabel(rule.target)}根据${rule.derivation === "reference_count" ? "参考素材数量" : "参考素材合计时长"}计算`,
    );
  if (rule.kind === "sum_limit")
    effects.push(
      `${rule.sum_fields.map(parameterLabel).join("、")}合计不超过${literalLabel(rule.value)}`,
    );
  return `${when.length ? `当${when.join("且")}时，` : ""}${effects.join("；") || rule.description || "组合规则尚未明确"}`;
}

export function contractLabel(contract: KnowledgeContract): string {
  const roles = Object.keys(contract.input_slots ?? {});
  return roles.length ? roles.map((role) => ROLE_LABEL[role] ?? "其他素材").join("、") : "文本";
}

export function parameterEvidence(knowledge: ModelKnowledge, path: string, status: string): string {
  const field = knowledge.fields.find((item) => item.path === path);
  const children = knowledge.fields.filter((item) => item.path.startsWith(`${path}/`));
  if ([field, ...children].some((item) => item?.claim_status === "conflicting"))
    return CLAIM_LABEL.conflicting;
  if (
    [field, ...children].some(
      (item) => item?.blocker && item.claim_status === "documented_supported",
    )
  )
    return "来源核验未通过";
  if (children.some((item) => item.claim_status === "documented_unsupported"))
    return "含明确不支持项";
  if (children.some((item) => item.claim_status === "unknown")) return "部分限制待核实";
  return CLAIM_LABEL[field?.claim_status ?? status] ?? CLAIM_LABEL.unknown;
}

export function groupEvidence(knowledge: ModelKnowledge, path: string, status: string): string {
  return parameterEvidence(knowledge, path, status);
}
