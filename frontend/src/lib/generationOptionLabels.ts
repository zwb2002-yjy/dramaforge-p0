const OPTION_LABELS: Record<string, string> = {
  aspect_ratio: "输出比例",
  size: "图片尺寸",
  duration_seconds: "视频生成时长（秒）",
  resolution: "分辨率",
  seed: "随机种子",
  generate_audio: "生成原生声音",
};

export function generationOptionLabel(name: string): string {
  return OPTION_LABELS[name] ?? name;
}

export const generationSettingsCopy = {
  image_keyframe: "画面生成参数",
  video: "视频生成参数",
  configure: "设置模型",
  loading: "正在读取模型合同…",
  failed: "无法读取当前模型参数，请检查模型设置。",
  save: "参数修改保存后生效；生成前仍需预检和确认。",
  inherit: "恢复继承",
  adopt: "采用模型固定值",
  fixed: "模型固定值",
  unavailable: "当前编译器未开放此参数",
  incompatible: "旧参数需要处理，预检前请移除或在模型方案中修正。",
  remove: "移除不兼容参数",
  model: "当前模型",
  current: "当前参数",
  fixedMismatch: "当前参数不符合模型固定输出；采用固定值后保存并重新预检。",
  unavailableGroup: "未开放参数",
  invalid: "当前值不符合模型合同，请修改或恢复继承",
  changedContract: "模型合同已变化，旧参数保留。请核对参数、参考和模式后保存，再重新预检。",
  acceptContract: "已核对，采用当前合同",
};

export function generationOptionSourceLabel(source: string): string {
  return (
    (
      {
        contract_default: "模型合同默认",
        project: "项目画幅",
        project_profile: "项目模型方案",
        workspace_profile: "工作空间默认方案",
        shot: "本镜头覆盖",
        shot_common: "本镜头常用参数",
        shot_native: "本镜头高级参数",
        shot_duration: "本镜头生成时长",
        compiler_fixed_default: "编译器固定默认",
      } as Record<string, string>
    )[source] ?? "继承设置"
  );
}
