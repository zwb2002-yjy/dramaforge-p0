export interface ReferencePurposeOption {
  value: string;
  label: string;
  description: string;
}

export const REFERENCE_PURPOSES: ReferencePurposeOption[] = [
  { value: "identity", label: "角色身份", description: "角色形象一致性" },
  { value: "clothing", label: "服装", description: "服装款式/颜色" },
  { value: "pose", label: "姿态", description: "身体姿态/构图" },
  { value: "action", label: "动作", description: "动作/运动参考" },
  { value: "camera_language", label: "镜头语言", description: "运镜/景别参考" },
  { value: "scene_layout", label: "场景布局", description: "空间/构图布局" },
  { value: "scene_lighting", label: "场景光照", description: "光线/氛围" },
  { value: "style", label: "风格", description: "整体美术风格" },
  { value: "audio_rhythm", label: "音频节奏", description: "节奏/节拍参考" },
  { value: "first_frame", label: "首帧", description: "视频首帧" },
  { value: "last_frame", label: "尾帧", description: "视频尾帧" },
  { value: "generic_reference", label: "通用参考", description: "通用图参考" },
];
