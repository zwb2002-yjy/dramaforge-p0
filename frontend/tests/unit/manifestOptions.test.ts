/**
 * Manifest-driven model option rendering (V3 spec §59) — pure helpers.
 * No model/provider-name branching anywhere.
 */

import { describe, expect, it } from "vitest";
import type { CapabilitySpecRead } from "../../src/lib/api";
import {
  allowedValuesFor,
  constraintViolations,
  renderableOptions,
  uiComponentFor,
} from "../../src/lib/manifestOptions";

const DURATION_RESOLUTION_SPEC: CapabilitySpecRead = {
  capability: "video.image_to_video",
  input_slots: {},
  common_options: {
    duration_seconds: {
      type: "number",
      ui_component: "number",
    },
    resolution: {
      type: "string",
      enum: ["720p", "1080p"],
      ui_component: "select",
    },
  },
  native_options: {
    seed: { type: "integer", ui_component: "number" },
  },
  constraints: {
    mutually_exclusive: [],
    requires: {},
    conditional: [
      {
        when: { duration_seconds: 10 },
        require: [],
        forbid: [],
        allowed: { resolution: ["720p"] },
      },
    ],
  },
  transport_profile_id: "t1",
};

describe("uiComponentFor", () => {
  it("maps boolean to switch and enum to select", () => {
    expect(uiComponentFor({ type: "boolean" })).toBe("switch");
    expect(uiComponentFor({ type: "string", enum: ["a", "b"] })).toBe("select");
  });

  it("respects an explicit ui_component", () => {
    expect(uiComponentFor({ type: "string", ui_component: "textarea" })).toBe("textarea");
  });
});

describe("allowedValuesFor", () => {
  it("applies the duration-resolution matrix", () => {
    expect(
      allowedValuesFor(DURATION_RESOLUTION_SPEC, "resolution", { type: "string", enum: ["720p", "1080p"] }, { duration_seconds: 10 }),
    ).toEqual(["720p"]);
    expect(
      allowedValuesFor(DURATION_RESOLUTION_SPEC, "resolution", { type: "string", enum: ["720p", "1080p"] }, { duration_seconds: 5 }),
    ).toEqual(["720p", "1080p"]);
  });
});

describe("constraintViolations", () => {
  it("flags a 10s + 1080p combination", () => {
    const violations = constraintViolations(DURATION_RESOLUTION_SPEC, {
      duration_seconds: 10,
      resolution: "1080p",
    });
    expect(violations.length).toBeGreaterThan(0);
  });

  it("accepts a legal combination", () => {
    expect(
      constraintViolations(DURATION_RESOLUTION_SPEC, {
        duration_seconds: 10,
        resolution: "720p",
      }),
    ).toEqual([]);
  });

  it("flags mutually exclusive options", () => {
    const spec: CapabilitySpecRead = {
      ...DURATION_RESOLUTION_SPEC,
      constraints: {
        mutually_exclusive: [["mode_a", "mode_b"]],
        requires: {},
        conditional: [],
      },
    };
    expect(constraintViolations(spec, { mode_a: true, mode_b: true }).length).toBeGreaterThan(0);
  });
});

describe("renderableOptions", () => {
  it("splits common and native options with labels", () => {
    const { common, native } = renderableOptions(DURATION_RESOLUTION_SPEC);
    expect(common.map((o) => o.key)).toContain("resolution");
    expect(native.map((o) => o.key)).toEqual(["seed"]);
    expect(common[1].label).toBe("resolution");
  });
});
