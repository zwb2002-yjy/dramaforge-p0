const PURPOSE_LABELS: Record<string, string> = {
  identity: "角色身份",
  clothing: "服装造型",
  scene_layout: "空间布局",
  scene_lighting: "场景光线",
  style: "画面风格",
  action: "动作",
  pose: "姿态",
  camera_language: "镜头语言",
  audio_rhythm: "声音节奏",
  first_frame: "首帧",
  last_frame: "尾帧",
  generic_reference: "通用参考",
};

export function purposeLabel(value: string): string {
  return PURPOSE_LABELS[value] ?? "参考";
}
