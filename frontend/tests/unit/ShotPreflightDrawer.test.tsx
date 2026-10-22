import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ShotPreflightDrawer } from "../../src/features/shots/ShotPreflightDrawer";
import type { ShotExecutionPlanRead } from "../../src/features/shots/api";

const mockPlan: ShotExecutionPlanRead = {
  plan_fingerprint: "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff",
  compiler_contract_preview: {
    compile_level: "provider_contract",
    readiness: "contract_validated",
    transport_verified: false,
    account_verified: false,
    prompt_hash: "a".repeat(64),
    semantic_hash: "b".repeat(64),
    manifest_hash: "c".repeat(64),
    reference_ids: [],
    requested_options: { duration_seconds: 4 },
    effective_options: { duration_seconds: 4 },
    wire_fingerprint: "d".repeat(64),
    redacted_wire: { model_id: "unit-video", wire_request: { duration: 4 } },
    transformations: [],
    errors: [],
    warnings: [],
  },
  plan: {
    supports_prompt_override: false,
    project_id: "00000000-0000-0000-0000-000000000001",
    shot_id: "00000000-0000-0000-0000-000000000002",
    stage: "video",
    prompt: "A cinematic wide shot of a misty harbor at dusk.",
    mode_id: "image_to_video",
    resolved_model: {
      status: "RESOLVED",
      source: "project_profile",
      capability: "video.image_to_video",
      mode_id: "image_to_video",
      resolved_model_id: "provider/mock-video-v1",
      catalog_entry_id: "00000000-0000-0000-0000-000000000003",
      provider_connection_id: "00000000-0000-0000-0000-000000000004",
      manifest_hash: "mock-hash",
    },
    capability: "video.image_to_video",
    planned_references: [
      {
        purpose: "first_frame",
        delivery: "exact",
        role: "first_frame",
        resolution_mode: "current_formal",
        mime_type: "image/png",
      },
    ],
    duration_seconds: 4,
    effective_options: {
      motion_bucket_id: 120,
      duration_seconds: 4,
    },
    capability_gaps: [],
  },
};

describe("ShotPreflightDrawer", () => {
  it("shows read-only compiler-mapped parameters without claiming wire readiness", () => {
    const compiled: ShotExecutionPlanRead = {
      ...mockPlan,
      compiler_contract_preview: {
        compile_level: "provider_contract",
        readiness: "contract_validated",
        transport_verified: false,
        account_verified: false,
        prompt_hash: "a".repeat(64),
        semantic_hash: "b".repeat(64),
        manifest_hash: "c".repeat(64),
        reference_ids: [],
        requested_options: { duration_seconds: 4 },
        effective_options: { duration_seconds: 4 },
        transformations: [],
        errors: [],
        warnings: ["PLACEHOLDER_TRANSPORT_NOT_VERIFIED"],
      },
    };
    render(
      <ShotPreflightDrawer
        open
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor"
        plan={compiled}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );
    expect(screen.getByTestId("preflight-compiler-contract-preview")).toHaveTextContent(
      "真实素材字节与临时传输令牌仍由 Worker 核验",
    );
    expect(screen.getByTestId("preflight-compiler-options")).toHaveTextContent("duration_seconds");
  });

  it("blocks confirmation if the Compiler proof is absent", () => {
    const incomplete = { ...mockPlan, compiler_contract_preview: null };
    render(
      <ShotPreflightDrawer
        open
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor"
        plan={incomplete}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );
    expect(screen.getByTestId("confirm-generate-button")).toBeDisabled();
    expect(screen.getByText("尚未生成可验证的编译请求指纹，不能提交付费生成。")).toBeInTheDocument();
  });

  it("renders prompt, parameter, and fingerprint sections when plan is loaded", () => {
    render(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={mockPlan}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("本次发送核对")).toBeInTheDocument();
    expect(screen.getByTestId("preflight-prompt-section")).toBeInTheDocument();
    expect(screen.getByTestId("preflight-parameters-section")).toBeInTheDocument();
    expect(screen.getByTestId("preflight-fingerprint-section")).toBeInTheDocument();

    expect(screen.getByText("Harbor at dusk")).toBeInTheDocument();
    expect(
      screen.getByText("A cinematic wide shot of a misty harbor at dusk."),
    ).toBeInTheDocument();
    expect(screen.getByText("provider/mock-video-v1")).toBeInTheDocument();
    expect(screen.getByText("4 秒")).toBeInTheDocument();
    expect(screen.getByTestId("preflight-plan-boundary")).toHaveTextContent(
      "尚未提供逐字段同源 Payload 预览",
    );
    expect(screen.getByText(mockPlan.plan_fingerprint)).toBeInTheDocument();

    const confirmBtn = screen.getByTestId("confirm-generate-button");
    expect(confirmBtn).not.toBeDisabled();
  });

  it("blocks video confirmation when duration or effective options are missing", () => {
    const onConfirm = vi.fn();
    const invalid = {
      ...mockPlan,
      plan: { ...mockPlan.plan, duration_seconds: 4, effective_options: { duration_seconds: 5 } },
    };
    render(
      <ShotPreflightDrawer
        open
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor"
        plan={invalid}
        isLoading={false}
        onConfirmGenerate={onConfirm}
      />,
    );
    expect(screen.getByTestId("confirm-generate-button")).toBeDisabled();
    expect(screen.getByText("生成时长与有效参数未能一致确认，请重新预检。")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-generate-button"));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("blocks a plan belonging to a different execution stage", () => {
    render(
      <ShotPreflightDrawer
        open
        onClose={vi.fn()}
        stage="image_keyframe"
        rawPrompt="Harbor"
        plan={mockPlan}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );
    expect(screen.getByTestId("confirm-generate-button")).toBeDisabled();
    expect(screen.getByText("执行阶段不一致，请重新预检。")).toBeInTheDocument();
  });

  it("blocks confirmation and offers save/recompute when draft is dirty", () => {
    const handleSaveRecompute = vi.fn();
    render(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk (edited)"
        plan={mockPlan}
        isLoading={false}
        dirty={true}
        onSaveAndRecompute={handleSaveRecompute}
        onConfirmGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("存在未保存的设计草稿")).toBeInTheDocument();
    const saveBtn = screen.getByTestId("preflight-save-recompute-btn");
    expect(saveBtn).toBeInTheDocument();
    expect(screen.queryByTestId("confirm-generate-button")).not.toBeInTheDocument();

    fireEvent.click(saveBtn);
    expect(handleSaveRecompute).toHaveBeenCalled();
  });

  it("requires explicit approximation acceptance before enabling confirm", () => {
    const planWithApproximation: ShotExecutionPlanRead = {
      ...mockPlan,
      plan: {
        ...mockPlan.plan,
        capability_gaps: [
          {
            capability: "video.image_to_video",
            severity: "warning",
            reason: "Frame rate adapted from 30fps to 24fps",
          },
        ],
      },
    };

    const handleAcceptChange = vi.fn();
    const { rerender } = render(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={planWithApproximation}
        isLoading={false}
        approximationsAccepted={false}
        onAcceptApproximationsChange={handleAcceptChange}
        onConfirmGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("检测到模型近似适配")).toBeInTheDocument();
    const confirmBtn = screen.getByTestId("confirm-generate-button");
    expect(confirmBtn).toBeDisabled();

    const checkbox = screen.getByTestId("accept-approximations-checkbox");
    fireEvent.click(checkbox);
    expect(handleAcceptChange).toHaveBeenCalledWith(true);

    // When accepted, confirm becomes enabled
    rerender(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={planWithApproximation}
        isLoading={false}
        approximationsAccepted={true}
        onAcceptApproximationsChange={handleAcceptChange}
        onConfirmGenerate={vi.fn()}
      />,
    );

    expect(screen.getByTestId("confirm-generate-button")).not.toBeDisabled();
  });

  it("strictly disables confirm when fatal capability gap exists", () => {
    const planWithFatal: ShotExecutionPlanRead = {
      ...mockPlan,
      plan: {
        ...mockPlan.plan,
        capability_gaps: [
          {
            capability: "video.image_to_video",
            severity: "fatal",
            reason: "Resolution 4K unsupported by selected model",
          },
        ],
      },
    };

    render(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={planWithFatal}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText("存在致命能力缺口，无法生成")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-generate-button")).toBeDisabled();
  });

  it("renders prompt override only when supports_prompt_override is declared in contract", () => {
    // 1. Without prompt override slot declared: should NOT render override field
    const { rerender } = render(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={{
          ...mockPlan,
          plan: {
            ...mockPlan.plan,
            supports_prompt_override: false,
            prompt_override: null,
          },
        }}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );
    expect(screen.queryByText(/提示词覆盖/)).not.toBeInTheDocument();

    // 2. With prompt override slot declared: should render override field
    rerender(
      <ShotPreflightDrawer
        open={true}
        onClose={vi.fn()}
        stage="video"
        rawPrompt="Harbor at dusk"
        plan={{
          ...mockPlan,
          plan: {
            ...mockPlan.plan,
            supports_prompt_override: true,
            prompt_override: "cinematic override prompt",
          },
        }}
        isLoading={false}
        onConfirmGenerate={vi.fn()}
      />,
    );
    expect(screen.getByText(/提示词覆盖/)).toBeInTheDocument();
    expect(screen.getByTestId("preflight-prompt-override-value")).toHaveTextContent(
      "cinematic override prompt",
    );
  });
});
