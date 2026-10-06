export const providerConnectionCopy = {
  connection: "连接设置",
  provider: "服务类型",
  address: "服务地址",
  key: "API Key",
  savedKey: "已保存，留空不更换",
  newKey: "输入密钥",
  models: "已配置模型",
  addModel: "添加模型",
  closeAdd: "关闭添加模型",
  readModels: "读取目录",
  remoteModel: "模型",
  contract: "调用方案",
  image: "图片",
  video: "视频",
  details: "详情",
  project: "指定项目",
  diagnostics: "诊断与验证",
  emptyModels: "尚未添加模型",
  historical: "历史配置",
  configured: "已配置",
  unverified: "待验证",
  disabled: "已停用",
  unavailable: "不可用",
} as const;

/** Compact vocabulary for optional details, never appended to picker labels. */
export function modelInputSummary(capabilities: readonly string[]): string {
  const labels = new Set<string>();
  for (const capability of capabilities) {
    const label = {
      "image.t2i": "文本",
      "image.i2i": "图片",
      "video.t2v": "文本",
      "video.i2v.first_frame": "首帧",
      "video.i2v.last_frame": "尾帧",
      "video.reference.image": "参考图",
      "video.reference.video": "参考视频",
      "video.reference.audio": "参考音频",
    }[capability];
    if (label) labels.add(label);
  }
  return [...labels].join(" / ") || "未声明";
}
