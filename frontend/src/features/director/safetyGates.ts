import type { CostEstimatePayload } from "./types";

export function isTrialPricingReady(cost: CostEstimatePayload): boolean {
  return cost.trial_total !== null && cost.trial.every((line) => line.status === "known");
}

export function isProductionPricingReady(cost: CostEstimatePayload | null): boolean {
  return Boolean(
    cost &&
      cost.production_total !== null &&
      cost.production.every((line) => line.status === "known"),
  );
}

export function areTrialRunsTerminal(statuses: string[]): boolean {
  return statuses.length > 0 && statuses.every((status) => !["queued", "running", "leased"].includes(status));
}
