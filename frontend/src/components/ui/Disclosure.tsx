import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

/** Collapsing hides controls without discarding in-progress drafts. */
export function Disclosure({
  title,
  description,
  children,
  testId,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <details className="df-disclosure" data-testid={testId}>
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
