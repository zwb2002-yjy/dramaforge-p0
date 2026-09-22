import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { queryKeys } from "../../lib/queryKeys";
import { fetchRunStatuses } from "../production/api";
import { deliveryGateMessage } from "./deliveryGate";
import {
  fetchEditFinalFilms,
  fetchFinalFilmStatus,
  prepareFinalFilm,
  renderFinalFilm,
  type FinalFilmRead,
  type FinalFilmJobRead,
} from "./api";

const SUCCEEDED = new Set(["completed", "cached", "completed_after_cancel"]);
const FAILED = new Set(["failed", "blocked", "cancelled"]);

function wait(signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, 1200);
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function waitForTail(projectId: string, ids: string[], signal: AbortSignal) {
  if (ids.length === 0) return;
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    signal.throwIfAborted();
    const rows = await fetchRunStatuses(projectId, ids, signal);
    if (rows.some((run) => FAILED.has(run.status))) {
      throw new Error("成片尾链有任务失败，请先处理生产错误。");
    }
    if (rows.every((run) => SUCCEEDED.has(run.status))) return;
    await wait(signal);
  }
  throw new Error("等待成片尾链超时，请到制作页查看任务状态。");
}

async function waitForFilm(projectId: string, initial: FinalFilmJobRead, signal: AbortSignal) {
  const deadline = Date.now() + 15 * 60 * 1000;
  let current = initial;
  while (Date.now() < deadline) {
    signal.throwIfAborted();
    if (FAILED.has(current.status)) throw new Error(current.error_summary || "成片渲染失败。");
    if (current.result && SUCCEEDED.has(current.status)) return current.result;
    await wait(signal);
    current = await fetchFinalFilmStatus(projectId, initial.node_run_id, signal);
  }
  throw new Error("等待成片渲染超时，请到制作页查看任务状态。");
}

/** Observe one explicit export intent. Unmount aborts GETs, never a submitted job. */
export function useFinalFilmExport({
  projectId,
  sessionId,
  version,
  dirty,
}: {
  projectId: string;
  sessionId?: string;
  version?: number;
  dirty: boolean;
}) {
  const client = useQueryClient();
  const [result, setResult] = useState<FinalFilmRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<"prepare" | "tail" | "render" | null>(null);
  const [selectedHistory, setSelectedHistory] = useState<string | null>(null);
  const observation = useRef<AbortController | null>(null);
  const scope = useRef({ projectId, sessionId });
  scope.current = { projectId, sessionId };
  useEffect(() => {
    setResult(null);
    setError(null);
    setPending(null);
    setSelectedHistory(null);
    return () => {
      observation.current?.abort();
      observation.current = null;
    };
  }, [projectId, sessionId]);
  const filmHistory = useQuery({
    queryKey: queryKeys.editing.films(projectId, sessionId, version),
    queryFn: ({ signal }) => fetchEditFinalFilms(projectId, sessionId!, signal),
    enabled: Boolean(projectId) && Boolean(sessionId) && version !== undefined,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((job) =>
        ["queued", "running", "cancel_requested"].includes(job.status),
      )
        ? 5000
        : false,
  });
  const recovered = selectedHistory
    ? filmHistory.data?.find((job) => job.node_run_id === selectedHistory)?.result
    : filmHistory.data?.find((job) => job.result)?.result;
  const displayedFilm =
    [result, recovered].find(
      (film) => film?.project_id === projectId && film.edit_session_id === sessionId,
    ) ?? null;
  const selectHistoryRun = (id: string) => {
    setSelectedHistory(id);
    setResult(null);
  };

  async function exportFilm() {
    if (dirty) {
      setError("时间线有未保存修改，请先保存后再导出成片。");
      return;
    }
    if (!sessionId || !Number.isInteger(version) || (version ?? 0) < 1) {
      setError("请先创建并加载剪辑会话后再导出成片。");
      return;
    }
    if (observation.current) return; // Includes the synchronous double-click window.
    const controller = new AbortController();
    observation.current = controller;
    const { signal } = controller;
    const current = () =>
      !signal.aborted &&
      observation.current === controller &&
      scope.current.projectId === projectId &&
      scope.current.sessionId === sessionId;
    const historyKey = queryKeys.editing.films(projectId, sessionId, version);
    const exactVersion = version!;
    try {
      setError(null);
      setPending("prepare");
      // Writes are not cancelled/retried: their receipt may already be durable.
      const prepared = await prepareFinalFilm(projectId, sessionId, exactVersion);
      if (!current()) return;
      setPending("tail");
      await waitForTail(projectId, prepared.node_run_ids, signal);
      if (!current()) return;
      if (!/^[a-f0-9]{64}$/.test(prepared.preparation_fingerprint)) {
        throw new Error("成片准备回执缺少素材版本，请确认前后端版本一致；不要重复生成。");
      }
      setPending("render");
      const queued = await renderFinalFilm(
        projectId,
        sessionId,
        exactVersion,
        // The session UUID already identifies the project. Keep the full media
        // fingerprint plus timeline version within the backend's 120-byte key limit.
        `final-${sessionId}-${exactVersion}-${prepared.preparation_fingerprint}`,
      );
      void client.invalidateQueries({ queryKey: historyKey });
      if (!current()) return;
      const film = await waitForFilm(projectId, queued, signal);
      if (current()) setResult(film);
    } catch (cause) {
      if (current()) setError("成片导出失败：" + deliveryGateMessage(cause));
    } finally {
      if (current()) setPending(null);
      if (observation.current === controller) observation.current = null;
      void client.invalidateQueries({ queryKey: historyKey });
    }
  }
  return { filmHistory, displayedFilm, selectHistoryRun, exportFilm, pending, error };
}
