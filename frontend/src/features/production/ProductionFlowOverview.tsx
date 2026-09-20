import { Link } from "@tanstack/react-router";

import { Badge, Disclosure } from "../../components/ui";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { zhErrorParts, zhNode } from "../../lib/zh";
import type { ProductionSummary } from "./api";
import "./production-flow.css";

// Navigation and wording only. Execution order, prerequisites and state remain
// owned by the server; these links never submit a production command.
const stages = [
  { key: "prompt", destination: "scenes", action: "编辑镜头描述" },
  { key: "keyframe", destination: "scenes", action: "生成与选择画面" },
  { key: "identity_review", destination: "review", action: "检查人物一致性" },
  { key: "video", destination: "scenes", action: "生成与选择视频" },
  { key: "video_drift_review", destination: "review", action: "审片与修复" },
  { key: "voice", destination: "edit", action: "进入成片准备" },
  { key: "subtitle", destination: "edit", action: "编辑字幕与时间线" },
  { key: "composite", destination: "edit", action: "进入成片导出" },
  { key: "continuity_review", destination: "edit", action: "查看成片交付" },
] as const;

const destinations = {
  scenes: "/projects/$projectId/scenes",
  review: "/projects/$projectId/review",
  edit: "/projects/$projectId/edit",
} as const;

const workspaces = [
  { label: "故事剧本", outcome: "写故事、确认分场", to: "/projects/$projectId/script" },
  { label: "角色素材", outcome: "准备一致的参考素材", to: "/projects/$projectId/assets" },
  { label: "分镜制作", outcome: "制作画面与视频", to: "/projects/$projectId/scenes" },
  { label: "审片确认", outcome: "检查并采用镜头", to: "/projects/$projectId/review" },
  { label: "剪辑成片", outcome: "保存时间线、导出作品", to: "/projects/$projectId/edit" },
] as const;

type ProductionFlowOverviewProps = {
  projectId: string;
  summary?: ProductionSummary;
  unavailable: boolean;
  shots: ReadonlyArray<{ id: string; scene_id: string }>;
};

export function ProductionFlowOverview({
  projectId,
  summary,
  unavailable,
  shots,
}: ProductionFlowOverviewProps) {
  return (
    <section className="production-flow" aria-label="制作流程" data-testid="production-flow">
      <header>
        <h2>创作流程</h2>
        <p>从故事到成片，按需往返。打开工作区不会自动生成或替换正式版本。</p>
      </header>
      <nav className="production-flow-workspaces" aria-label="创作流程">
        {workspaces.map((workspace, index) => (
          <Link key={workspace.to} to={workspace.to} params={{ projectId }}>
            <span className="production-journey-index" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <strong>{workspace.label}</strong>
            <small>{workspace.outcome}</small>
          </Link>
        ))}
      </nav>
      <Disclosure title="查看执行环节" description="提示词、画面、视频与合成的真实执行状态">
        <ol className="production-flow-stages">
          {stages.map((step, index) => {
            const facts = !unavailable
              ? summary?.stages.find((stage) => stage.node_key === step.key)
              : undefined;
            const counts = Object.entries(facts?.status_counts ?? {}).filter(
              ([, count]) => count > 0,
            );
            const failure = facts?.latest_failure;
            const failedShot = failure
              ? shots.find((shot) => shot.id === failure.shot_id)
              : undefined;
            const reason = failure?.error_code
              ? zhErrorParts(failure.error_code, failure.error_summary ?? "").label
              : "执行失败，请查看镜头记录。";
            return (
              <li key={step.key} data-testid={`production-stage-${step.key}`}>
                <header>
                  <span className="production-flow-index" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3>{zhNode(step.key)}</h3>
                </header>
                <div className="production-flow-status" aria-label={`${zhNode(step.key)}执行状态`}>
                  {!facts ? (
                    <span className="muted">
                      {unavailable ? "状态暂不可用" : summary ? "流程状态未返回" : "正在读取状态…"}
                    </span>
                  ) : counts.length === 0 ? (
                    <span className="muted">暂无执行记录</span>
                  ) : (
                    counts.map(([status, count]) => (
                      <Badge key={status} tone={status === "failed" ? "danger" : "default"}>
                        {nodeRunStatusLabel(status)} {count}
                      </Badge>
                    ))
                  )}
                </div>
                {failure && <p className="production-flow-blocker">阻塞原因：{reason}</p>}
                <div className="production-flow-actions">
                  <Link to={destinations[step.destination]} params={{ projectId }}>
                    {step.action}
                  </Link>
                  {failedShot && (
                    <Link
                      to="/projects/$projectId/scenes/$sceneId"
                      params={{ projectId, sceneId: failedShot.scene_id }}
                      search={{ shotId: failedShot.id, tool: undefined }}
                    >
                      查看失败镜头
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        <p className="production-flow-note">
          按镜头和环节统计主线的有效执行，版本尝试不计入这里。执行完成不等于人工通过或设为正式；
          配音、字幕与合成由剪辑页显式导出时准备，不会因打开本页而启动。
        </p>
      </Disclosure>
    </section>
  );
}
