/** Mainchain roles shared by default model selection and its read-only notice. */
export const WORKSPACE_MODEL_ROLES = [
  {
    id: "llm",
    label: "文本模型",
    capabilities: ["text.generate"],
    slots: ["planning.brief", "planning.script", "planning.storyboard"],
  },
  {
    id: "image",
    label: "图片模型",
    capabilities: ["image.generate"],
    slots: ["visual.character", "visual.storyboard", "visual.keyframe"],
  },
  {
    id: "video",
    label: "视频模型",
    capabilities: [
      "video.text_to_video",
      "video.image_to_video",
      "video.last_frame_to_video",
      "video.first_last_frame",
      "video.reference_to_video",
    ],
    slots: ["video.shot"],
  },
] as const;

export type WorkspaceModelRole = (typeof WORKSPACE_MODEL_ROLES)[number]["id"];
