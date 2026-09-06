import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CapabilitySpecRead, ModelRead } from "../../src/lib/api";
import {
  AdvancedModelOptions,
  DynamicCapabilityForm,
  ModelPicker,
  ReferencePurposeEditor,
} from "../../src/features/model-controls";

function mockSpec(overrides: Partial<CapabilitySpecRead> = {}): CapabilitySpecRead {
  return {
    capability: "video.image_to_video",
    input_slots: {},
    common_options: {
      duration_seconds: {
        type: "integer",
        title: "时长(秒)",
        ui_component: "slider",
        minimum: 5,
        maximum: 10,
        default: 10,
      },
      resolution: {
        type: "string",
        title: "分辨率",
        ui_component: "select",
        enum: ["720p", "1080p"],
        default: "1080p",
      },
      enhanced: { type: "boolean", title: "增强", ui_component: "switch" },
    },
    native_options: {
      seed: { type: "integer", title: "种子", ui_component: "number" },
    },
    constraints: {
      mutually_exclusive: [["enhanced", "resolution"]],
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
    ...overrides,
  };
}

describe("DynamicCapabilityForm", () => {
  it("renders manifest-driven controls (slider/select/switch) without name branching", () => {
    render(
      <DynamicCapabilityForm
        spec={mockSpec()}
        values={{ duration_seconds: 10, resolution: "1080p", enhanced: true }}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByRole("slider")).toBeTruthy();
    expect(screen.getByRole("combobox")).toBeTruthy();
    expect(screen.getByRole("checkbox")).toBeTruthy();
    expect(screen.queryByText("seedance")).toBeNull();
    expect(screen.queryByText("agnes")).toBeNull();
  });

  it("applies conditional allowed values (duration=10 -> resolution restricted)", () => {
    render(
      <DynamicCapabilityForm
        spec={mockSpec()}
        values={{ duration_seconds: 10 }}
        onChange={() => undefined}
      />,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("720p");
    expect(options).not.toContain("1080p");
  });

  it("disables an option that is mutually exclusive with a selected sibling", () => {
    render(
      <DynamicCapabilityForm
        spec={mockSpec()}
        values={{ enhanced: true }}
        onChange={() => undefined}
      />,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.disabled).toBe(true);
  });
});

describe("AdvancedModelOptions", () => {
  it("renders native options inside a collapsible section", () => {
    render(
      <AdvancedModelOptions
        options={{ seed: { type: "integer", title: "种子", ui_component: "number" } }}
        values={{ seed: 7 }}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByTestId("advanced-model-options")).toBeTruthy();
  });
});

describe("ModelPicker", () => {
  it("renders models by display name and capability, not provider names", () => {
    const models: ModelRead[] = [
      {
        id: "agnes/agnes-video-v2.0",
        provider_id: "agnes",
        display_name: "Agnes Video 2.0",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["video.image_to_video"],
      },
    ];
    render(<ModelPicker models={models} value={null} onChange={() => undefined} />);
    expect(screen.getByText("Agnes Video 2.0")).toBeTruthy();
    expect(screen.getByText(/video\.image_to_video/)).toBeTruthy();
  });
});

describe("ReferencePurposeEditor", () => {
  it("lists reference purposes from the vocabulary", () => {
    render(<ReferencePurposeEditor value="identity" onChange={() => undefined} />);
    const select = screen.getByTestId("reference-purpose-editor").querySelector("select");
    expect(select).not.toBeNull();
    expect(screen.getByText(/角色身份/)).toBeTruthy();
    expect(screen.getByText(/镜头语言/)).toBeTruthy();
  });

  it("emits the selected purpose", () => {
    let value = "identity";
    render(
      <ReferencePurposeEditor
        value={value}
        onChange={(next) => {
          value = next;
        }}
      />,
    );
    const select = screen.getByTestId("reference-purpose-editor").querySelector("select")!;
    fireEvent.change(select, { target: { value: "camera_language" } });
    expect(value).toBe("camera_language");
  });
});
