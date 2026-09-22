import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { eventStreamUrl } from "../../lib/api";
import {
  parseProductionChange,
  productionQueryAffected,
  type ProductionChange,
} from "./productionInvalidation";

const PRODUCTION_FACTS_TOPIC = "production.facts.v1";
export const PRODUCTION_EVENT_BATCH_MS = 150;

export type ProductionFactsSseProps = { workspaceId: string | null };

/** Coalesce bursts and re-read only affected committed production projections. */
export function ProductionFactsSse({ workspaceId }: ProductionFactsSseProps) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!workspaceId || typeof EventSource === "undefined") return;
    const source = new EventSource(eventStreamUrl(workspaceId), { withCredentials: true });
    const pending = new Map<string, ProductionChange>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const flush = () => {
      timer = undefined;
      const changes = [...pending.values()];
      pending.clear();
      void queryClient.invalidateQueries(
        { predicate: (query) => productionQueryAffected(query, changes) },
        // A busy stream must not repeatedly abort an in-flight fact read.
        { cancelRefetch: false },
      );
    };
    const onProductionFacts = (event: Event) => {
      let data: unknown;
      try {
        data = JSON.parse((event as MessageEvent<string>).data) as unknown;
      } catch {
        return;
      }
      const change = parseProductionChange(data, workspaceId);
      if (!change) return;
      pending.set(JSON.stringify([change.projectId, change.kind, change.shotId]), change);
      // A fixed window (not a resetting debounce) cannot starve a busy project.
      timer ??= setTimeout(flush, PRODUCTION_EVENT_BATCH_MS);
    };
    source.addEventListener(PRODUCTION_FACTS_TOPIC, onProductionFacts);
    return () => {
      if (timer !== undefined) clearTimeout(timer);
      pending.clear();
      source.removeEventListener(PRODUCTION_FACTS_TOPIC, onProductionFacts);
      source.close();
    };
  }, [queryClient, workspaceId]);
  return null;
}
