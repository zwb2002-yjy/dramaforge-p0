import { Drawer as AntDrawer, Typography } from "antd";
import type { ReactNode } from "react";

export function Drawer({
  open,
  onClose,
  title,
  kicker,
  children,
  actions,
  size = "default",
  testId,
  placement = "right",
  closeLabel = "关闭",
  className,
  inline = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  kicker?: string;
  children?: ReactNode;
  actions?: ReactNode;
  size?: "default" | "wide";
  testId?: string;
  placement?: "left" | "right";
  closeLabel?: string;
  className?: string;
  inline?: boolean;
}) {
  return (
    <AntDrawer
      open={open}
      onClose={onClose}
      getContainer={inline ? false : undefined}
      rootStyle={inline ? { position: "fixed" } : undefined}
      focusable={{ trap: true }}
      title={
        <span role="heading" aria-level={2}>
          {kicker && (
            <Typography.Text aria-hidden="true" type="secondary">
              {kicker} ·{" "}
            </Typography.Text>
          )}
          {title}
        </span>
      }
      placement={placement}
      rootClassName={className}
      size={size === "wide" ? "large" : "default"}
      footer={actions}
      destroyOnHidden={false}
      closable={{ "aria-label": closeLabel }}
      data-testid={testId}
    >
      {children}
    </AntDrawer>
  );
}
