import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import {
  artifactContentUrl,
  exportProject,
  fetchProjectShots,
  fetchSnapshot,
  grantExportDownload,
  importScript,
  produceGolden,
} from "../lib/api";
import { projectRoute } from "./projects.$projectId";

export const projectProductionRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/production",
  component: ProductionPage,
});

const NODES = [
  "prompt",
  "keyframe",
  "face_review",
  "video",
  "video_drift_review",
  "voice",
  "subtitle",
  "composite",
  "continuity_review",
] as const;

const GOLDEN_SCRIPT = `# Episode 1 — Neon Rain Lead

Lead: Lin Xia

## Scene 1 — Neon alley / night
Opening rain.

### Shot 1 — wide
Visual: neon rain street wide establishing, Lin Xia silhouette
Dialogue: (none)

### Shot 2 — medium
Visual: Lin Xia medium shot, wet jacket, neon rain street
Dialogue: The city never sleeps.

### Shot 3 — close
Visual: close-up Lin Xia eyes, rain drops
Dialogue: I know what I saw.

## Scene 2 — Underpass market / night

### Shot 4 — tracking
Visual: tracking Lin Xia through underpass market
Dialogue: Don't look back.

### Shot 5 — over_shoulder
Visual: over shoulder stranger watching Lin Xia
Dialogue: Found you.

### Shot 6 — insert
Visual: insert phone map pin neon rain street
Dialogue: (none)

### Shot 7 — medium
Visual: Lin Xia confronts stranger under tube light
Dialogue: Who sent you?

## Scene 3 — Rooftop / dawn

### Shot 8 — wide
Visual: rooftop wide dawn skyline face off
Dialogue: It ends here.

### Shot 9 — close
Visual: close Lin Xia face determined
Dialogue: Tell them I refuse.

### Shot 10 — wide
Visual: final wide neon rain street far below
Dialogue: (none)
`;

function statusClass(status: string): string {
  if (["completed", "cached", "completed_after_cancel"].includes(status)) return "done";
  if (status === "failed") return "fail";
  if (["queued", "running", "leased"].includes(status)) return "run";
  return "";
}

function ProductionPage() {
  const { projectId } = projectProductionRoute.useParams();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [lastExportId, setLastExportId] = useState<string | null>(null);
  const [downloadHint, setDownloadHint] = useState<string | null>(null);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);

  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 4000,
  });
  const shots = useQuery({
    queryKey: ["shots", projectId],
    queryFn: () => fetchProjectShots(projectId),
    enabled: projectId !== "demo",
  });

  const importMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从大厅创建真实项目");
      return importScript(projectId, "p0_10_shots.md", GOLDEN_SCRIPT, true);
    },
    onSuccess: async (r) => {
      setMsg(
        `已导入剧本：shots=${r.shot_count} scenes=${r.scene_count} lead=${r.lead_character ?? "—"}`,
      );
      await qc.invalidateQueries({ queryKey: ["shots", projectId] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const exportMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从大厅创建真实项目");
      return exportProject(projectId);
    },
    onSuccess: (r) => {
      setLastExportId(r.export_id);
      setMsg(
        `导出完成 timeline=${r.timeline_hash.slice(0, 12)}… items=${r.export_item_count} mp4=${r.mp4_error ? "失败" : "有"}`,
      );
      setDownloadHint(
        r.mp4_error
          ? `MP4：${r.mp4_error}（仍可下载 timeline/SRT）`
          : "可申请 timeline 下载授权",
      );
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const goldenMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从大厅创建真实项目");
      return produceGolden(projectId);
    },
    onSuccess: async (r) => {
      setMsg(
        `[夹具] 黄金批处理 shots=${r.shot_count} face=${r.face_checked} cont=${r.continuity_checked} — 非 §3.1 验收主证据`,
      );
      setLastExportId(r.export_id);
      await qc.invalidateQueries({ queryKey: ["shots", projectId] });
      await qc.invalidateQueries({ queryKey: ["snapshot", projectId] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const downloadMut = useMutation({
    mutationFn: async () => {
      if (!lastExportId) throw new Error("请先导出");
      return grantExportDownload(projectId, lastExportId, "timeline_json");
    },
    onSuccess: (g) => {
      const url = `/api/v1/projects/${projectId}/exports/${g.export_id}/download?token=${encodeURIComponent(g.token)}&object_role=timeline_json`;
      setDownloadHint(`授权下载：${g.object_key}`);
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const runs = snapshot.data?.node_runs ?? [];
  const arts = snapshot.data?.artifacts ?? [];
  const completedRuns = runs.filter((r) =>
    ["completed", "cached", "completed_after_cancel"].includes(r.status),
  ).length;
  const failedRuns = runs.filter((r) => r.status === "failed").length;
  const queuedRuns = runs.filter((r) => ["queued", "running"].includes(r.status)).length;

  const selectedShot =
    shots.data?.find((s) => s.id === selectedShotId) ?? shots.data?.[0] ?? null;

  // Aggregate node status: snapshot may only expose status + output_summary in P0 API
  const nodeRailClass = useMemo(() => {
    const map: Record<string, string> = {};
    for (const n of NODES) {
      const matching = runs.filter((r) => {
        const summary = r.output_summary ?? {};
        const key = String(
          summary.node_key ?? summary.node_type ?? summary.node_name ?? summary.kind ?? "",
        );
        return key === n || key.includes(n);
      });
      if (matching.some((r) => r.status === "failed")) map[n] = "fail";
      else if (matching.some((r) => ["queued", "running", "leased"].includes(r.status)))
        map[n] = "run";
      else if (
        matching.some((r) =>
          ["completed", "cached", "completed_after_cancel"].includes(r.status),
        )
      )
        map[n] = "done";
      else map[n] = "";
    }
    // Fallback: tint rail by completion ratio when runs lack node keys
    const hasKeys = Object.values(map).some(Boolean);
    if (!hasKeys && runs.length > 0) {
      const ratio = completedRuns / Math.max(runs.length, 1);
      NODES.forEach((n, i) => {
        if (i / NODES.length < ratio) map[n] = "done";
      });
      if (failedRuns) {
        map[NODES[Math.min(NODES.length - 1, Math.floor(ratio * NODES.length))]] = "fail";
      }
      if (queuedRuns) {
        map[NODES[Math.min(NODES.length - 1, Math.ceil(ratio * NODES.length))]] = "run";
      }
    }
    return map;
  }, [runs, completedRuns, failedRuns, queuedRuns]);

  const stageArt = arts[0];
  const stageUrl =
    stageArt && projectId !== "demo" ? artifactContentUrl(projectId, stageArt.id) : null;

  return (
    <div data-testid="production-mode">
      <div className="page-title-row">
        <div>
          <h2 style={{ margin: 0 }}>专业生产板</h2>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            分镜板 + shot-p0-v1 节点轨 · 与
            <Link to="/projects/$projectId/quick" params={{ projectId }}>
              {" "}
              快速创作
            </Link>{" "}
            同一 Project
          </p>
        </div>
      </div>

      <div className="callout warn">
        行业台共同点：分镜可视、节点状态清楚、结果可回看。
        <strong>禁止用「黄金夹具一键」冒充 §3.1 验收</strong>
        。正式路径：导入剧本 → 逐 Shot 生产/审核 → 导出可校验交付。
      </div>

      <div className="pipeline-rail" aria-label="shot-p0-v1">
        {NODES.map((n) => (
          <span key={n} className={`pipeline-node ${nodeRailClass[n] ?? ""}`}>
            {n}
          </span>
        ))}
      </div>

      <div className="toolbar">
        <button
          type="button"
          className="primary"
          data-testid="import-golden"
          onClick={() => importMut.mutate()}
          disabled={importMut.isPending}
        >
          {importMut.isPending ? "导入中…" : "① 导入 10 Shot 冻结剧本"}
        </button>
        <button
          type="button"
          className="accent"
          data-testid="export-project"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
        >
          {exportMut.isPending ? "导出中…" : "② 导出 timeline / SRT / 包"}
        </button>
        <button
          type="button"
          data-testid="download-export"
          onClick={() => downloadMut.mutate()}
          disabled={!lastExportId || downloadMut.isPending}
        >
          ③ 授权下载 timeline
        </button>
        <button
          type="button"
          className="ghost"
          data-testid="produce-golden"
          onClick={() => goldenMut.mutate()}
          disabled={goldenMut.isPending}
          title="仅开发夹具"
        >
          {goldenMut.isPending ? "夹具跑批中…" : "〔夹具〕假 Adapter 批处理（非验收）"}
        </button>
      </div>

      {msg && (
        <div className="flash ok" data-testid="production-msg">
          {msg}
        </div>
      )}
      {downloadHint && (
        <p className="muted" data-testid="download-hint">
          {downloadHint}
        </p>
      )}

      <div className="status-grid" data-testid="pipeline-stats">
        <div className="status-card">
          <span className="status-label">分镜 Shot</span>
          <strong data-testid="stat-shots">{shots.data?.length ?? 0}</strong>
        </div>
        <div className="status-card">
          <span className="status-label">NodeRun 完成</span>
          <strong className="status-ok" data-testid="stat-completed">
            {completedRuns}
          </strong>
        </div>
        <div className="status-card">
          <span className="status-label">进行中</span>
          <strong className="status-pending" data-testid="stat-queued">
            {queuedRuns}
          </strong>
        </div>
        <div className="status-card">
          <span className="status-label">失败</span>
          <strong className={failedRuns ? "status-bad" : ""} data-testid="stat-failed">
            {failedRuns}
          </strong>
        </div>
        <div className="status-card">
          <span className="status-label">Artifacts</span>
          <strong data-testid="stat-artifacts">{arts.length}</strong>
        </div>
      </div>

      {shots.data && shots.data.length > 0 && (
        <div className="timeline-strip" data-testid="shot-timeline">
          {shots.data.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`timeline-chip ${selectedShot?.id === s.id ? "selected" : ""}`}
              onClick={() => setSelectedShotId(s.id)}
            >
              <span className="num">S{s.shot_number || s.sort_order}</span>
              {s.shot_type}
            </button>
          ))}
        </div>
      )}

      <div className="studio">
        <div>
          <div className="panel">
            <h3>分镜板 Storyboard</h3>
            {shots.data && shots.data.length > 0 ? (
              <div className="shot-board" data-testid="shot-list">
                {shots.data.map((s, idx) => {
                  const art = arts[idx] ?? arts[0];
                  const thumbUrl =
                    art && projectId !== "demo"
                      ? artifactContentUrl(projectId, art.id)
                      : null;
                  return (
                    <article
                      key={s.id}
                      className={`shot-card ${selectedShot?.id === s.id ? "selected" : ""}`}
                      onClick={() => setSelectedShotId(s.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") setSelectedShotId(s.id);
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="thumb">
                        {thumbUrl ? <img src={thumbUrl} alt="" /> : null}
                        <div className="overlay">
                          #{s.sort_order} · {s.shot_type}
                        </div>
                      </div>
                      <div className="body">
                        <div className="title">Shot {s.shot_number || s.sort_order}</div>
                        <div className="meta">{s.visual_description.slice(0, 80)}</div>
                        {s.dialogue ? <div className="meta">「{s.dialogue}」</div> : null}
                        <div className="node-dots" title="shot-p0-v1">
                          {NODES.map((n) => (
                            <span
                              key={n}
                              className={`dot ${nodeRailClass[n] || ""}`}
                              title={n}
                            />
                          ))}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="muted">
                尚无分镜 — 点「导入 10 Shot 冻结剧本」，或从快速模式生成首帧后再回来。
              </p>
            )}
          </div>

          {selectedShot && (
            <div className="detail-panel" data-testid="shot-detail">
              <h3 style={{ margin: "0 0 0.5rem", color: "var(--text)" }}>
                镜头详情 · Shot {selectedShot.shot_number || selectedShot.sort_order}
              </h3>
              <div className="kv">
                <span>类型</span>
                <span>{selectedShot.shot_type}</span>
                <span>状态</span>
                <span>{selectedShot.status}</span>
                <span>画面</span>
                <span>{selectedShot.visual_description}</span>
                <span>对白</span>
                <span>{selectedShot.dialogue || "—"}</span>
              </div>
              <div className="pipeline-rail" style={{ marginTop: "0.75rem" }}>
                {NODES.map((n) => (
                  <span key={n} className={`pipeline-node ${nodeRailClass[n] ?? ""}`}>
                    {n}
                  </span>
                ))}
              </div>
              <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
                P0 局部重跑：修改字幕只失效 Subtitle→Composite 下游；Keyframe/Video/Voice
                保持缓存。逐 Shot 审核返工 API 继续加厚中。
              </p>
            </div>
          )}

          {snapshot.data && (
            <div className="panel" data-testid="production-snapshot">
              <h3>运行时 · {snapshot.data.name}</h3>
              <div className="split-2">
                <div>
                  <h4>最近 NodeRuns</h4>
                  <ul className="dense">
                    {snapshot.data.node_runs.slice(0, 20).map((r) => (
                      <li key={r.id}>
                        <code>{r.id.slice(0, 8)}</code>
                        <strong className={statusClass(r.status) === "done" ? "status-ok" : statusClass(r.status) === "fail" ? "status-bad" : "status-pending"}>
                          {r.status}
                        </strong>
                      </li>
                    ))}
                    {snapshot.data.node_runs.length === 0 && (
                      <li className="muted">尚无 NodeRun</li>
                    )}
                  </ul>
                </div>
                <div>
                  <h4>Artifacts</h4>
                  <ul className="dense">
                    {snapshot.data.artifacts.slice(0, 16).map((a) => (
                      <li key={a.id}>
                        <a
                          href={artifactContentUrl(projectId, a.id)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {a.object_key.split("/").slice(-2).join("/")}
                        </a>
                        <span className="muted">{a.byte_size}B</span>
                      </li>
                    ))}
                    {snapshot.data.artifacts.length === 0 && (
                      <li className="muted">尚无产物 · 先快速首帧或正式生产</li>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>

        <aside className="studio-stage">
          <div className="panel" style={{ padding: "0.85rem" }}>
            <h3 style={{ marginBottom: "0.65rem" }}>预览 / 交付</h3>
            <div className="stage-phone">
              {stageUrl ? (
                <>
                  <span className="stage-badge">最新 Artifact</span>
                  <img src={stageUrl} alt="preview" />
                </>
              ) : (
                <div className="stage-empty">
                  分镜板产物预览
                  <br />
                  导入剧本并生产后
                  <br />
                  在此回看画面
                </div>
              )}
            </div>
            <div className="stage-meta">
              {stageArt ? (
                <>
                  <div>
                    <code>{stageArt.object_key.split("/").slice(-1)[0]}</code>
                  </div>
                  <div>{stageArt.byte_size}B</div>
                </>
              ) : (
                "等待产物…"
              )}
            </div>
            <div className="ref-strip" style={{ marginTop: "0.65rem" }}>
              {arts.slice(0, 8).map((a) => (
                <a
                  key={a.id}
                  className="ref-chip"
                  href={artifactContentUrl(projectId, a.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img src={artifactContentUrl(projectId, a.id)} alt="" />
                </a>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
