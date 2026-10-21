import { Modal, Typography } from "antd";
import type { ReactNode } from "react";

export function Dialog({
  open,
  title,
  kicker,
  onClose,
  children,
  actions,
  size = "default",
  testId,
  afterClose,
}: {
  open: boolean;
  title: string;
  kicker?: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
  size?: "default" | "wide";
  testId?: string;
  afterClose?: () => void;
}) {
  return (
    <Modal
      open={open}
      destroyOnHidden
      afterClose={afterClose}
      centered
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
      onCancel={onClose}
      footer={actions ?? null}
      width={
        size === "wide" ? "var(--df-dialog-wide-width, 64rem)" : "var(--df-dialog-width, 38rem)"
      }
      closable={{ "aria-label": "关闭" }}
      modalRender={(node) => <div data-testid={testId}>{node}</div>}
    >
      {children}
    </Modal>
  );
}
