/**
 * Manifest-driven model option rendering (V3 spec §59) — pure helpers.
 * No model/provider-name branching anywhere.
 */

import { describe, expect, it } from "vitest";
import type { CapabilitySpecRead, ParameterSpecRead } from "../../src/features/model-controls/api";
import { allowedValuesFor, uiComponentFor } from "../../src/lib/manifestOptions";

function parameter(
  value: Omit<ParameterSpecRead, "required" | "deprecated" | "sensitive">,
): ParameterSpecRead {
  return { required: false, deprecated: false, sensitive: false, ...value };
}

const DURATION_RESOLUTION_SPEC: CapabilitySpecRead = {
  capability: "video.image_to_video",
  minimum_total_references: 0,
  auto_match_contract: false,
  input_slots: {},
  common_options: {
    duration_seconds: parameter({
      type: "number",
      ui_component: "number",
    }),
    resolution: parameter({
      type: "string",
      enum: ["720p", "1080p"],
      ui_component: "select",
    }),
  },
  native_options: {
    seed: parameter({ type: "integer", ui_component: "number" }),
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
    expect(uiComponentFor(parameter({ type: "boolean" }))).toBe("switch");
    expect(uiComponentFor(parameter({ type: "string", enum: ["a", "b"] }))).toBe("select");
  });

  it("respects an explicit ui_component", () => {
    expect(uiComponentFor(parameter({ type: "string", ui_component: "textarea" }))).toBe(
      "textarea",
    );
  });
});

describe("allowedValuesFor", () => {
  it("applies the duration-resolution matrix", () => {
    expect(
      allowedValuesFor(
        DURATION_RESOLUTION_SPEC,
        "resolution",
        parameter({ type: "string", enum: ["720p", "1080p"] }),
        { duration_seconds: 10 },
      ),
    ).toEqual(["720p"]);
    expect(
      allowedValuesFor(
        DURATION_RESOLUTION_SPEC,
        "resolution",
        parameter({ type: "string", enum: ["720p", "1080p"] }),
        { duration_seconds: 5 },
      ),
    ).toEqual(["720p", "1080p"]);
  });
});
