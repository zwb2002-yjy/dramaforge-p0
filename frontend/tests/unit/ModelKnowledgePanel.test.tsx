import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelKnowledgePanel } from "../../src/components/provider/ModelKnowledgePanel";
import {
  boundLabel,
  parameterEvidence,
  parameterValue,
  protocolFactValue,
} from "../../src/components/provider/modelKnowledge";
import type { ProviderModelBindingRead } from "../../src/lib/api";
import {
  fixtureKnowledge,
  fixtureKnowledgeModel,
  fixtureKnowledgePlugin,
  unknownBound,
  fixtureParameter,
} from "../fixtures/model-knowledge";

describe("read-only model knowledge", () => {
  it("keeps unknown distinct from an explicitly supported unlimited bound", () => {
    expect(boundLabel(unknownBound)).toBe("待核实");
    expect(boundLabel(undefined)).toBe("待核实");
    expect(
      boundLabel({ kind: "unlimited", claim_status: "documented_supported", inclusive: true }),
    ).toBe("无上限（官方明确）");
  });

  it("uses effective field conflicts instead of a positive parent status", () => {
    expect(
      parameterEvidence(
        fixtureKnowledge,
        "/operations/video.generate/output_options/seed",
        "documented_supported",
      ),
    ).toBe("来源存在冲突");
  });

  it("does not promote a child whose source does not match the model scope", () => {
    const path = "/operations/video.generate/output_options/resolution";
    expect(
      parameterEvidence(
        {
          ...fixtureKnowledge,
          fields: [
            {
              path: `${path}/maximum`,
              claim_status: "documented_supported",
              source_snapshot_ref: "other-source",
              evidence_resolution: "explicit",
              blocker: "SOURCE_SCOPE_MISMATCH",
            },
          ],
        },
        path,
        "documented_supported",
      ),
    ).toBe("来源核验未通过");
  });

  it("renders custom dimensions and enum-backed fixed protocol facts", () => {
    const bound = {
      kind: "bounded",
      value: 0.4,
      claim_status: "documented_supported",
      inclusive: true,
    } as const;
    expect(
      parameterValue(
        fixtureParameter({
          enum: ["2K"],
          dimension_bounds: { min_aspect_ratio: bound, max_aspect_ratio: { ...bound, value: 2.5 } },
        }),
      ),
    ).toContain("最小宽高比 0.4；最大宽高比 2.5");
    expect(
      protocolFactValue(fixtureParameter({ enum: ["video_id"], control: "unsupported" })),
    ).toBe("video_id");
    expect(
      protocolFactValue(
        fixtureParameter({
          type: "boolean",
          claim_status: "documented_unsupported",
          default: false,
        }),
      ),
    ).toBe("否");
  });

  it("keeps ratio-only media bounds visible without a pixel-count bound", () => {
    const bound = {
      kind: "bounded",
      value: 0.4,
      claim_status: "documented_supported",
      inclusive: true,
    } as const;
    const operation = fixtureKnowledge.operations["video.generate"];
    const contract = operation.input_contracts!.reference;
    const slot = contract.input_slots!.reference_audio;
    const path = "/operations/video.generate/input_contracts/reference/input_slots/reference_image";
    render(
      <ModelKnowledgePanel
        bindings={[]}
        plugin={{
          ...fixtureKnowledgePlugin,
          models: [
            {
              ...fixtureKnowledgeModel,
              knowledge: {
                ...fixtureKnowledge,
                fields: [
                  {
                    path: `${path}/min_aspect_ratio`,
                    claim_status: "documented_supported",
                    evidence_resolution: "inherited",
                    source_snapshot_ref: "fixture-source",
                    blocker: null,
                  },
                ],
                operations: {
                  "video.generate": {
                    ...operation,
                    input_contracts: {
                      reference: {
                        ...contract,
                        input_slots: {
                          reference_image: {
                            ...slot,
                            media_types: ["image/png"],
                            min_aspect_ratio: bound,
                            max_aspect_ratio: { ...bound, value: 2.5 },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("宽高比：0.4 至 2.5")).toBeInTheDocument();
  });

  it("does not apply the old revision account result to the displayed revision", () => {
    const binding = (catalogId: string, verified: boolean): ProviderModelBindingRead => ({
      id: catalogId,
      connection_id: "connection",
      media_type: "video",
      model_id: fixtureKnowledgeModel.model_id,
      purpose: "video",
      enabled: true,
      documented: true,
      contract_tested: true,
      account_verified: verified,
      quality_gated: false,
      catalog_entry_id: catalogId,
      capability_manifest_hash: fixtureKnowledgeModel.capability_manifest_hash,
      remote_resource_kind: "model",
      remote_resource_id: fixtureKnowledgeModel.model_id,
      invoke_model_value: fixtureKnowledgeModel.model_id,
    });
    render(
      <ModelKnowledgePanel
        plugin={fixtureKnowledgePlugin}
        bindings={[
          binding("old-catalog", true),
          binding(fixtureKnowledgeModel.catalog_entry_id, false),
        ]}
      />,
    );
    expect(screen.getByText("现有绑定：账号目录尚未验证")).toBeInTheDocument();
    expect(screen.queryByText(/现有绑定：目录已验证/)).not.toBeInTheDocument();
  });

  it("shows source facts and blocked implementation without generation controls", () => {
    render(<ModelKnowledgePanel plugin={fixtureKnowledgePlugin} bindings={[]} />);
    const panel = screen.getByTestId("provider-model-knowledge");
    fireEvent.click(within(panel).getByText("模型能力说明"));
    fireEvent.click(within(panel).getByText(fixtureKnowledgeModel.model_id, { exact: true }));
    expect(
      within(panel).getByText(/候选修订未实现；产品未开放；该修订账号尚未实测/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/未知不代表无上限/)).toBeInTheDocument();
    expect(within(panel).getByText(/现有绑定：尚未绑定/)).toBeInTheDocument();
    expect(within(panel).getByText(/参考音频合计时长：最多 15 秒/)).toBeInTheDocument();
    expect(within(panel).getByText(/分辨率仅允许480p/)).toBeInTheDocument();
    expect(within(panel).getAllByText("来源存在冲突").length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(panel).queryByRole("textbox")).not.toBeInTheDocument();
    expect(panel.querySelectorAll("button, input, select, textarea")).toHaveLength(0);
  });

  it("keeps protocol contracts out of the normal model list", () => {
    const { container } = render(
      <ModelKnowledgePanel
        plugin={{
          ...fixtureKnowledgePlugin,
          models: [
            {
              ...fixtureKnowledgeModel,
              catalog_source: "protocol_contract",
              model_id: "@contract/internal",
            },
          ],
        }}
        bindings={[]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
