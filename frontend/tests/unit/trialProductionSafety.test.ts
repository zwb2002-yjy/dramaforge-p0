import { describe, expect, it } from "vitest";

import {
  areTrialRunsTerminal,
  isProductionPricingReady,
  isTrialPricingReady,
} from "../../src/features/director/safetyGates";
import type { CostEstimatePayload } from "../../src/features/director/types";

const cost = {
  pricing_snapshot_id: "prices-1",
  currency: "CNY",
  trial: [{ purpose: "video", quantity: 1, unit_amount: "1", estimated_amount: "1", currency: "CNY", status: "known" }],
  production: [{ purpose: "video", quantity: 4, unit_amount: "1", estimated_amount: "4", currency: "CNY", status: "known" }],
  repair: [],
  trial_total: "1",
  production_total: "4",
  repair_total: "0",
  requires_user_budget_limit: true,
  disclaimer: "estimate",
} satisfies CostEstimatePayload;

describe("Director media safety gates", () => {
  it("requires fully known trial and production prices", () => {
    expect(isTrialPricingReady(cost)).toBe(true);
    expect(isProductionPricingReady(cost)).toBe(true);
    expect(isTrialPricingReady({ ...cost, trial_total: null })).toBe(false);
    expect(isProductionPricingReady({ ...cost, production: [{ ...cost.production[0], status: "provider_not_reported" }] })).toBe(false);
  });

  it("allows trial inspection only after at least one run and all runs are terminal", () => {
    expect(areTrialRunsTerminal([])).toBe(false);
    expect(areTrialRunsTerminal(["completed", "failed"])).toBe(true);
    expect(areTrialRunsTerminal(["completed", "running"])).toBe(false);
  });

});
