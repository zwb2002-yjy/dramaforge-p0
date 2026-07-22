import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import {
  ApiError,
  artifactContentUrl,
  confirmBrief,
  createPlan,
  fetchCreationState,
  fetchSnapshot,
  generateBriefAgent,
  generatePlanFromBrief,
  registerLeadCharacter,
  updateBrief,
} from "../lib/api";
import { imageArtifacts, latestImageArtifact } from "../lib/projectMedia";
import {
  manualPlanSaveState,
  normalizeCreationState,
  prepareAndEnqueueKeyframe,
  requiresAgentBriefRegeneration,
  requiresAgentPlanRegeneration,
} from "../lib/quickWorkflow";
import { projectRoute } from "./projects.$projectId";

export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  component: QuickModePage,
});

type Step = 1 | 2 | 3 | 4 | 5;
type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : null;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asObjectList(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.map(asObject).filter((item): item is JsonObject => item !== null)
    : [];
}

function SummaryField({ label, value }: { label: string; value: unknown }) {
  const text = asText(value);
  if (!text) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{text}</dd>
    </>
  );
}

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
  const [briefBody, setBriefBody] = useState<JsonObject | null>(null);
  const [planBody, setPlanBody] = useState<JsonObject | null>(null);
  const [briefRev, setBriefRev] = useState<string | null>(null);
  const [briefStatus, setBriefStatus] = useState<string | null>(null);
  const [briefSource, setBriefSource] = useState<string | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [planSource, setPlanSource] = useState<string | null>(null);
  const [nodeRunId, setNodeRunId] = useState<string | null>(null);
  const [leadName, setLeadName] = useState("林夏");
  const [canonKey, setCanonKey] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hydratedProjectId, setHydratedProjectId] = useState<string | null>(null);

  const creationState = useQuery({
    queryKey: ["creation-state", projectId],
    queryFn: () => fetchCreationState(projectId),
    enabled: projectId !== "demo",
  });

  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 2500,
  });

  const runs = snapshot.data?.node_runs ?? [];
  const arts = snapshot.data?.artifacts ?? [];
  const previewArts = imageArtifacts(arts);
  const latestArt = latestImageArtifact(arts);
  const previewUrl =
    latestArt && projectId !== "demo" ? artifactContentUrl(projectId, latestArt.id) : null;
  const protagonist = asObject(briefBody?.protagonist);
  const protagonistSummary = [
    asText(protagonist?.name),
    asText(protagonist?.profile),
    asText(protagonist?.goal),
  ]
    .filter(Boolean)
    .join(" · ");
  const planShots = asObjectList(planBody?.shots);
  const visualBible = asObject(planBody?.visual_bible);
  const agentBriefNeedsRegeneration = requiresAgentBriefRegeneration(briefSource, briefBody);
  const agentPlanNeedsRegeneration = requiresAgentPlanRegeneration(planSource, planBody);
  const manualPlanControl = manualPlanSaveState(planSource, briefStatus);

  useEffect(() => {
    if (!creationState.data || hydratedProjectId === projectId) return;
    const restored = normalizeCreationState(creationState.data);
    setStep(restored.step);
    setBriefRev(restored.briefRev);
    setBriefStatus(restored.briefStatus);
    setBriefSource(restored.briefSource);
    setBriefBody(restored.briefBody);
    setLogline(restored.logline);
    setTone(restored.tone);
    setAudience(restored.audience);
    if (restored.logline) setIdea(restored.logline);
    if (restored.leadName) setLeadName(restored.leadName);
    setPlanId(restored.planId);
    setPlanSource(restored.planSource);
    setPlanBody(restored.planBody);
    setPrompt(restored.prompt);
    setShotNotes(restored.shotNotes);
    if (restored.agentBriefNeedsRegeneration && restored.agentPlanNeedsRegeneration) {
      setErr("检测到旧版 Agent Brief 和 Plan。请重新生成 Brief、确认后再生成 10 Shot Plan。");
    } else if (restored.agentBriefNeedsRegeneration) {
      setErr("检测到旧版 Agent Brief，内容不完整。请重新生成 Brief 后再规划。");
    } else if (restored.agentPlanNeedsRegeneration) {
      setErr("检测到旧版 Agent Plan，不含完整 10 Shot。请重新点击「Agent 生成 Plan」。");
    }
    setHydratedProjectId(projectId);
  }, [creationState.data, hydratedProjectId, projectId]);

  const agentBrief = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      setErr(null);
      return generateBriefAgent(projectId, idea, true);
    },
    onSuccess: (r) => {
      setBriefRev(r.id);
      setBriefStatus(r.status);
      setBriefSource("agent");
      setBriefBody(r.brief);
      setLogline(String(r.brief.logline ?? ""));
      setTone(String(r.brief.tone ?? ""));
      setAudience(String(r.brief.audience ?? ""));
      const generatedLeadName = asText(asObject(r.brief.protagonist)?.name);
      if (generatedLeadName) setLeadName(generatedLeadName);
      setPlanId(null);
      setPlanSource(null);
      setPlanBody(null);
      setPrompt("");
      setShotNotes("");
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
      setBriefStatus(r.status);
      setBriefSource("user");
      setBriefBody(r.brief ?? { logline: logline || idea, tone, audience });
      setPlanId(null);
      setPlanSource(null);
      setPlanBody(null);
      setMsg(`Brief 草稿已保存 · revision ${r.id.slice(0, 8)}…（请确认）`);
      setStep(2);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const doConfirmBrief = useMutation({
    mutationFn: async () => {
      if (!briefRev) throw new Error("请先生成或保存 Brief");
      return confirmBrief(projectId, briefRev);
    },
    onSuccess: (r) => {
      setBriefStatus(r.status);
      setMsg("Brief 已确认 → 可生成 Plan");
      setStep(3);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const agentPlan = useMutation({
    mutationFn: async () => {
      if (!briefRev) throw new Error("需要已确认的 Brief revision");
      if (agentBriefNeedsRegeneration) {
        throw new Error("旧版 Agent Brief 内容不完整，请先重新生成并确认 Brief");
      }
      setErr(null);
      return generatePlanFromBrief(projectId, briefRev, briefStatus, true);
    },
    onSuccess: (r) => {
      setBriefStatus("confirmed");
      setPlanId(r.id);
      setPlanSource("agent");
      setPlanBody(r.plan);
      setPrompt(String(r.plan.prompt ?? ""));
      setShotNotes(String(r.plan.shot_notes ?? ""));
      setMsg(
        `Agent Plan 已生成 · ${asObjectList(r.plan.shots).length} Shot · plan ${r.id.slice(0, 8)}…`,
      );
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
      if (briefStatus !== "confirmed") {
        await confirmBrief(projectId, briefRev);
      }
      return createPlan(projectId, briefRev, prompt || `Keyframe: ${logline || idea}`);
    },
    onSuccess: (r) => {
      setBriefStatus("confirmed");
      setPlanId(r.id);
      setPlanSource("manual");
      setPlanBody({ prompt: prompt || `Keyframe: ${logline || idea}`, shot_notes: shotNotes });
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
      if (agentPlanNeedsRegeneration) {
        throw new Error("旧版 Agent Plan 不含完整 10 Shot，请重新生成 Plan");
      }
      setErr(null);
      const result = await prepareAndEnqueueKeyframe({
        projectId,
        planId,
        canonKey,
        leadName,
      });
      if (result.canonicalObjectKey && result.canonicalObjectKey !== canonKey) {
        setCanonKey(result.canonicalObjectKey);
      }
      setNodeRunId(result.mat.node_run_id);
      return result;
    },
    onSuccess: async (r) => {
      setMsg(
        `已物化并入队 ${r.enqueues.length} 个 Shot · 首个 node_run ${r.mat.node_run_id.slice(0, 8)}… · 等待 Worker`,
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
          <h2 style={{ margin: 0 }}>快速创作 · 10 Shot 分镜</h2>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Brief → 10 Shot Plan → 主角 → 全部分镜首帧。完成后进入
            <Link to="/projects/$projectId/production" params={{ projectId }}>
              {" "}
              专业生产板
            </Link>
            继续审核与合成。
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
                  setMsg("已切换手工 Brief：编辑字段后点「保存 Brief 草稿」");
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
                <input
                  value={tone}
                  onChange={(e) => setTone(e.target.value)}
                  placeholder="悬疑 / 霓虹 / 雨夜"
                />
              </label>
              <label>
                Audience
                <input
                  value={audience}
                  onChange={(e) => setAudience(e.target.value)}
                  placeholder="短视频 · 18-35"
                />
              </label>
            </div>
            <div className="toolbar">
              <button
                type="button"
                data-testid="save-manual-brief"
                disabled={busy}
                onClick={() => manualBrief.mutate()}
              >
                保存 Brief 草稿
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
            {briefBody && (
              <dl className="creative-summary" data-testid="agent-brief-summary">
                <SummaryField label="标题" value={briefBody.title} />
                <SummaryField label="梗概" value={briefBody.synopsis} />
                <SummaryField label="主角" value={protagonistSummary} />
                <SummaryField label="冲突" value={briefBody.conflict} />
                <SummaryField label="代价" value={briefBody.stakes} />
                <SummaryField label="世界" value={briefBody.world} />
                <SummaryField label="视觉" value={briefBody.visual_style} />
                <SummaryField label="钩子" value={briefBody.episode_hook} />
              </dl>
            )}
            {briefRev && (
              <p className="muted">
                revision <code>{briefRev.slice(0, 12)}…</code>
              </p>
            )}
          </section>

          <section className="panel" data-testid="step-plan">
            <h3>③ Plan · 分镜与视觉规范</h3>
            <div className="toolbar">
              <button
                type="button"
                className="primary"
                data-testid="agent-plan"
                disabled={busy || !briefRev || agentBriefNeedsRegeneration}
                onClick={() => agentPlan.mutate()}
              >
                {agentPlan.isPending
                  ? "Agent 规划中…"
                  : briefStatus === "confirmed"
                    ? "Agent 生成 Plan"
                    : "确认 Brief 并生成 Plan"}
              </button>
              <button
                type="button"
                data-testid="save-manual-plan"
                disabled={busy || !briefRev || manualPlanControl.disabled}
                onClick={() => manualPlan.mutate()}
              >
                {manualPlanControl.label}
              </button>
            </div>
            {agentBriefNeedsRegeneration && (
              <p className="status-bad" data-testid="legacy-agent-brief-warning">
                当前是旧版简略 Agent Brief。请重新生成并确认 Brief，之后才能生成新版 Plan。
              </p>
            )}
            <label>
              首镜 Keyframe prompt
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                readOnly={planSource === "agent"}
                rows={3}
                placeholder="cinematic keyframe, neon rain alley, lead character medium shot…"
              />
            </label>
            <label>
              Plan notes
              <textarea
                value={shotNotes}
                onChange={(e) => setShotNotes(e.target.value)}
                readOnly={planSource === "agent"}
                rows={2}
              />
            </label>
            {visualBible && (
              <dl className="creative-summary" data-testid="visual-bible">
                <SummaryField label="风格" value={visualBible.style} />
                <SummaryField label="色彩" value={visualBible.color_palette} />
                <SummaryField label="光线" value={visualBible.lighting} />
                <SummaryField label="角色连续性" value={visualBible.character_continuity} />
                <SummaryField label="负向词" value={visualBible.negative_prompt} />
              </dl>
            )}
            {planShots.length > 0 && (
              <div className="plan-shot-list" data-testid="agent-plan-shots">
                {planShots.map((shot, index) => (
                  <article className="plan-shot-row" key={`${asText(shot.shot_number)}-${index}`}>
                    <div className="plan-shot-heading">
                      <strong>Shot {asText(shot.shot_number) || index + 1}</strong>
                      <span>
                        {[
                          asText(shot.location),
                          asText(shot.shot_type),
                          asText(shot.camera_move),
                          asText(shot.duration_seconds) ? `${asText(shot.duration_seconds)}s` : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </div>
                    <p>{asText(shot.visual_description)}</p>
                    {asText(shot.dialogue) && (
                      <p className="muted">对白：{asText(shot.dialogue)}</p>
                    )}
                    <code>{asText(shot.keyframe_prompt)}</code>
                  </article>
                ))}
              </div>
            )}
            {planId && (
              <p className="muted">
                plan <code>{planId.slice(0, 12)}…</code>
              </p>
            )}
            {agentPlanNeedsRegeneration && (
              <p className="status-bad" data-testid="legacy-agent-plan-warning">
                当前 Agent Plan 不是完整 10 Shot，已禁止生产。请重新生成 Plan。
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
            <h3>④ 生产全部 Shot 首帧</h3>
            <p className="muted">
              Plan 会物化为真实 Shot，每个 Shot 创建独立 keyframe NodeRun 并交给 Worker。
            </p>
            <button
              type="button"
              className="accent"
              data-testid="produce-keyframe"
              disabled={busy || !planId || agentPlanNeedsRegeneration}
              onClick={() => produce.mutate()}
            >
              {produce.isPending
                ? "批量入队中…"
                : agentPlanNeedsRegeneration
                  ? "请先重新生成 10 Shot Plan"
                  : `确认 Plan 并生产${planShots.length ? ` ${planShots.length} 个` : "全部"} Shot`}
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
                  <img src={previewUrl} alt="latest keyframe" data-testid="artifact-preview-img" />
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
              {previewArts.slice(0, 6).map((a) => (
                <a
                  key={a.id}
                  className="ref-chip"
                  href={artifactContentUrl(projectId, a.id)}
                  target="_blank"
                  rel="noreferrer"
                  title={a.object_key}
                >
                  <img src={artifactContentUrl(projectId, a.id)} alt="" />
                </a>
              ))}
              {previewArts.length === 0 && <div className="ref-chip">空</div>}
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
