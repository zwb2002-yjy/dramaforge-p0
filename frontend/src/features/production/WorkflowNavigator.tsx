import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../../lib/queryKeys";
import {
  fetchWorkflowOverview,
  type SceneWorkflowViewRead,
  type ShotWorkflowStateRead,
  type WorkflowOverviewRead,
} from "./workflow-api";

const CAPABILITY_LABEL: Record<string, string> = {
  EXACT: "可双人",
  APPROXIMATE: "近似双人",
  UNSUPPORTED: "不可双人",
};

const CAPABILITY_TONE: Record<string, string> = {
  EXACT: "done",
  APPROXIMATE: "running",
  UNSUPPORTED: "attention",
};

const RESOLUTION_LABEL: Record<string, string> = {
  RESOLVED: "已冻结",
  UNAVAILABLE: "模板失效",
  NONE: "未选模板",
};

function productionStateLabel(state: string): string {
  return (
    {
      draft: "草稿",
      ready: "就绪",
      producing: "制作中",
      review: "待审",
      complete: "完成",
      blocked: "阻塞",
    }[state] ?? state
  );
}

function productionStateTone(state: string): string {
  return (
    {
      draft: "idle",
      ready: "done",
      producing: "running",
      review: "running",
      complete: "done",
      blocked: "attention",
    }[state] ?? "idle"
  );
}

function ShotWorkflowRow({ shot }: { shot: ShotWorkflowStateRead }) {
  const cap = shot.capability_assessment;
  return (
    <li className="workflow-shot-row" data-testid={`workflow-shot-${shot.shot_number}`}>
      <span className="shot-index">{String(shot.shot_number).padStart(2, "0")}</span>
      <span className="workflow-shot-main">
        <span className="workflow-shot-template">
          {shot.workflow_template_key ?? shot.status ?? "未选模板"}
        </span>
        <small>
          {RESOLUTION_LABEL[shot.template_resolution_status] ?? shot.template_resolution_status}
          {shot.template_version ? ` · v${shot.template_version}` : ""}
        </small>
      </span>
      <span
        className={`workflow-shot-status status-chip ${cap ? (CAPABILITY_TONE[cap.status] ?? "idle") : "idle"}`}
      >
        {cap
          ? (CAPABILITY_LABEL[cap.status] ?? cap.status)
          : shot.template_resolution_status === "RESOLVED"
            ? "已定"
            : "—"}
      </span>
    </li>
  );
}

function SceneWorkflowGroup({ scene }: { scene: SceneWorkflowViewRead }) {
  const status = scene.production_status;
  return (
    <section className="scene-group" data-testid={`workflow-scene-${scene.scene_number}`}>
      <div className="scene-group-title">
        <span>{scene.location_name || `场景 ${scene.scene_number}`}</span>
        <span className={`status-chip ${productionStateTone(status.state)}`}>
          {productionStateLabel(status.state)}
        </span>
      </div>
      <p className="workflow-scene-synopsis muted">
        {scene.episode_number}.{scene.scene_number} · {scene.time_of_day} · 正式{" "}
        {status.formal_shots}/{status.total_shots}
      </p>
      <ul className="workflow-shot-list">
        {scene.shots.map((shot) => (
          <ShotWorkflowRow key={shot.shot_id} shot={shot} />
        ))}
      </ul>
    </section>
  );
}

export type WorkflowNavigatorProps = {
  projectId: string;
};

/** Episode → Scene → Shot wire-visible workflow navigator (WF13-02).
 *
 * Pure read aggregation over the existing execution truth: shows scene
 * production status, per-shot frozen workflow template identity, and the
 * multi-subject capability assessment (EXACT / APPROXIMATE / UNSUPPORTED).
 * No provider call and no mutation is performed here.
 */
export function WorkflowNavigator({ projectId }: WorkflowNavigatorProps) {
  const overview = useQuery({
    queryKey: queryKeys.production.workflowOverview(projectId),
    queryFn: () => fetchWorkflowOverview(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const data = overview.data as WorkflowOverviewRead | undefined;
  const episodes = data?.episodes ?? [];
  const scenes = data?.scenes ?? [];

  return (
    <div className="workflow-navigator" data-testid="workflow-navigator">
      <div className="workflow-navigator-header">
        <span>Workflow Navigator</span>
        <small>
          {data
            ? `${data.total_shots} 镜头 · 正式 ${data.formal_shots} · 阻塞 ${data.blocked_scenes} 场景`
            : "…"}
        </small>
      </div>
      <div className="workflow-episode-list">
        {episodes.length === 0 && (
          <p className="muted">暂无剧本。可在场景工作区导入剧本后回看镜头工作流状态。</p>
        )}
        {episodes.map((episode) => (
          <section
            key={episode.episode_id}
            className="workflow-episode"
            data-testid={`workflow-episode-${episode.episode_number}`}
          >
            <header
              className="workflow-episode-header"
              data-testid={`workflow-episode-${episode.episode_number}-title`}
            >
              <strong>
                EP{episode.episode_number} · {episode.title || `第 ${episode.episode_number} 集`}
              </strong>
              <small>
                {episode.scene_count} 场景 · {episode.total_shots} 镜头
              </small>
            </header>
            <div className="workflow-scene-groups">
              {scenes
                .filter((scene) => scene.episode_id === episode.episode_id)
                .map((scene) => (
                  <SceneWorkflowGroup key={scene.scene_id} scene={scene} />
                ))}
            </div>
          </section>
        ))}
      </div>
      <div className="workflow-nav-footer">
        <small>未声明的多角色镜头不会静默降级；UNSUPPORTED 时 Provider POST=0</small>
      </div>
    </div>
  );
}
