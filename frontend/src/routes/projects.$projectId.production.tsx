import { useQuery } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";

import { fetchSnapshot } from "../lib/api";
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

function ProductionPage() {
  const { projectId } = projectProductionRoute.useParams();
  const snapshot = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 4000,
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
