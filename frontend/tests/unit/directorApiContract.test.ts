import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import * as directorApi from "../../src/features/director/api";
import { DIRECTOR_ROUTE_TEMPLATES, directorPath } from "../../src/features/director/api";

/**
 * The generated contract is the backend's published route table. Reading its
 * emitted literals keeps this check honest at runtime while `vitest` runs from
 * `frontend/`; it fails when a director request path stops matching the served
 * surface (the proactive recommendation once silently pointed at
 * `/api/v1/projects/{project_id}/shots/{shot_id}/recommendation`).
 */
const generatedSource = readFileSync("src/shared/api/generated.ts", "utf-8");
const emittedPaths = new Set(
  [...generatedSource.matchAll(/^\s{4}"(\/api\/v1\/[^"]+)": \{/gm)].map((match) => match[1]),
);

describe("director API routes match the generated OpenAPI contract", () => {
  it("reads the generated route table", () => {
    expect(emittedPaths.size).toBeGreaterThan(50);
  });

  it("declares every director template in the generated contract", () => {
    for (const [name, template] of Object.entries(DIRECTOR_ROUTE_TEMPLATES)) {
      expect(emittedPaths.has(template), `${name} is not served: ${template}`).toBe(true);
    }
  });

  it("routes the proactive Shot recommendation through /director", () => {
    expect(DIRECTOR_ROUTE_TEMPLATES.recommendation).toBe(
      "/api/v1/projects/{project_id}/director/shots/{shot_id}/recommendation",
    );
  });

  it("substitutes every placeholder when building a request path", () => {
    expect(directorPath("project-1", "recommendation", { shot_id: "shot-1" })).toBe(
      "/api/v1/projects/project-1/director/shots/shot-1/recommendation",
    );
    expect(directorPath("project-1", "turns")).toBe("/api/v1/projects/project-1/director/turns");
    expect(directorPath("project-1", "runtimeTurnStop", { turn_id: "turn-9" })).toBe(
      "/api/v1/projects/project-1/director/runtime/turns/turn-9/stop",
    );
  });

  it("exposes the recommendation request used by the Shot panel", () => {
    expect(typeof directorApi.recommendShotDesign).toBe("function");
    expect(directorApi.requestShotDirectorSuggestion).toBe(directorApi.suggestShotDesign);
  });
});
