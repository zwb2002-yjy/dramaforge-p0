import { apiGet, ApiError } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ProductionStage = components["schemas"]["ProductionStageRead"];
export type ProductionSummary = components["schemas"]["ProductionSummaryRead"];
export type ProductionRunStatus = components["schemas"]["ProductionRunStatusRead"];
export type ProductionRunPage = components["schemas"]["ProductionRunPage"];
export type ProductionArtifactPage = components["schemas"]["ProductionArtifactPage"];

const projectPath = (projectId: string) => "/api/v1/projects/" + encodeURIComponent(projectId);

export async function fetchProductionSummary(projectId: string, signal?: AbortSignal) {
  const summary = await apiGet<ProductionSummary>(
    projectPath(projectId) + "/production-summary",
    undefined,
    signal,
  );
  if (
    !summary ||
    summary.project_id !== projectId ||
    ![
      summary.total_runs,
      summary.completed_runs,
      summary.running_runs,
      summary.failed_runs,
      summary.artifact_count,
    ].every((value) => Number.isInteger(value) && value >= 0) ||
    !Array.isArray(summary.recent_failures) ||
    !Array.isArray(summary.stages) ||
    summary.stages.some(
      (stage) =>
        !stage ||
        typeof stage.node_key !== "string" ||
        !stage.status_counts ||
        typeof stage.status_counts !== "object" ||
        Array.isArray(stage.status_counts) ||
        !Object.values(stage.status_counts).every(
          (count) => Number.isInteger(count) && count > 0,
        ) ||
        (stage.latest_failure !== null &&
          (!stage.latest_failure || stage.latest_failure.node_key !== stage.node_key)),
    ) ||
    new Set(summary.stages.map((stage) => stage.node_key)).size !== summary.stages.length
  ) {
    throw new Error("制作摘要回执不完整，请重新读取；这不代表没有任务。");
  }
  return summary;
}

/** Exact identities only; large tail plans are chunked instead of downloading project history. */
export async function fetchRunStatuses(projectId: string, runIds: string[], signal?: AbortSignal) {
  const result: ProductionRunStatus[] = [];
  const ids = [...new Set(runIds)];
  for (let start = 0; start < ids.length; start += 100) {
    signal?.throwIfAborted();
    const requested = ids.slice(start, start + 100);
    const query = new URLSearchParams(requested.map((id) => ["run_id", id]));
    const rows = await apiGet<ProductionRunStatus[]>(
      projectPath(projectId) + "/node-runs/status?" + query,
      undefined,
      signal,
    );
    if (
      !Array.isArray(rows) ||
      rows.length !== requested.length ||
      new Set(rows.map((row) => row.id)).size !== requested.length ||
      rows.some((row) => !requested.includes(row.id))
    ) {
      throw new Error("任务状态回执不完整，请重新读取，不能据此继续导出。");
    }
    result.push(...rows);
  }
  return result;
}

export function fetchRunHistory(projectId: string, cursor?: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", cursor);
  return apiGet<ProductionRunPage>(
    projectPath(projectId) + "/production-history/runs?" + query,
    undefined,
    signal,
  );
}

export function fetchArtifactHistory(
  projectId: string,
  cursor?: string | null,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", cursor);
  return apiGet<ProductionArtifactPage>(
    projectPath(projectId) + "/production-history/artifacts?" + query,
    undefined,
    signal,
  );
}

export function productionReadErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "制作状态接口不可用（404）。请确认项目仍可访问、前后端版本一致；这不代表素材已丢失，不要因此重复生成。";
  }
  if (error instanceof ApiError && [401, 403].includes(error.status)) {
    return "制作状态读取未获授权，请确认登录状态和当前工作空间。";
  }
  return "部分制作状态读取失败，相关统计暂不可用。请重新读取状态，不要将未知状态当作没有任务。";
}
