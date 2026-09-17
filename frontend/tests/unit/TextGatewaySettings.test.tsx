import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TextGatewaySettings } from "../../src/components/provider/TextGatewaySettings";

describe("TextGatewaySettings", () => {
  it("explains instance configuration without a dead credential form or false readiness", () => {
    const { container } = render(<TextGatewaySettings />);
    expect(screen.getByRole("heading", { name: "文本模型 · 实例级网关配置" })).toBeInTheDocument();
    expect(screen.getByText(/LITELLM_GATEWAY_URL 与 LITELLM_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/不表示网关已配置或可用/)).toBeInTheDocument();
    expect(container.querySelector("input, form, button")).toBeNull();
    expect(screen.queryByText("已配置")).not.toBeInTheDocument();
  });
});
