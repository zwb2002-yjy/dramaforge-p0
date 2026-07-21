import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute } from "@tanstack/react-router";
import { useState } from "react";

import {
  ApiError,
  confirmBrief,
  confirmPlan,
  createPlan,
  fetchCsrf,
  fetchSnapshot,
  generateBriefAgent,
  generatePlanAgent,
  registerLeadCharacter,
  updateBrief,
  apiSend,
} from "../lib/api";
import { projectRoute } from "./projects.$projectId";

export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  component: QuickModePage,
});

async function enqueueNodeRun(projectId: string, nodeRunId: string) {
  const csrf = await fetchCsrf();
  return apiSend<{ node_run_id: string; status: string; job_id: string }>(
    "POST",
    `/api/v1/projects/${projectId}/node-runs/${nodeRunId}/enqueue`,
    {},
    csrf,
  );
}

async function workerTick() {
  const res = await fetch("/api/v1/worker/tick", {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "X-Worker-Token": "dev-worker-token",
    },
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as { processed: number };
}

type Step = 1 | 2 | 3 | 4 | 5;

function QuickModePage() {
  const { projectId } = projectQuickRoute.useParams();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>(1);
  const [idea, setIdea] = useState("霓虹雨夜短剧：女主林夏在巷口发现被跟踪");
  const [logline, setLogline] = useState("");
  const [tone, setTone] = useState("");
  const [audience, setAudience] = useState("");
  const [prompt, setPrompt] = useState("");
  const [shotNotes, setShotNotes] = useState("");
  const [briefRev, setBriefRev] = useState<string | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [nodeRunId, setNodeRunId] = useState<string | null>(null);
  const [leadName, setLeadName] = useState("林夏");
  const [canonKey, setCanonKey] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 2500,
  });

  const runs = snapshot.data?.node_runs ?? [];
  const arts = snapshot.data?.artifacts ?? [];
  const latestArt = arts[0];
  const previewUrl =
    latestArt && projectId !== "demo"
      ? `/api/v1/projects/${projectId}/artifacts/${latestArt.id}/content`
      : null;

  const agentBrief = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      setErr(null);
      return generateBriefAgent(projectId, idea, true);
    },
    onSuccess: (r) => {
      setBriefRev(r.id);
      setLogline(String(r.brief.logline ?? ""));
      setTone(String(r.brief.tone ?? ""));
      setAudience(String(r.brief.audience ?? ""));
      setMsg(`Agent Brief 已生成 · revision ${r.id.slice(0, 8)}…（请确认）`);
      setStep(2);
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && (e.message.includes("TEXT_LLM") || e.code?.includes?.("TEXT"))) {
        setErr("未配置文本 LLM Key：请改用「手工填写 Brief」，或配置 TEXT_LLM_*");
      } else {
        setErr(e.message);
      }
    },
  });

  const manualBrief = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      setErr(null);
      return updateBrief(projectId, logline || idea, tone, audience);
    },
    onSuccess: (r) => {
      setBriefRev(r.id);
      setMsg(`手工 Brief 已保存 · revision ${r.id.slice(0, 8)}…`);
      setStep(2);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const doConfirmBrief = useMutation({
    mutationFn: async () => {
      if (!briefRev) throw new Error("请先生成或保存 Brief");
      return confirmBrief(projectId, briefRev);
    },
    onSuccess: () => {
      setMsg("Brief 已确认 → 可生成 Plan");
      setStep(3);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const agentPlan = useMutation({
    mutationFn: async () => {
      if (!briefRev) throw new Error("需要已确认的 Brief revision");
      setErr(null);
      return generatePlanAgent(projectId, briefRev, true);
    },
    onSuccess: (r) => {
      setPlanId(r.id);
      setPrompt(String(r.plan.prompt ?? ""));
      setShotNotes(String(r.plan.shot_notes ?? ""));
      setMsg(`Agent Plan 已生成 · plan ${r.id.slice(0, 8)}…`);
      setStep(4);
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.message.includes("TEXT_LLM")) {
        setErr("未配置文本 LLM：请用「手工填写 Plan」");
      } else {
        setErr(e.message);
      }
    },
  });

  const manualPlan = useMutation({
    mutationFn: async () => {
      if (!briefRev) throw new Error("需要 Brief");
      return createPlan(projectId, briefRev, prompt || `Keyframe: ${logline || idea}`);
    },
    onSuccess: (r) => {
      setPlanId(r.id);
      setMsg(`手工 Plan 已保存 · plan ${r.id.slice(0, 8)}…`);
      setStep(4);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const registerLead = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      setErr(null);
      return registerLeadCharacter(
        projectId,
        leadName,
        `lead character ${leadName}, consistent face, short drama portrait, cinematic`,
      );
    },
    onSuccess: (r) => {
      setCanonKey(r.canonical_object_key);
      setMsg(`主角 canonical 已注册：${r.name} · ${r.byte_size}B · ${r.provider}`);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const produce = useMutation({
    mutationFn: async () => {
      if (!planId) throw new Error("需要 Plan");
      setErr(null);
      if (!canonKey) {
        try {
          const lead = await registerLeadCharacter(
            projectId,
            leadName,
            `lead character ${leadName}, consistent face`,
          );
          setCanonKey(lead.canonical_object_key);
        } catch {
          // keyframe may still run
        }
      }
      const mat = await confirmPlan(projectId, planId);
      setNodeRunId(mat.node_run_id);
      const enq = await enqueueNodeRun(projectId, mat.node_run_id);
      const tick = await workerTick();
      return { mat, enq, tick };
    },
    onSuccess: async (r) => {
      setMsg(
        `已物化并执行 Worker · node_run ${r.mat.node_run_id.slice(0, 8)}… · processed=${r.tick.processed}`,
      );
      setStep(5);
      await qc.invalidateQueries({ queryKey: ["snapshot", projectId] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  const busy =
    agentBrief.isPending ||
    manualBrief.isPending ||
    doConfirmBrief.isPending ||
    agentPlan.isPending ||
    manualPlan.isPending ||
    registerLead.isPending ||
    produce.isPending;

  return (
    <div data-testid="quick-mode">
      <div className="page-title-row">
        <div>
          <h2 style={{ margin: 0 }}>快速创作 · 首帧竖切</h2>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Brief → Plan → 主角 → Keyframe。完成后进入
            <Link to="/projects/$projectId/production" params={{ projectId }}>
              {" "}
              专业生产板
            </Link>
            继续 10 Shot。
          </p>
        </div>
      </div>

      <ol className="workflow-steps" data-testid="workflow-steps">
        <li className={step > 1 ? "done" : step >= 1 ? "active" : ""}>1. 创意</li>
        <li className={step > 2 ? "done" : step >= 2 ? "active" : ""}>2. Brief</li>
        <li className={step > 3 ? "done" : step >= 3 ? "active" : ""}>3. Plan</li>
        <li className={step > 4 ? "done" : step >= 4 ? "active" : ""}>4. 生产</li>
        <li className={step >= 5 ? "active" : ""}>5. 结果</li>
      </ol>

      {msg && (
        <div className="flash ok" data-testid="flow-msg">
          {msg}
        </div>
      )}
      {err && (
        <div className="flash err" data-testid="flow-err">
          {err}
        </div>
      )}

      <div className="studio">
        <div className="studio-editor">
          <section className="panel" data-testid="step-idea">
            <h3>① 创意</h3>
            <label>
              故事创意 / Idea
              <textarea value={idea} onChange={(e) => setIdea(e.target.value)} rows={3} />
            </label>
            <div className="toolbar">
              <button
                type="button"
                className="primary"
                data-testid="agent-brief"
                disabled={busy}
                onClick={() => agentBrief.mutate()}
              >
                {agentBrief.isPending ? "Agent 生成中…" : "Agent 生成 Brief"}
              </button>
              <button
                type="button"
                data-testid="manual-brief-fill"
                disabled={busy}
                onClick={() => {
                  if (!logline) setLogline(idea);
                  setStep(2);
                  setMsg("已切换手工 Brief：编辑字段后点「保存手工 Brief」");
                }}
              >
                改用手工 Brief
              </button>
            </div>
          </section>

          <section className="panel" data-testid="step-brief">
            <h3>② Brief</h3>
            <label>
              Logline
              <textarea value={logline} onChange={(e) => setLogline(e.target.value)} rows={2} />
            </label>
            <div className="split-2">
              <label>
                Tone
                <input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="悬疑 / 霓虹 / 雨夜" />
              </label>
              <label>
                Audience
                <input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="短视频 · 18-35" />
              </label>
            </div>
            <div className="toolbar">
              <button
                type="button"
                data-testid="save-manual-brief"
                disabled={busy}
                onClick={() => manualBrief.mutate()}
              >
                保存手工 Brief
              </button>
              <button
                type="button"
                className="primary"
                data-testid="confirm-brief"
                disabled={busy || !briefRev}
                onClick={() => doConfirmBrief.mutate()}
              >
                确认 Brief
              </button>
            </div>
            {briefRev && (
              <p className="muted">
                revision <code>{briefRev.slice(0, 12)}…</code>
              </p>
            )}
          </section>

          <section className="panel" data-testid="step-plan">
            <h3>③ Plan · 首帧提示词</h3>
            <div className="toolbar">
              <button
                type="button"
                className="primary"
                data-testid="agent-plan"
                disabled={busy || !briefRev}
                onClick={() => agentPlan.mutate()}
              >
                {agentPlan.isPending ? "Agent 规划中…" : "Agent 生成 Plan"}
              </button>
              <button
                type="button"
                data-testid="save-manual-plan"
                disabled={busy || !briefRev}
                onClick={() => manualPlan.mutate()}
              >
                保存手工 Plan
              </button>
            </div>
            <label>
              Keyframe prompt
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                placeholder="cinematic keyframe, neon rain alley, lead character medium shot…"
              />
            </label>
            <label>
              Shot notes
              <textarea value={shotNotes} onChange={(e) => setShotNotes(e.target.value)} rows={2} />
            </label>
            {planId && (
              <p className="muted">
                plan <code>{planId.slice(0, 12)}…</code>
              </p>
            )}
          </section>

          <section className="panel" data-testid="step-assets">
            <h3>主角 · Canonical</h3>
            <p className="muted">
              P0 一致性门禁需要主角 canonical 参考。开发环境可调用图像 Adapter（Agnes）生成肖像。
            </p>
            <label>
              主角名
              <input value={leadName} onChange={(e) => setLeadName(e.target.value)} />
            </label>
            <div className="toolbar">
              <button
                type="button"
                data-testid="register-lead"
                disabled={busy}
                onClick={() => registerLead.mutate()}
              >
                {registerLead.isPending ? "注册中…" : "注册主角 + 生成 canonical"}
              </button>
            </div>
            {canonKey && (
              <p className="status-ok" style={{ fontSize: "0.8rem", wordBreak: "break-all" }}>
                {canonKey}
              </p>
            )}
          </section>

          <section className="panel" data-testid="step-produce">
            <h3>④ 生产首帧</h3>
            <p className="muted">
              物化白名单：create_shot_stub + enqueue_keyframe。Worker 内执行图像 Adapter；
              development + Agnes Key 走真生成。
            </p>
            <button
              type="button"
              className="accent"
              data-testid="produce-keyframe"
              disabled={busy || !planId}
              onClick={() => produce.mutate()}
            >
              {produce.isPending ? "生产中（真生成可能数十秒）…" : "确认 Plan 并生产首帧"}
            </button>
            {nodeRunId && (
              <p className="muted" style={{ marginTop: "0.5rem" }}>
                NodeRun <code>{nodeRunId.slice(0, 12)}…</code>
              </p>
            )}
          </section>

          <section className="panel" data-testid="step-result">
            <h3>⑤ 运行时</h3>
            <div className="status-grid" data-testid="quick-stats">
              <div className="status-card">
                <span className="status-label">NodeRuns</span>
                <strong data-testid="quick-runs">{runs.length}</strong>
              </div>
              <div className="status-card">
                <span className="status-label">Artifacts</span>
                <strong data-testid="quick-arts">{arts.length}</strong>
              </div>
            </div>
            {snapshot.data ? (
              <ul className="dense" data-testid="snapshot-panel">
                {snapshot.data.node_runs.slice(0, 12).map((r) => (
                  <li key={r.id}>
                    <code>{r.id.slice(0, 8)}</code>
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
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">尚无快照</p>
            )}
          </section>
        </div>

        <aside className="studio-stage" data-testid="studio-stage">
          <div className="panel" style={{ padding: "0.85rem" }}>
            <h3 style={{ marginBottom: "0.65rem" }}>竖屏预览台</h3>
            <div className="stage-phone">
              {previewUrl ? (
                <>
                  <span className="stage-badge">9:16 · artifact</span>
                  <img
                    src={previewUrl}
                    alt="latest keyframe"
                    data-testid="artifact-preview-img"
                  />
                </>
              ) : (
                <div className="stage-empty">
                  尚无首帧产物
                  <br />
                  完成 Brief → Plan → 生产后
                  <br />
                  在此回看 keyframe
                </div>
              )}
            </div>
            <div className="stage-meta" data-testid="artifact-preview">
              {latestArt ? (
                <>
                  <div>
                    key <code>{latestArt.object_key.split("/").slice(-1)[0]}</code>
                  </div>
                  <div>
                    {latestArt.byte_size}B ·{" "}
                    <a href={previewUrl!} target="_blank" rel="noreferrer">
                      打开原图
                    </a>
                  </div>
                </>
              ) : (
                <span>等待 Worker 写入 Artifact…</span>
              )}
            </div>
            <div className="ref-strip" style={{ marginTop: "0.75rem" }}>
              {arts.slice(0, 6).map((a) => (
                <a
                  key={a.id}
                  className="ref-chip"
                  href={`/api/v1/projects/${projectId}/artifacts/${a.id}/content`}
                  target="_blank"
                  rel="noreferrer"
                  title={a.object_key}
                >
                  <img src={`/api/v1/projects/${projectId}/artifacts/${a.id}/content`} alt="" />
                </a>
              ))}
              {arts.length === 0 && <div className="ref-chip">空</div>}
            </div>
            <div className="toolbar" style={{ marginTop: "0.75rem" }}>
              <Link to="/projects/$projectId/production" params={{ projectId }}>
                <button type="button" className="primary">
                  去专业生产板 →
                </button>
              </Link>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
