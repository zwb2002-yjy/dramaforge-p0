import { Link } from "@tanstack/react-router";
import { Disclosure } from "../ui";
import type { ProjectWorkspaceView } from "./ProjectWorkspaceShell";
import "./project-stage-guide.css";

const guides = {
  script: {
    path: "/projects/$projectId/script",
    step: "01",
    title: "故事剧本",
    outcome: "已保存的故事、分场与镜头安排",
    next: "按需准备角色素材",
    to: "/projects/$projectId/assets",
    instructions: [
      "写下故事想法，或导入已有剧本。",
      "检查导演建议中的人物、场景和镜头，选择接受的内容。",
      "明确应用建议后，再进入素材或分镜；预览建议不会修改作品。",
    ],
  },
  assets: {
    path: "/projects/$projectId/assets",
    step: "02",
    title: "角色素材",
    outcome: "可复用的角色、场景与道具参考",
    next: "进入分镜制作",
    to: "/projects/$projectId/scenes",
    instructions: [
      "按角色、场景、道具整理素材，保持同一角色的形象一致。",
      "上传或生成候选，预览后明确选择使用的版本。",
      "在镜头中添加对应引用；素材入库不等于已经被镜头引用。",
    ],
  },
  scenes: {
    path: "/projects/$projectId/scenes",
    step: "03",
    title: "分镜制作",
    outcome: "每个镜头的画面与视频候选",
    next: "进入审片确认",
    to: "/projects/$projectId/review",
    instructions: [
      "选择场景和镜头，写清画面描述。",
      "添加角色与场景参考，保存镜头；按需选择导演手法。",
      "先生成与确认关键帧，再生成视频。预览候选不会自动替换正式版本。",
    ],
  },
  review: {
    path: "/projects/$projectId/review",
    step: "04",
    title: "审片确认",
    outcome: "完成检查、明确采用的镜头版本",
    next: "进入剪辑成片",
    to: "/projects/$projectId/edit",
    instructions: [
      "确认正在检查的是哪一个镜头和候选版本。",
      "查看画面与声音，用批注记录问题，需要时发起修复。",
      "人工审核与选择正式版本是独立动作；确认完成后再进入剪辑。",
    ],
  },
  edit: {
    path: "/projects/$projectId/edit",
    step: "05",
    title: "剪辑成片",
    outcome: "可下载的 MP4 成片与 SRT 字幕",
    next: "返回作品总览",
    to: "/projects/$projectId/production",
    instructions: [
      "用已确认的视频创建或打开剪辑时间线。",
      "调整顺序、时长与字幕后，点击保存。",
      "明确点击导出，等待成片完成后下载；离开页面不会自动再发起导出。",
    ],
  },
} as const;

export function ProjectStageGuide({
  projectId,
  view,
}: {
  projectId: string;
  view: ProjectWorkspaceView;
}) {
  const guide = view === "production" || view === "overview" ? null : guides[view];
  return (
    <aside
      className="project-stage-guide"
      aria-label="本步创作指引"
      data-testid="project-stage-guide"
    >
      <nav className="project-stage-steps" aria-label="创作流程">
        {Object.entries(guides).map(([key, item]) => (
          <Link
            key={key}
            to={item.path}
            params={{ projectId }}
            aria-current={view === key ? "page" : undefined}
            aria-label={`${item.step} ${item.title}`}
          >
            <span aria-hidden="true">{item.step}</span>
            {item.title}
          </Link>
        ))}
      </nav>
      {guide && (
        <div className="project-stage-guide-actions">
          <Disclosure title="操作指引">
            <p>本步产物：{guide.outcome}</p>
            <ol>
              {guide.instructions.map((instruction) => (
                <li key={instruction}>{instruction}</li>
              ))}
            </ol>
          </Disclosure>
          <Link className="project-stage-next" to={guide.to} params={{ projectId }}>
            {guide.next}
            <span aria-hidden="true"> →</span>
          </Link>
        </div>
      )}
    </aside>
  );
}
