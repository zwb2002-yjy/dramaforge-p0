import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { ArtifactStage } from "../lib/artifactStage";
import {
  approveShot,
  artifactContentUrl,
  exportDownloadUrl,
  exportProject,
  fetchProjectShots,
  fetchShotStatus,
  fetchSnapshot,
  grantExportDownload,
  importScript,
  lockShot,
  produceGolden,
  rejectShot,
  rerunShot,
  startShot,
} from "../lib/api";
import type { ProjectSnapshot } from "../lib/api";
import {
  imageArtifacts,
  latestImageArtifact,
  shotKeyframeArtifact,
} from "../lib/projectMedia";
import { projectRoute } from "./projects.$projectId";
import { zhErrorCode, zhErrorSummary, zhNode, zhStatus } from "../lib/zh";

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

const NODE_DEPENDENCIES: Record<string, string[]> = {
  prompt: [],
  keyframe: ["prompt"],
  face_review: ["keyframe"],
  video: ["face_review"],
  video_drift_review: ["video"],
  voice: [],
  subtitle: [],
  composite: ["video_drift_review", "voice", "subtitle"],
  continuity_review: ["composite"],
};

const RETRY_SUGGESTIONS: Record<string, string> = {
  PROVIDER_NOT_CONFIGURED: "配置 Provider 或使用受审计手工媒体上传",
  MODEL_BINDING_NOT_VERIFIED: "完成四层模型证据后再绑定项目",
  CANONICAL_REFERENCE_REQUIRED: "先注册并锁定主角 Canonical Reference",
  UPSTREAM_RUN_MISSING: "检查同 Shot、同版本、同 attempt 的上游 Run",
  UPSTREAM_TERMINAL_FAILURE: "先处理首个上游失败节点，再局部重跑",
  UPSTREAM_ARTIFACT_MISSING: "核对上游 Run、Artifact 和对象存储 hash",
  PROVIDER_TASK_PENDING: "保留远端任务 ID，恢复 Worker 后继续 Poll",
  PROVIDER_SUBMISSION_UNKNOWN: "人工核对 Provider 任务和账单后再创建新 attempt",
  PROVIDER_CREATE_FAILED: "检查 Provider 错误和请求合同，只重试当前节点",
  PROVIDER_TASK_FAILED: "检查远端任务错误，再重跑当前节点及下游",
  PROVIDER_MEDIA_DOWNLOAD_FAILED: "续查同一任务或结果 URL，修复后再入库",
  FACE_BELOW_THRESHOLD: "保持 0.60 阈值，从 Keyframe 返工",
  FACE_PROBE_UNAVAILABLE: "检查两源 Artifact 和人脸检测后人工复核",
  VIDEO_DRIFT_BLOCKED: "查看抽样时间点，从 Video 及下游重跑",
  blocked_budget: "调整项目预算后重试原节点",
  QUEUE_UNAVAILABLE: "恢复 Redis/Worker 后重新 enqueue",
};

const SCRIPT_TEMPLATE = `# Episode 1 - Untitled

Lead: Lead Name

## Scene 1 - Location / day
Story beat.

### Shot 1 - medium
Visual: describe the subject, action, composition, and story beat
Dialogue:
Camera: static
`;

function statusClass(status: string): string {
  if (["completed", "cached", "completed_after_cancel"].includes(status)) return "done";
  if (status === "failed") return "fail";
  if (["queued", "running", "leased"].includes(status)) return "run";
  return "";
}

function nodeRailForRuns(runs: ProjectSnapshot["node_runs"]): Record<string, string> {
  const map: Record<string, string> = {};
  const completed = runs.filter((run) =>
    ["completed", "cached", "completed_after_cancel"].includes(run.status),
  ).length;
  for (const node of NODES) {
    const matching = runs.filter((run) => {
      const input = run.input_snapshot ?? {};
      const summary = run.output_summary ?? {};
      const key = String(
        run.node_key ??
          input.node_key ??
          summary.node_key ??
          summary.node_type ??
          summary.node_name ??
          summary.kind ??
          "",
      );
      return key === node || key.includes(node);
    });
    if (matching.some((run) => run.status === "failed")) map[node] = "fail";
    else if (matching.some((run) => ["queued", "running", "leased"].includes(run.status)))
      map[node] = "run";
    else if (
      matching.some((run) =>
        ["completed", "cached", "completed_after_cancel"].includes(run.status),
      )
    )
      map[node] = "done";
    else map[node] = "";
  }

  if (!Object.values(map).some(Boolean) && runs.length > 0) {
    const ratio = completed / runs.length;
    NODES.forEach((node, index) => {
      if (index / NODES.length < ratio) map[node] = "done";
    });
    if (runs.some((run) => run.status === "failed")) {
      map[NODES[Math.min(NODES.length - 1, Math.floor(ratio * NODES.length))]] = "fail";
    }
    if (runs.some((run) => ["queued", "running", "leased"].includes(run.status))) {
      map[NODES[Math.min(NODES.length - 1, Math.ceil(ratio * NODES.length))]] = "run";
    }
  }
  return map;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function nodeStatusLabel(run: ProjectSnapshot["node_runs"][number] | undefined, node: string): string {
  if (!run) {
    const dependencies = NODE_DEPENDENCIES[node] ?? [];
    return dependencies.length ? "等待上游" : "未开始";
  }
  if (run.status === "failed") return zhErrorCode(run.error_code) || "Provider 失败";
  if (run.status === "blocked_budget") return "预算阻断";
  if (run.status === "queued" || run.status === "running") {
    if (run.output_summary?.status === "provider_pending") return "Provider 处理中";
    return run.status === "queued" ? "排队中" : "运行中";
  }
  if (run.status === "completed_after_cancel") return "取消后完成";
  if (run.status === "completed" || run.status === "cached") {
    const reviewStatus = String(run.output_summary?.status ?? "");
    if (reviewStatus === "needs_human") return "需人工复核";
    if (reviewStatus === "blocked") return "质量阻断";
    return "已完成";
  }
  return zhStatus(run.status);
}

function retrySuggestion(code: string | null): string {
  if (!code) return "—";
  return RETRY_SUGGESTIONS[code] ?? "查看错误摘要后局部重跑失败节点";
}

function ProductionPage() {
  const { projectId } = projectProductionRoute.useParams();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [lastExportId, setLastExportId] = useState<string | null>(null);
  const [downloadHint, setDownloadHint] = useState<string | null>(null);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [opBusy, setOpBusy] = useState(false);
  const [scriptFilename, setScriptFilename] = useState("script.md");
  const [scriptText, setScriptText] = useState(SCRIPT_TEMPLATE);

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
      const text = scriptText.trim();
      if (!text) throw new Error("请输入或上传剧本文本");
      return importScript(projectId, scriptFilename.trim() || "script.md", text, true);
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
      const url = exportDownloadUrl(projectId, g.export_id, g.token, "timeline_json");
      setDownloadHint(`授权下载：${g.object_key}`);
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const runs = useMemo(() => snapshot.data?.node_runs ?? [], [snapshot.data?.node_runs]);
  const arts = useMemo(() => snapshot.data?.artifacts ?? [], [snapshot.data?.artifacts]);
  const previewArts = imageArtifacts(arts);
  const completedRuns = runs.filter((r) =>
    ["completed", "cached", "completed_after_cancel"].includes(r.status),
  ).length;
  const failedRuns = runs.filter((r) => r.status === "failed").length;
  const queuedRuns = runs.filter((r) => ["queued", "running"].includes(r.status)).length;

  const selectedShot =
    shots.data?.find((s) => s.id === selectedShotId) ?? shots.data?.[0] ?? null;

  const selectedShotRuns = useMemo(
    () =>
      selectedShot
        ? runs.filter((run) => String(run.input_snapshot?.shot_id ?? "") === selectedShot.id)
        : [],
    [runs, selectedShot],
  );
  const selectedShotByNode = useMemo(() => {
    const byNode: Record<string, ProjectSnapshot["node_runs"][number]> = {};
    for (const run of selectedShotRuns) {
      const previous = byNode[run.node_key];
      if (!previous || run.attempt_no >= previous.attempt_no) byNode[run.node_key] = run;
    }
    return byNode;
  }, [selectedShotRuns]);

  const shotStatus = useQuery({
    queryKey: ["shot-status", projectId, selectedShot?.id],
    queryFn: () => fetchShotStatus(projectId, selectedShot!.id),
    enabled: projectId !== "demo" && !!selectedShot?.id,
    refetchInterval: 5000,
  });

  async function runShotOp(
    label: string,
    fn: () => Promise<{ status: string; message: string }>,
  ) {
    if (!selectedShot) return;
    setOpBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      setMsg(`${label}: ${r.status} — ${r.message}`);
      await qc.invalidateQueries({ queryKey: ["shots", projectId] });
      await qc.invalidateQueries({ queryKey: ["shot-status", projectId, selectedShot.id] });
      await qc.invalidateQueries({ queryKey: ["snapshot", projectId] });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setOpBusy(false);
    }
  }

  const nodeRailClass = useMemo(() => nodeRailForRuns(runs), [runs]);

  const selectedShotArt =
    selectedShot && snapshot.data
      ? shotKeyframeArtifact(snapshot.data, selectedShot.id)
      : null;
  const stageArt = selectedShot ? selectedShotArt : latestImageArtifact(arts);

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
            {zhNode(n)}
          </span>
        ))}
      </div>

      <div className="script-import-panel">
        <label>
          剧本文件
          <input
            type="file"
            accept=".md,.txt,text/markdown,text/plain"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              void file.text().then((text) => {
                setScriptFilename(file.name);
                setScriptText(text);
              });
            }}
          />
        </label>
        <label>
          文件名
          <input
            value={scriptFilename}
            onChange={(event) => setScriptFilename(event.target.value)}
            maxLength={260}
          />
        </label>
        <label>
          剧本
          <textarea
            value={scriptText}
            onChange={(event) => setScriptText(event.target.value)}
            rows={10}
            spellCheck={false}
          />
        </label>
      </div>

      <div className="toolbar">
        <button
          type="button"
          className="primary"
          data-testid="import-golden"
          onClick={() => importMut.mutate()}
          disabled={importMut.isPending}
        >
          {importMut.isPending ? "导入中…" : "① 导入剧本"}
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
                {shots.data.map((s) => {
                  const art = snapshot.data
                    ? shotKeyframeArtifact(snapshot.data, s.id)
                    : null;
                  const shotRuns = runs.filter(
                    (run) => String(run.input_snapshot?.shot_id ?? "") === s.id,
                  );
                  const shotNodeRailClass = nodeRailForRuns(shotRuns);
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
                        <div className="title">分镜 {s.shot_number || s.sort_order}</div>
                        <div className="meta">{s.visual_description.slice(0, 80)}</div>
                        {s.dialogue ? <div className="meta">「{s.dialogue}」</div> : null}
                        <div className="node-dots" title="shot-p0-v1">
                          {NODES.map((n) => (
                            <span
                              key={n}
                              className={`dot ${shotNodeRailClass[n] || ""}`}
                              title={zhNode(n)}
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
                  <span key={n} className={`pipeline-node ${nodeRailForRuns(selectedShotRuns)[n] ?? ""}`}>
                    {n}
                  </span>
                ))}
              </div>
              <div className="node-runtime-table" data-testid="shot-runtime-nodes">
                {NODES.map((node) => {
                  const run = selectedShotByNode[node];
                  const dependencies = run?.upstream_dependencies?.length
                    ? run.upstream_dependencies.map(
                        (dependency) =>
                          `${zhNode(dependency.node_key)}：${zhStatus(dependency.status)}`,
                      )
                    : (NODE_DEPENDENCIES[node] ?? []).map((dependency) => `${zhNode(dependency)}：—`);
                  const artifact = run?.result_artifact_id
                    ? arts.find((item) => item.id === run.result_artifact_id)
                    : null;
                  const state = nodeStatusLabel(run, node);
                  const stateClass = run ? statusClass(run.status) : dependencies.length ? "run" : "";
                  return (
                    <article className="node-runtime-row" key={node} data-testid={`shot-runtime-node-${node}`}>
                      <div className="node-runtime-heading">
                        <strong>{zhNode(node)}</strong>
                        <span className={`node-runtime-state ${stateClass}`}>{state}</span>
                      </div>
                      <dl className="node-runtime-meta">
                        <dt>尝试</dt>
                        <dd>{run?.attempt_no ?? "—"}</dd>
                        <dt>依赖</dt>
                        <dd>{dependencies.length ? dependencies.join(" · ") : "—"}</dd>
                        <dt>开始</dt>
                        <dd>{formatTimestamp(run?.started_at ?? null)}</dd>
                        <dt>结束</dt>
                        <dd>{formatTimestamp(run?.finished_at ?? null)}</dd>
                        <dt>Provider 成本</dt>
                        <dd>{run?.provider_cost ?? "0"}</dd>
                        <dt>产物</dt>
                        <dd>
                          {artifact ? (
                            <a href={artifactContentUrl(projectId, artifact.id)} target="_blank" rel="noreferrer">
                              {artifact.id.slice(0, 8)}… · {artifact.byte_size}B
                            </a>
                          ) : "—"}
                        </dd>
                        <dt>错误</dt>
                        <dd className={run?.error_code ? "status-bad" : undefined}>
                          {run?.error_code
                            ? zhErrorSummary(run.error_code, run.error_summary)
                            : "—"}
                        </dd>
                        <dt>处理建议</dt>
                        <dd>{retrySuggestion(run?.error_code ?? null)}</dd>
                      </dl>
                    </article>
                  );
                })}
              </div>
              {shotStatus.data && (
                  <div className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }} data-testid="shot-status">
                  运行={shotStatus.data.node_run_count} 失败={shotStatus.data.failed_count}{" "}
                  锁定={String(shotStatus.data.locked)}
                  {shotStatus.data.guidance ? (
                    <div className="status-bad">
                      {zhErrorCode(shotStatus.data.guidance.error_code)}：{shotStatus.data.guidance.retry_suggestion}
                    </div>
                  ) : null}
                </div>
              )}
              <div className="toolbar" data-testid="shot-ops">
                <button
                  type="button"
                  className="primary"
                  disabled={opBusy}
                  data-testid="shot-start"
                  onClick={() =>
                    void runShotOp("启动", () => startShot(projectId, selectedShot.id))
                  }
                >
                  启动生产
                </button>
                <button
                  type="button"
                  className="accent"
                  disabled={opBusy}
                  data-testid="shot-approve"
                  onClick={() =>
                    void runShotOp("审核通过", () => approveShot(projectId, selectedShot.id))
                  }
                >
                  审核通过
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={opBusy}
                  data-testid="shot-reject"
                  onClick={() =>
                    void runShotOp("驳回", () =>
                      rejectShot(projectId, selectedShot.id, "需要返工"),
                    )
                  }
                >
                  驳回
                </button>
                <button
                  type="button"
                  disabled={opBusy}
                  data-testid="shot-lock"
                  onClick={() =>
                    void runShotOp("人工锁", () => lockShot(projectId, selectedShot.id, true))
                  }
                >
                  人工锁
                </button>
                <button
                  type="button"
                  disabled={opBusy}
                  data-testid="shot-unlock"
                  onClick={() =>
                    void runShotOp("解锁", () => lockShot(projectId, selectedShot.id, false))
                  }
                >
                  解锁
                </button>
                <button
                  type="button"
                  disabled={opBusy}
                  data-testid="shot-rerun-subtitle"
                  onClick={() =>
                    void runShotOp("局部重跑字幕", () =>
                      rerunShot(projectId, selectedShot.id, "subtitle"),
                    )
                  }
                >
                  字幕局部重跑
                </button>
              </div>
              <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
                真实路径：NodeRun → Outbox → Arq → Worker → Artifact → 审核。假黄金批处理仅夹具。
                手工媒体：POST …/manual-media（受审计上传）。
              </p>
            </div>
          )}

          {snapshot.data && (
            <div className="panel" data-testid="production-snapshot">
              <h3>运行时 · {snapshot.data.name}</h3>
              <div className="split-2">
                <div>
                  <h4>最近 NodeRun 记录</h4>
                  <ul className="dense">
                    {snapshot.data.node_runs.slice(0, 20).map((r) => (
                      <li key={r.id}>
                        <code>{r.id.slice(0, 8)}</code>
                        <strong className={statusClass(r.status) === "done" ? "status-ok" : statusClass(r.status) === "fail" ? "status-bad" : "status-pending"}>
                          {zhStatus(r.status)}
                        </strong>
                      </li>
                    ))}
                    {snapshot.data.node_runs.length === 0 && (
                      <li className="muted">尚无 NodeRun 记录</li>
                    )}
                  </ul>
                </div>
                <div>
                  <h4>产物列表</h4>
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
          <ArtifactStage
            projectId={projectId}
            stageArt={stageArt}
            stageLabel={
              selectedShot
                ? `Shot ${selectedShot.shot_number || selectedShot.sort_order}`
                : "最新分镜图"
            }
            previewArts={previewArts}
          />
        </aside>
      </div>
    </div>
  );
}
