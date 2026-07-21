import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { useState } from "react";

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
];

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

function ProductionPage() {
  const { projectId } = projectProductionRoute.useParams();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [lastExportId, setLastExportId] = useState<string | null>(null);
  const [downloadHint, setDownloadHint] = useState<string | null>(null);

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
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      return importScript(projectId, "p0_10_shots.md", GOLDEN_SCRIPT, true);
    },
    onSuccess: async (r) => {
      setMsg(
        `imported shots=${r.shot_count} scenes=${r.scene_count} lead=${r.lead_character} char=${r.character_id ?? "—"}`,
      );
      await qc.invalidateQueries({ queryKey: ["shots", projectId] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const exportMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      return exportProject(projectId);
    },
    onSuccess: (r) => {
      setLastExportId(r.export_id);
      setMsg(
        `export timeline=${r.timeline_hash.slice(0, 12)}… srt=${r.srt_hash.slice(0, 12)}… items=${r.export_item_count} mp4_err=${r.mp4_error ?? "none"}`,
      );
      setDownloadHint(
        r.mp4_error
          ? `MP4 未生成（${r.mp4_error}）。仍可下载 timeline/SRT 授权包。`
          : "导出完成，可申请 timeline 下载授权。",
      );
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const downloadMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      if (!lastExportId) throw new Error("请先执行导出");
      return grantExportDownload(projectId, lastExportId, "timeline_json");
    },
    onSuccess: (g) => {
      const url = `/api/v1/projects/${projectId}/exports/${g.export_id}/download?token=${encodeURIComponent(g.token)}&object_key=${encodeURIComponent(g.object_key)}`;
      setDownloadHint(`下载授权已签发：${g.object_key}（expires ${g.expires_at}）`);
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const goldenMut = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      return produceGolden(projectId);
    },
    onSuccess: async (r) => {
      setMsg(
        `golden shots=${r.shot_count} face=${r.face_checked} cont=${r.continuity_checked} export=${r.export_id.slice(0, 8)}…`,
      );
      await qc.invalidateQueries({ queryKey: ["shots", projectId] });
      await qc.invalidateQueries({ queryKey: ["snapshot", projectId] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const runs = snapshot.data?.node_runs ?? [];
  const arts = snapshot.data?.artifacts ?? [];
  const completedRuns = runs.filter((r) =>
    ["completed", "cached", "completed_after_cancel"].includes(r.status),
  ).length;
  const failedRuns = runs.filter((r) => r.status === "failed").length;
  const queuedRuns = runs.filter((r) =>
    ["queued", "running"].includes(r.status),
  ).length;

  return (
    <div data-testid="production-mode">
      <h2>专业生产 · 短剧流水线</h2>
      <p>
        同一 Project：<code>{projectId}</code>
        （与快速模式共享资产 / Run / 成本）
      </p>
      <p className="muted">
        标准路径：先在「快速模式」完成 Brief/Plan/首帧，或在此导入剧本 → 生产 → 导出。
        「黄金路径」仅用于开发夹具批处理，<strong>不是 P0 验收主路径</strong>（假 Adapter 仅测试）。
      </p>
      <div className="node-strip" aria-label="shot-p0-v1 nodes">
        {NODES.map((n) => (
          <span key={n} className="node-chip">
            {n}
          </span>
        ))}
      </div>
      <div className="toolbar">
        <button
          type="button"
          data-testid="import-golden"
          onClick={() => importMut.mutate()}
          disabled={importMut.isPending || goldenMut.isPending}
        >
          {importMut.isPending ? "导入中…" : "① 导入黄金样本剧本 (10 Shot)"}
        </button>
        <button
          type="button"
          data-testid="produce-golden"
          onClick={() => goldenMut.mutate()}
          disabled={goldenMut.isPending}
        >
          {goldenMut.isPending
            ? "夹具批处理中…"
            : "② [开发夹具] 黄金路径 10 Shot（测试/假适配器，非产品主路径）"}
        </button>
        <button
          type="button"
          data-testid="export-project"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending || goldenMut.isPending}
        >
          {exportMut.isPending ? "导出中…" : "③ 导出 timeline/SRT/素材包"}
        </button>
        <button
          type="button"
          data-testid="download-export"
          onClick={() => downloadMut.mutate()}
          disabled={!lastExportId || downloadMut.isPending}
        >
          {downloadMut.isPending ? "签发中…" : "④ 授权下载 timeline"}
        </button>
      </div>
      {msg && (
        <p data-testid="production-msg" className="status-ok">
          {msg}
        </p>
      )}
      {downloadHint && (
        <p data-testid="download-hint" className="muted">
          {downloadHint}
        </p>
      )}
      {(importMut.isPending || goldenMut.isPending || exportMut.isPending) && (
        <p data-testid="production-busy" className="status-pending">
          任务执行中，请稍候…完成后下方 Shot / NodeRun 会自动刷新。
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
        <div data-testid="shot-list">
          <h3>分镜列表 Shots ({shots.data.length}) · 剧本生产线</h3>
          <ol>
            {shots.data.map((s) => (
              <li key={s.id}>
                <strong>
                  #{s.sort_order} [{s.shot_type}]
                </strong>{" "}
                {s.visual_description.slice(0, 100)}
                {s.dialogue ? ` · 对白「${s.dialogue}」` : ""}
                <span className="muted"> · {s.status}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {snapshot.data && (
        <div data-testid="production-snapshot">
          <h3>生产状态 NodeRuns / Artifacts（与快速模式同源）</h3>
          <p>
            project: <strong>{snapshot.data.name}</strong>
          </p>
          <h4>最近 NodeRuns</h4>
          <ul>
            {snapshot.data.node_runs.slice(0, 30).map((r) => (
              <li key={r.id}>
                <code>{r.id.slice(0, 8)}</code>…{" "}
                <strong
                  className={
                    r.status === "completed" || r.status === "cached"
                      ? "status-ok"
                      : r.status === "failed"
                        ? "status-bad"
                        : "status-pending"
                  }
                >
                  {r.status}
                </strong>
                {r.result_artifact_id
                  ? ` · art=${r.result_artifact_id.slice(0, 8)}…`
                  : " · no artifact"}
                {r.output_summary && Object.keys(r.output_summary).length > 0 && (
                  <span className="muted">
                    {" "}
                    ·{" "}
                    {String(
                      (r.output_summary as { node_type?: string; face_review?: string })
                        .node_type ??
                        (r.output_summary as { face_review?: string }).face_review ??
                        "",
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <h4>Artifacts（素材产物）</h4>
          <ul>
            {snapshot.data.artifacts.slice(0, 30).map((a) => (
              <li key={a.id}>
                <a href={artifactContentUrl(projectId, a.id)} target="_blank" rel="noreferrer">
                  {a.object_key}
                </a>{" "}
                · {a.byte_size}B · {a.content_hash.slice(0, 12)}…
              </li>
            ))}
          </ul>
          {snapshot.data.artifacts.length === 0 && (
            <p className="muted">尚无产物 — 请先点「黄金路径」或从快速模式生成首帧。</p>
          )}
        </div>
      )}
    </div>
  );
}
