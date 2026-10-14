import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

/** Collapsing hides controls without discarding in-progress drafts. */
export function Disclosure({
  title,
  description,
  children,
  testId,
  open,
  onOpenChange,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  testId?: string;
  /** Optional control; omit both to let the element manage itself. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <details
      className="df-disclosure"
      data-testid={testId}
      open={open}
      onToggle={onOpenChange ? (event) => onOpenChange(event.currentTarget.open) : undefined}
    >
      <summary>
        <span>
          <strong>{title}</strong>
          {description && <small>{description}</small>}
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </summary>
      <div className="df-disclosure-body">{children}</div>
    </details>
  );
}
