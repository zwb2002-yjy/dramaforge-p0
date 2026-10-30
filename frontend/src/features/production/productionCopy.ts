export const productionCopy = {
  views: [
    { id: "progress", label: "作品进度" },
    { id: "workflow", label: "生成任务" },
    { id: "experiments", label: "版本尝试" },
    { id: "advanced", label: "导演手法" },
  ],
  sceneFilters: [
    { value: "all", label: "全部场景" },
    { value: "unfinished", label: "未完成" },
    { value: "risk", label: "仅看风险" },
  ],
  scopeLabel: "修改范围",
  scopes: [
    { value: "scene", label: "整个场景" },
    { value: "shot", label: "单个镜头" },
  ],
} as const;
