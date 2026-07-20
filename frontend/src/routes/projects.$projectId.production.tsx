import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { useState } from "react";

import {
  exportProject,
  fetchProjectShots,
  fetchSnapshot,
  importScript,
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
      setMsg(
        `export timeline=${r.timeline_hash.slice(0, 12)}… srt=${r.srt_hash.slice(0, 12)}… items=${r.export_item_count} mp4_err=${r.mp4_error ?? "none"}`,
      );
    },
    onError: (e: Error) => setMsg(e.message),
  });

  return (
    <div data-testid="production-mode">
      <h2>专业生产</h2>
      <p>
        同一 Project：<code>{projectId}</code>
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
          disabled={importMut.isPending}
        >
          {importMut.isPending ? "导入中…" : "导入黄金样本剧本 (10 Shot)"}
        </button>
        <button
          type="button"
          data-testid="export-project"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
        >
          {exportMut.isPending ? "导出中…" : "导出 timeline/SRT/素材包"}
        </button>
      </div>
      {msg && <p data-testid="production-msg">{msg}</p>}
      {shots.data && shots.data.length > 0 && (
        <div data-testid="shot-list">
          <h3>Shots ({shots.data.length})</h3>
          <ol>
            {shots.data.map((s) => (
              <li key={s.id}>
                #{s.sort_order} {s.shot_type} — {s.visual_description.slice(0, 80)}
                {s.dialogue ? ` · 「${s.dialogue}」` : ""}
              </li>
            ))}
          </ol>
        </div>
      )}
      {snapshot.data && (
        <div data-testid="production-snapshot">
          <h3>NodeRuns / Artifacts（与快速模式同源）</h3>
          <p>project: {snapshot.data.name}</p>
          <ul>
            {snapshot.data.node_runs.map((r) => (
              <li key={r.id}>
                {r.status} · artifact={r.result_artifact_id ?? "—"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
