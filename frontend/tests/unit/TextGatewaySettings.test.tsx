import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TextGatewaySettings } from "../../src/components/provider/TextGatewaySettings";

describe("TextGatewaySettings", () => {
  it("explains instance configuration without a dead credential form or false readiness", () => {
    const { container } = render(<TextGatewaySettings />);
    expect(screen.getByRole("heading", { name: "文本服务" })).toBeInTheDocument();
    expect(screen.getByText(/LITELLM_GATEWAY_URL 与 LITELLM_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/不检测连接状态/)).toBeInTheDocument();
    expect(container.querySelector("input, form, button")).toBeNull();
    expect(screen.queryByText("已配置")).not.toBeInTheDocument();
  });
});
