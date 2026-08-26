/**
 * Phase 10 cross-scene Production Monitor (plan 03 §89).
 *
 * The production page is a monitor: cross-scene summary + per-scene status,
 * while the actual work happens in the Scene Workbench (/scenes/$sceneId) and
 * the ProfessionalWorkbench. Legacy Script Import / budget main panel / old
 * big storyboard workspace were removed from this surface.
 */
import type { ProjectSnapshot } from "../../lib/api";
import type { SceneSummary } from "../workbench/api";

type ProductionMonitorProps = {
  projectId: string;
  scenes: SceneSummary[];
  shots: Array<{ id: string; scene_id: string; shot_number: number; sort_order: number; shot_type: string; status: string }>;
  snapshot?: ProjectSnapshot;
  experimentCount: number;
};

const DONE = new Set(["completed", "cached", "completed_after_cancel", "approved"]);
const RUNNING = new Set(["queued", "running", "leased"]);

export function ProductionMonitor({
  projectId,
  scenes,
  shots,
  snapshot,
  experimentCount,
}: ProductionMonitorProps) {
  const runs = snapshot?.node_runs ?? [];
  const completedRuns = runs.filter((r) => DONE.has(r.status)).length;
  const runningRuns = runs.filter((r) => RUNNING.has(r.status)).length;
  const failedRuns = runs.filter((r) => r.status === "failed").length;
  const artifacts = snapshot?.artifacts ?? [];
  const formalKeyframes = scenes.reduce((sum, s) => sum + (s.formal_keyframe_count || 0), 0);
  const formalVideos = scenes.reduce((sum, s) => sum + (s.formal_video_count || 0), 0);
  const risks = scenes.reduce((sum, s) => sum + (s.risk_count || 0), 0);
  const sceneCount = scenes.length;

  return (
    <section className="production-monitor" data-testid="production-monitor">
      <div className="status-grid" data-testid="monitor-stats">
        <div className="status-card">
          <span className="status-label">场景</span>
          <strong data-testid="stat-scenes">{sceneCount}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">分镜 Shot</span>
          <strong data-testid="stat-shots">{shots.length}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">正式关键帧</span>
          <strong data-testid="stat-formal-keyframes">{formalKeyframes}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">正式视频</span>
          <strong data-testid="stat-formal-videos">{formalVideos}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">NodeRun 完成</span>
          <strong className="status-ok" data-testid="stat-completed">{completedRuns}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">进行中</span>
          <strong className="status-pending" data-testid="stat-running">{runningRuns}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">失败 / 风险</span>
          <strong className={failedRuns + risks ? "status-bad" : ""} data-testid="stat-failed">
            {failedRuns + risks}
          </strong>
        </div>
        <div className="status-card">
          <span className="status-label">Artifacts</span>
          <strong data-testid="stat-artifacts">{artifacts.length}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">实验</span>
          <strong data-testid="stat-experiments">{experimentCount}</strong>
        </div>
      </div>

      <div className="panel">
        <h3>跨场景状态</h3>
        {scenes.length === 0 ? (
          <p className="muted">尚无场景。请在场景工作区创建场景与镜头。</p>
        ) : (
          <table className="monitor-table" data-testid="monitor-scene-table">
            <thead>
              <tr>
                <th>场景</th>
                <th>Shot</th>
                <th>正式关键帧</th>
                <th>正式视频</th>
                <th>风险</th>
                <th>进入</th>
              </tr>
            </thead>
            <tbody>
              {scenes.map((scene) => (
                <tr key={scene.id} data-testid={`monitor-scene-${scene.id}`}>
                  <td>
                    <strong>
                      {scene.episode_number}.{scene.scene_number} · {scene.location_name}
                    </strong>
                    <span className="muted">{scene.time_of_day}</span>
                  </td>
                  <td>{scene.shot_count}</td>
                  <td>{scene.formal_keyframe_count ?? 0}</td>
                  <td>{scene.formal_video_count ?? 0}</td>
                  <td className={scene.risk_count ? "status-bad" : undefined}>{scene.risk_count ?? 0}</td>
                  <td>
                    <a className="df-btn ghost" href={`/projects/${projectId}/scenes/${scene.id}`}>
                      场景工作区
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {shots.length > 0 && (
        <div className="timeline-strip" data-testid="shot-timeline">
          {shots.map((shot) => (
            <a
              key={shot.id}
              className={`timeline-chip ${shot.status === "failed" ? "fail" : ""}`}
              href={`/projects/${projectId}/scenes/${shot.scene_id}`}
            >
              <span className="num">S{shot.shot_number || shot.sort_order}</span>
              {shot.shot_type}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
