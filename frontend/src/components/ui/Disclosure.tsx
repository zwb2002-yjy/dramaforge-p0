import { Collapse, Typography } from "antd";
import { ChevronRight } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

export function Disclosure({
  title,
  description,
  children,
  testId,
  open,
  onOpenChange,
  compact = false,
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, "title" | "onChange"> & {
  title: ReactNode;
  description?: string;
  children: ReactNode;
  testId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  compact?: boolean;
}) {
  return (
    <Collapse
      data-testid={testId}
      {...props}
      ghost={compact}
      destroyOnHidden={false}
      expandIcon={({ isActive }) => (
        <ChevronRight
          aria-hidden="true"
          size={16}
          style={{ transform: isActive ? "rotate(90deg)" : undefined }}
        />
      )}
      activeKey={open === undefined ? undefined : open ? ["content"] : []}
      onChange={(keys) => onOpenChange?.(keys.includes("content"))}
      items={[
        {
          key: "content",
          forceRender: true,
          label: (
            <>
              <Typography.Text strong>{title}</Typography.Text>
              {description && <Typography.Text type="secondary"> · {description}</Typography.Text>}
            </>
          ),
          children: <div className="df-disclosure-content">{children}</div>,
        },
      ]}
    />
  );
}
