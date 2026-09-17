import { useState } from "react";

import { Button, Disclosure } from "../../components/ui";
import type { ProjectSnapshot } from "../../lib/api";
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
  const [riskOnly, setRiskOnly] = useState(false);
  const runs = latestEffectiveNodeRuns(snapshot?.node_runs ?? []);
  const completedRuns = runs.filter((run) => DONE.has(run.status)).length;
  const runningRuns = runs.filter((run) => RUNNING.has(run.status)).length;
  const failedRuns = runs.filter((run) => run.status === "failed").length;
  const sceneFactsKnown = !scenesLoading && !scenesError;
  const runFactsKnown = Array.isArray(snapshot?.node_runs) && !snapshotError;
  const risks = scenes.reduce((sum, scene) => sum + (scene.risk_count ?? 0), 0);
  const formalKeyframes = scenes.reduce(
    (sum, scene) => sum + (scene.formal_keyframe_count ?? 0),
    0,
  );
  const formalVideos = scenes.reduce((sum, scene) => sum + (scene.formal_video_count ?? 0), 0);
  const visibleScenes = riskOnly ? scenes.filter((scene) => (scene.risk_count ?? 0) > 0) : scenes;

  return (
    <section className="production-monitor" data-testid="production-monitor" aria-label="制作进度">
      {(scenesError || shotsError || snapshotError) && (
        <div className="flash err" role="alert">
          部分制作状态读取失败，相关统计暂不可用。已有场景列表可能不是最新状态。
          {onRetry && <Button onClick={onRetry}>重新读取状态</Button>}
        </div>
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
        <span className="muted">执行完成不等于已确认正式结果</span>
      </p>

      <section className="monitor-scenes" aria-labelledby="monitor-scenes-title">
        <header className="monitor-scene-heading">
          <h2 id="monitor-scenes-title">
            跨场景状态{" "}
            <span data-testid="stat-scenes">{sceneFactsKnown ? scenes.length : "—"}</span>
          </h2>
          <div className="monitor-filters" role="group" aria-label="场景状态筛选">
            <Button aria-pressed={!riskOnly} onClick={() => setRiskOnly(false)}>
              全部场景
            </Button>
            <Button aria-pressed={riskOnly} onClick={() => setRiskOnly(true)}>
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
            <a href={`/projects/${projectId}/scenes`}>前往场景工作区</a>
          </div>
        ) : visibleScenes.length === 0 ? (
          <p role="status">当前没有带风险的场景。失败执行请在镜头工作流中查看。</p>
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
                  <th>正式关键帧</th>
                  <th>正式视频</th>
                  <th>风险</th>
                </tr>
              </thead>
              <tbody>
                {visibleScenes.map((scene) => (
                  <tr key={scene.id} data-testid={`monitor-scene-${scene.id}`}>
                    <td>
                      <a
                        className="qc-scene-enter"
                        href={`/projects/${projectId}/scenes/${scene.id}`}
                      >
                        <strong>
                          {scene.episode_number}.{scene.scene_number} · {scene.location_name}
                        </strong>
                      </a>
                      <span className="muted">{timeOfDayLabel(scene.time_of_day)}</span>
                    </td>
                    <td>{scene.shot_count}</td>
                    <td>{scene.formal_keyframe_count ?? 0}</td>
                    <td>{scene.formal_video_count ?? 0}</td>
                    <td className={scene.risk_count ? "status-bad" : undefined}>
                      {scene.risk_count ?? 0}
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
