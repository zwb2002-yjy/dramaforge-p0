import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const PRODUCTION_FACTS_TOPIC = "production.facts.v1";

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function projectIdFromEvent(data: unknown): string | null {
  const envelope = asRecord(data);
  if (!envelope || envelope.topic !== PRODUCTION_FACTS_TOPIC) return null;
  if (typeof envelope.project_id === "string") return envelope.project_id;
  const payload = asRecord(envelope.payload);
  return payload && typeof payload.project_id === "string" ? payload.project_id : null;
}

function eventStreamUrl(workspaceId: string): string {
  return `${API_BASE}/api/v1/events/stream?workspace_id=${encodeURIComponent(workspaceId)}`;
}

export type ProductionFactsSseProps = {
  workspaceId: string | null;
};

/** Keep active project queries fresh when a committed production fact arrives. */
export function ProductionFactsSse({ workspaceId }: ProductionFactsSseProps) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!workspaceId || typeof EventSource === "undefined") return;

    const source = new EventSource(eventStreamUrl(workspaceId), { withCredentials: true });
    const onProductionFacts = (event: Event) => {
      const message = event as MessageEvent<string>;
      let data: unknown;
      try {
        data = JSON.parse(message.data) as unknown;
      } catch {
        return;
      }
      const projectId = projectIdFromEvent(data);
      if (!projectId) return;

      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey.some((part) => part === projectId),
      });
    };

    source.addEventListener(PRODUCTION_FACTS_TOPIC, onProductionFacts);
    return () => {
      source.removeEventListener(PRODUCTION_FACTS_TOPIC, onProductionFacts);
      source.close();
    };
  }, [queryClient, workspaceId]);

  return null;
}
