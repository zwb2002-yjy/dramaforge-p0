import { useQuery } from "@tanstack/react-query";

import { Button } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import { shotStatusLabel } from "../../lib/shotLabels";
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
  NONE: "未使用模板",
};

function productionStateLabel(state: string): string {
  return (
    {
      draft: "草稿",
      ready: "就绪",
      producing: "制作中",
      queued: "排队中",
      running: "生成中",
      failed: "生成失败",
      completed: "已完成",
      review: "待审",
      complete: "完成",
      blocked: "阻塞",
    }[state] ?? "待确认"
  );
}

function productionStateTone(state: string): string {
  return (
    {
      draft: "idle",
      ready: "done",
      producing: "running",
      queued: "idle",
      running: "running",
      failed: "attention",
      completed: "done",
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
        <span className="workflow-shot-template">创作：{shotStatusLabel(shot.status)}</span>
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
        {scene.episode_number}.{scene.scene_number} · {timeOfDayLabel(scene.time_of_day)} · 正式{" "}
        {status.formal_shots}/{status.total_shots}
      </p>
      <ul className="workflow-shot-list">
        {(scene.shots ?? []).map((shot) => (
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
    enabled: Boolean(projectId),
  });
  const data = overview.data as WorkflowOverviewRead | undefined;
  const episodes = data?.episodes ?? [];
  const scenes = data?.scenes ?? [];

  return (
    <div className="workflow-navigator" data-testid="workflow-navigator">
      <div className="workflow-navigator-header">
        <span>生成任务</span>
        <small>
          {data
            ? `${data.total_shots} 镜头 · 正式 ${data.formal_shots} · 阻塞 ${data.blocked_scenes} 场景`
            : "…"}
        </small>
      </div>
      {data && <p className="muted">场景完成按正式视频统计；镜头创作状态不代表有任务正在运行。</p>}
      {overview.isPending && <p role="status">正在读取生成任务…</p>}
      {overview.isError && (
        <div className="flash err" role="alert">
          生成任务读取失败，不能据此判断项目没有任务。
          <Button onClick={() => void overview.refetch()}>重新读取生成任务</Button>
        </div>
      )}
      <div className="workflow-episode-list">
        {overview.isSuccess && episodes.length === 0 && (
          <p className="muted">还没有生成任务。先到剧本页准备故事，再选择镜头生成画面。</p>
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
                第 {episode.episode_number} 集 ·{" "}
                {episode.title || `第 ${episode.episode_number} 集`}
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
    </div>
  );
}
