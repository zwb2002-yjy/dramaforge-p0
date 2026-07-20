import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { useState } from "react";

import {
  confirmBrief,
  confirmPlan,
  createPlan,
  fetchCsrf,
  fetchSnapshot,
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
  return apiSend<{ processed: number }>(
    "POST",
    "/api/v1/worker/tick",
    {},
    undefined,
  ).catch(async () => {
    // worker token header required
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
  });
}

function QuickModePage() {
  const { projectId } = projectQuickRoute.useParams();
  const qc = useQueryClient();
  const [logline, setLogline] = useState("Hero enters neon rain street");
  const [prompt, setPrompt] = useState("Cinematic keyframe neon rain, 9:16");
  const [briefRev, setBriefRev] = useState<string | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [nodeRunId, setNodeRunId] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 2000,
  });

  const flow = useMutation({
    mutationFn: async () => {
      if (projectId === "demo") throw new Error("请从首页创建真实项目");
      const br = await updateBrief(projectId, logline);
      setBriefRev(br.id);
      const confirmed = await confirmBrief(projectId, br.id);
      const plan = await createPlan(projectId, confirmed.id, prompt);
      setPlanId(plan.id);
      const mat = await confirmPlan(projectId, plan.id);
      setNodeRunId(mat.node_run_id);
      // Product path: enqueue only — Adapter runs in Worker
      const enq = await enqueueNodeRun(projectId, mat.node_run_id);
      // Local dev: tick worker (same code path as arq execute_node_run)
      const tick = await workerTick();
      return { enq, tick, nodeRunId: mat.node_run_id };
    },
    onSuccess: async (r) => {
      setMsg(
        `enqueued job=${r.enq.job_id}; worker processed=${r.tick.processed}; run=${r.nodeRunId}`,
      );
      await qc.invalidateQueries({ queryKey: ["snapshot", projectId] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  return (
    <div data-testid="quick-mode">
      <h2>快速模式</h2>
      <p>
        Project <code>{projectId}</code> — 与专业入口共享同一项目。Adapter 仅在 Worker 执行。
      </p>
      <label>
        Brief logline
        <textarea value={logline} onChange={(e) => setLogline(e.target.value)} rows={2} />
      </label>
      <label>
        Plan prompt
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} />
      </label>
      <button type="button" onClick={() => flow.mutate()} disabled={flow.isPending}>
        {flow.isPending ? "执行中…" : "确认 Brief/Plan → 入队 → Worker 生产"}
      </button>
      {msg && <p data-testid="flow-msg">{msg}</p>}
      {briefRev && <p>Brief revision: {briefRev}</p>}
      {planId && <p>Plan: {planId}</p>}
      {nodeRunId && <p>NodeRun: {nodeRunId}</p>}

      <h3>快照（轮询 PostgreSQL）</h3>
      {snapshot.data ? (
        <div data-testid="snapshot-panel">
          <p>Runs: {snapshot.data.node_runs.length}</p>
          <ul>
            {snapshot.data.node_runs.map((r) => (
              <li key={r.id}>
                {r.id.slice(0, 8)}… <strong>{r.status}</strong>
              </li>
            ))}
          </ul>
          <p>Artifacts: {snapshot.data.artifacts.length}</p>
          <ul>
            {snapshot.data.artifacts.map((a) => (
              <li key={a.id}>
                {a.object_key} · {a.byte_size}B · {a.content_hash.slice(0, 12)}…
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">无快照（demo 或未登录）</p>
      )}
    </div>
  );
}
