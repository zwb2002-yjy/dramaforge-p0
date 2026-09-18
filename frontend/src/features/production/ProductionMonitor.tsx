import { useState } from "react";
import { Link } from "@tanstack/react-router";

import { Button, Disclosure } from "../../components/ui";
import type { ProjectSnapshot } from "../../lib/api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { zhNode } from "../../lib/zh";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import type { SceneSummary } from "../scenes/api";
import { latestEffectiveNodeRuns } from "./effectiveRuns";
import "./production-monitor.css";

type ProductionMonitorProps = {
  projectId: string;
  scenes: SceneSummary[];
  shots: Array<{
    id: string;
    scene_id: string;
    shot_number: number;
    sort_order: number;
    shot_type: string;
    status: string;
  }>;
  snapshot?: ProjectSnapshot;
  experimentCount?: number;
  scenesLoading?: boolean;
  scenesError?: boolean;
  shotsLoading?: boolean;
  shotsError?: boolean;
  snapshotError?: boolean;
  onRetry?: () => void;
};

const DONE = new Set(["completed", "cached", "completed_after_cancel", "approved"]);
const RUNNING = new Set(["queued", "running", "leased"]);

type SceneFilter = "all" | "unfinished" | "risk";

function sceneProgress(scene: SceneSummary) {
  const keyframes = Math.max(0, scene.shot_count - scene.formal_keyframe_count);
  const videos = Math.max(0, scene.shot_count - scene.formal_video_count);
  return {
    scene,
    keyframes,
    videos,
    unfinished: scene.shot_count === 0 || keyframes > 0 || videos > 0,
    description:
      scene.shot_count === 0
        ? "尚未添加镜头"
        : keyframes > 0
          ? `缺 ${keyframes} 个正式关键帧`
          : videos > 0
            ? `缺 ${videos} 个正式视频`
            : "正式产物已齐备",
  };
}

export function ProductionMonitor({
  projectId,
  scenes,
  shots,
  snapshot,
  experimentCount,
  scenesLoading = false,
  scenesError = false,
  shotsLoading = false,
  shotsError = false,
  snapshotError = false,
  onRetry,
}: ProductionMonitorProps) {
  const [filter, setFilter] = useState<SceneFilter>("all");
  const runs = latestEffectiveNodeRuns(snapshot?.node_runs ?? []);
  const completedRuns = runs.filter((run) => DONE.has(run.status)).length;
  const runningRuns = runs.filter((run) => RUNNING.has(run.status)).length;
  const failures = runs.filter((run) => run.status === "failed");
  const failedRuns = failures.length;
  const sceneFactsKnown = !scenesLoading && !scenesError;
  const runFactsKnown = Array.isArray(snapshot?.node_runs) && !snapshotError;
  const risks = scenes.reduce((sum, scene) => sum + (scene.risk_count ?? 0), 0);
  const formalKeyframes = scenes.reduce(
    (sum, scene) => sum + (scene.formal_keyframe_count ?? 0),
    0,
  );
  const formalVideos = scenes.reduce((sum, scene) => sum + (scene.formal_video_count ?? 0), 0);
  const progress = scenes.map(sceneProgress);
  const unfinished = progress.filter((item) => item.unfinished);
  const risky = progress.filter((item) => item.scene.risk_count > 0);
  const missingKeyframes = progress.reduce((sum, item) => sum + item.keyframes, 0);
  const missingVideos = progress.reduce((sum, item) => sum + item.videos, 0);
  const nextProgress =
    risky[0] ??
    progress.find((item) => item.keyframes > 0) ??
    progress.find((item) => item.videos > 0) ??
    unfinished[0];
  const nextScene = nextProgress?.scene;
  // The project shot list has no formal artifact pointers. Only a failed
  // shot's status is enough to target it; product gaps stay scene-scoped.
  const nextShot =
    !shotsLoading && !shotsError && risky.length > 0
      ? shots.find((shot) => shot.scene_id === nextScene?.id && shot.status === "failed")
      : undefined;
  const visibleScenes = filter === "risk" ? risky : filter === "unfinished" ? unfinished : progress;
  const nextStepTitle =
    risky.length > 0
      ? `有 ${risky.length} 个场景存在风险`
      : missingKeyframes > 0
        ? `还有 ${missingKeyframes} 个镜头未确认正式关键帧`
        : missingVideos > 0
          ? `还有 ${missingVideos} 个镜头未确认正式视频`
          : unfinished.length > 0
            ? "先为场景添加镜头"
            : "正式产物已齐备，可以进入剪辑";

  return (
    <section className="production-monitor" data-testid="production-monitor" aria-label="制作进度">
      {(scenesError || shotsError || snapshotError) && (
        <div className="flash err" role="alert">
          部分制作状态读取失败，相关统计暂不可用。已有场景列表可能不是最新状态。
          {onRetry && <Button onClick={onRetry}>重新读取状态</Button>}
        </div>
      )}
      {sceneFactsKnown && scenes.length > 0 && (
        <section
          className="monitor-next-step"
          data-testid="production-next-step"
          aria-label="下一步"
        >
          <div>
            <h2>{nextStepTitle}</h2>
          </div>
          <div className="monitor-next-actions">
            {nextScene ? (
              <Link
                className="df-btn primary"
                to="/projects/$projectId/scenes/$sceneId"
                params={{ projectId, sceneId: nextScene.id }}
                search={{ shotId: nextShot?.id, tool: undefined }}
              >
                {risky.length > 0 ? "检查风险场景" : "继续制作"}
              </Link>
            ) : (
              <Link
                className="df-btn primary"
                to="/projects/$projectId/edit"
                params={{ projectId }}
                search={{ sessionId: undefined }}
              >
                进入剪辑
              </Link>
            )}
          </div>
        </section>
      )}
      <div className="monitor-overview" data-testid="monitor-stats">
        <div>
          <span>镜头总数</span>
          <strong data-testid="stat-shots">
            {!shotsLoading && !shotsError ? shots.length : "—"}
          </strong>
        </div>
        <div>
          <span>正式关键帧</span>
          <strong data-testid="stat-formal-keyframes">
            {sceneFactsKnown ? formalKeyframes : "—"}
          </strong>
        </div>
        <div>
          <span>正式视频</span>
          <strong data-testid="stat-formal-videos">{sceneFactsKnown ? formalVideos : "—"}</strong>
        </div>
        <div>
          <span>场景风险</span>
          <strong
            className={sceneFactsKnown && risks ? "status-bad" : undefined}
            data-testid="stat-risks"
          >
            {sceneFactsKnown ? risks : "—"}
          </strong>
        </div>
      </div>
      <p className="monitor-execution-status">
        进行中 <strong data-testid="stat-running">{runFactsKnown ? runningRuns : "—"}</strong>
        <span>
          失败执行{" "}
          <strong
            className={runFactsKnown && failedRuns ? "status-bad" : undefined}
            data-testid="stat-failed"
          >
            {runFactsKnown ? failedRuns : "—"}
          </strong>
        </span>
      </p>

      {runFactsKnown && failedRuns > 0 && (
        <Disclosure title="查看失败执行" testId="production-failures-disclosure">
          <section className="monitor-failures" aria-label="失败执行详情">
            <p className="muted">
              失败执行与场景风险分别统计；实验失败也会计入执行记录，不代表正式产物缺失。此处不会自动重试。
            </p>
            <ul>
              {failures.map((run) => {
                const shot =
                  !shotsError && !shotsLoading
                    ? shots.find((item) => item.id === run.input_snapshot?.shot_id)
                    : undefined;
                const scene = sceneFactsKnown
                  ? scenes.find((item) => item.id === shot?.scene_id)
                  : undefined;
                const experiment =
                  run.input_snapshot?.experiment_id ||
                  run.input_snapshot?.execution_branch === "experiment";
                return (
                  <li key={run.id}>
                    <span>
                      {zhNode(run.node_key)} · {experiment ? "实验执行" : "执行"}
                      {nodeRunStatusLabel(run.status)}
                    </span>
                    {shot && scene ? (
                      <Link
                        to="/projects/$projectId/scenes/$sceneId"
                        params={{ projectId, sceneId: scene.id }}
                        search={{ shotId: shot.id, tool: undefined }}
                      >
                        查看镜头 {shot.shot_number} · {scene.location_name}
                      </Link>
                    ) : (
                      <span className="muted">暂无可定位的镜头</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </Disclosure>
      )}

      <section className="monitor-scenes" aria-labelledby="monitor-scenes-title">
        <header className="monitor-scene-heading">
          <h2 id="monitor-scenes-title">
            跨场景状态{" "}
            <span data-testid="stat-scenes">{sceneFactsKnown ? scenes.length : "—"}</span>
          </h2>
          <div className="monitor-filters" role="group" aria-label="场景状态筛选">
            <Button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
              全部场景
            </Button>
            <Button aria-pressed={filter === "unfinished"} onClick={() => setFilter("unfinished")}>
              未完成
            </Button>
            <Button aria-pressed={filter === "risk"} onClick={() => setFilter("risk")}>
              仅看风险
            </Button>
          </div>
        </header>
        {scenesLoading ? (
          <p role="status">正在读取场景制作进度…</p>
        ) : scenesError && scenes.length === 0 ? (
          <p>无法读取场景，请重试；这不代表项目中没有场景。</p>
        ) : scenes.length === 0 ? (
          <div className="monitor-empty">
            <p>尚无场景。请在场景工作区创建场景与镜头。</p>
            <Link to="/projects/$projectId/scenes" params={{ projectId }}>
              前往场景工作区
            </Link>
          </div>
        ) : visibleScenes.length === 0 ? (
          <p role="status">
            {scenesError
              ? "场景状态读取失败，暂时无法判断筛选结果。"
              : filter === "unfinished"
                ? "所有场景的正式产物均已齐备。"
                : "当前没有带风险的场景；未完成制作请切换到“未完成”。"}
          </p>
        ) : (
          <div
            className="monitor-table-scroll"
            role="region"
            aria-label="跨场景状态表格"
            tabIndex={0}
          >
            <table className="monitor-table" data-testid="monitor-scene-table">
              <thead>
                <tr>
                  <th>场景</th>
                  <th>镜头</th>
                  <th>正式关键帧 / 镜头</th>
                  <th>正式视频 / 镜头</th>
                  <th>风险</th>
                </tr>
              </thead>
              <tbody>
                {visibleScenes.map(({ scene, description, unfinished: isUnfinished }) => (
                  <tr key={scene.id} data-testid={`monitor-scene-${scene.id}`}>
                    <td>
                      <Link
                        className="qc-scene-enter monitor-scene-link"
                        to="/projects/$projectId/scenes/$sceneId"
                        params={{ projectId, sceneId: scene.id }}
                        search={{ shotId: undefined, tool: undefined }}
                      >
                        <strong>
                          {scene.episode_number}.{scene.scene_number} · {scene.location_name}
                        </strong>
                        <span>
                          {!sceneFactsKnown
                            ? "查看场景 →"
                            : scene.risk_count > 0
                              ? "检查场景 →"
                              : isUnfinished
                                ? "继续制作 →"
                                : "查看场景 →"}
                        </span>
                      </Link>
                      <small className="monitor-scene-description">
                        {timeOfDayLabel(scene.time_of_day)} ·{" "}
                        {sceneFactsKnown ? description : "状态待刷新"}
                      </small>
                    </td>
                    <td>{sceneFactsKnown ? scene.shot_count : "—"}</td>
                    <td>
                      {sceneFactsKnown
                        ? `${scene.formal_keyframe_count} / ${scene.shot_count}`
                        : "—"}
                    </td>
                    <td>
                      {sceneFactsKnown ? `${scene.formal_video_count} / ${scene.shot_count}` : "—"}
                    </td>
                    <td className={scene.risk_count ? "status-bad" : undefined}>
                      {sceneFactsKnown ? scene.risk_count : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Disclosure
        title="执行与资源统计"
        description="辅助统计，不代表正式成片进度"
        testId="production-statistics-disclosure"
      >
        <dl className="monitor-resource-stats">
          <div>
            <dt>已完成执行</dt>
            <dd data-testid="stat-completed">{runFactsKnown ? completedRuns : "—"}</dd>
          </div>
          <div>
            <dt>媒体结果</dt>
            <dd data-testid="stat-artifacts">
              {!snapshotError ? (snapshot?.artifacts?.length ?? "—") : "—"}
            </dd>
          </div>
          <div>
            <dt>实验</dt>
            <dd data-testid="stat-experiments">{experimentCount ?? "—"}</dd>
          </div>
        </dl>
      </Disclosure>
    </section>
  );
}
