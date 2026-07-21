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
      setMsg(`Agent Brief 草稿已生成 revision=${r.id.slice(0, 8)}…（请确认后继续）`);
      setStep(2);
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.message.includes("TEXT_LLM")) {
        setErr("未配置文本 LLM Key：请改用「手工填写 Brief」，或在 .env 配置 TEXT_LLM_*");
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
      setMsg(`手工 Brief 草稿 revision=${r.id.slice(0, 8)}…`);
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
      setMsg(`Agent Plan 草稿 plan=${r.id.slice(0, 8)}…`);
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
      setMsg(`手工 Plan plan=${r.id.slice(0, 8)}…`);
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
        `lead character ${leadName}, consistent face, short drama`,
      );
    },
    onSuccess: (r) => {
      setCanonKey(r.canonical_object_key);
      setMsg(
        `主角 canonical 已注册：${r.name} provider=${r.provider} bytes=${r.byte_size} key=${r.canonical_object_key.slice(0, 48)}…`,
      );
    },
    onError: (e: Error) => setErr(e.message),
  });

  const produce = useMutation({
    mutationFn: async () => {
      if (!planId) throw new Error("需要 Plan");
      setErr(null);
      // Ensure lead exists for consistency path when possible
      if (!canonKey) {
        try {
          const lead = await registerLeadCharacter(
            projectId,
            leadName,
            `lead character ${leadName}, consistent face`,
          );
          setCanonKey(lead.canonical_object_key);
        } catch {
          // continue — keyframe may still run without hard require_canonical
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
        `已物化并执行 Worker：node_run=${r.mat.node_run_id.slice(0, 8)}… job=${r.enq.job_id} processed=${r.tick.processed}`,
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
      <h2>快速模式 · 标准竖切（Brief → Plan → 首帧）</h2>
      <p>
        Project <code>{projectId}</code>
        — 与专业模式同一 Project。Agent 调用需 BYOK 文本 Key；无 Key 请走手工路径。
      </p>
      <p className="muted">
        步骤：① 创意 ② Brief 确认 ③ Plan ④ 确认物化+Worker ⑤ 查看产物。完成后可到
        <Link to="/projects/$projectId/production" params={{ projectId }}>
          专业生产
        </Link>
        继续 10 Shot。
      </p>

      <ol className="workflow-steps" data-testid="workflow-steps">
        <li className={step >= 1 ? "active" : ""}>1. 创意</li>
        <li className={step >= 2 ? "active" : ""}>2. Brief</li>
        <li className={step >= 3 ? "active" : ""}>3. Plan</li>
        <li className={step >= 4 ? "active" : ""}>4. 生产</li>
        <li className={step >= 5 ? "active" : ""}>5. 结果</li>
      </ol>

      <section className="panel" data-testid="step-idea">
        <h3>① 创意 / Idea</h3>
        <label>
          故事创意
          <textarea value={idea} onChange={(e) => setIdea(e.target.value)} rows={3} />
        </label>
        <div className="toolbar">
          <button
            type="button"
            data-testid="agent-brief"
            disabled={busy}
            onClick={() => agentBrief.mutate()}
          >
            {agentBrief.isPending ? "Agent 生成中…" : "Agent 生成 Brief（BYOK 文本）"}
          </button>
          <button
            type="button"
            data-testid="manual-brief-fill"
            disabled={busy}
            onClick={() => {
              if (!logline) setLogline(idea);
              setStep(2);
              setMsg("已切换到手工 Brief：请编辑下方字段后点「保存手工 Brief」");
            }}
          >
            改用手工填写 Brief
          </button>
        </div>
      </section>

      <section className="panel" data-testid="step-brief">
        <h3>② Brief（可编辑后确认）</h3>
        <label>
          Logline
          <textarea value={logline} onChange={(e) => setLogline(e.target.value)} rows={2} />
        </label>
        <label>
          Tone
          <input value={tone} onChange={(e) => setTone(e.target.value)} />
        </label>
        <label>
          Audience
          <input value={audience} onChange={(e) => setAudience(e.target.value)} />
        </label>
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
            data-testid="confirm-brief"
            disabled={busy || !briefRev}
            onClick={() => doConfirmBrief.mutate()}
          >
            确认 Brief
          </button>
        </div>
        {briefRev && (
          <p className="muted">
            brief_revision: <code>{briefRev}</code>
          </p>
        )}
      </section>

      <section className="panel" data-testid="step-plan">
        <h3>③ Plan / 首帧提示词</h3>
        <div className="toolbar">
          <button
            type="button"
            data-testid="agent-plan"
            disabled={busy || !briefRev}
            onClick={() => agentPlan.mutate()}
          >
            {agentPlan.isPending ? "Agent 规划中…" : "Agent 生成 Plan（BYOK）"}
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
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
        </label>
        <label>
          Shot notes
          <textarea value={shotNotes} onChange={(e) => setShotNotes(e.target.value)} rows={2} />
        </label>
        {planId && (
          <p className="muted">
            plan: <code>{planId}</code>
          </p>
        )}
      </section>

      <section className="panel" data-testid="step-assets">
        <h3>③.5 主角 canonical（一致性门禁）</h3>
        <p className="muted">
          P0 要求主角至少 1 张 canonical 参考图。开发环境会调用图像 Adapter（Agnes 若已配置）生成参考肖像。
        </p>
        <label>
          主角名
          <input value={leadName} onChange={(e) => setLeadName(e.target.value)} />
        </label>
        <button
          type="button"
          data-testid="register-lead"
          disabled={busy}
          onClick={() => registerLead.mutate()}
        >
          {registerLead.isPending ? "注册中…" : "注册主角 + 生成 canonical 参考图"}
        </button>
        {canonKey && (
          <p className="status-ok">
            canonical: <code>{canonKey}</code>
          </p>
        )}
      </section>

      <section className="panel" data-testid="step-produce">
        <h3>④ 确认 Plan → 入队 → Worker 首帧</h3>
        <p className="muted">
          物化白名单：create_shot_stub + enqueue_keyframe。图像在 Worker 执行；
          <strong>development + Agnes Key</strong> 走真实生成，<code>APP_ENV=test</code> 仅测试用 Fake。
        </p>
        <button
          type="button"
          data-testid="produce-keyframe"
          disabled={busy || !planId}
          onClick={() => produce.mutate()}
        >
          {produce.isPending ? "生产中（真生成可能需数十秒）…" : "确认 Plan 并生产首帧"}
        </button>
        {nodeRunId && (
          <p>
            NodeRun: <code>{nodeRunId}</code>
          </p>
        )}
      </section>

      {msg && (
        <p data-testid="flow-msg" className="status-ok">
          {msg}
        </p>
      )}
      {err && (
        <p data-testid="flow-err" className="status-bad">
          {err}
        </p>
      )}

      <section className="panel" data-testid="step-result">
        <h3>⑤ 生产状态与预览</h3>
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
        {previewUrl && (
          <div data-testid="artifact-preview">
            <p>最近 Artifact 预览（需已登录 cookie）</p>
            <img
              src={previewUrl}
              alt="latest artifact"
              style={{ maxWidth: "100%", maxHeight: 360, border: "1px solid #333" }}
            />
          </div>
        )}
        {snapshot.data ? (
          <div data-testid="snapshot-panel">
            <h4>NodeRuns</h4>
            <ul>
              {snapshot.data.node_runs.slice(0, 20).map((r) => (
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
                </li>
              ))}
            </ul>
            <h4>Artifacts</h4>
            <ul>
              {snapshot.data.artifacts.slice(0, 15).map((a) => (
                <li key={a.id}>
                  <a href={`/api/v1/projects/${projectId}/artifacts/${a.id}/content`}>
                    {a.object_key}
                  </a>{" "}
                  · {a.byte_size}B
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted">尚无快照</p>
        )}
      </section>
    </div>
  );
}
