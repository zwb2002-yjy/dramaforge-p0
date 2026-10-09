import { X } from "lucide-react";
import { useId, type ReactNode } from "react";

import { useModalDialog } from "./useModalDialog";

/**
 * The single modal dialog primitive: focus trap, Escape, restore focus.
 * Content and actions stay owned by the feature; the shell only frames them.
 */
export function Dialog({
  title,
  kicker,
  onClose,
  children,
  actions,
  size = "default",
  testId,
}: {
  title: string;
  kicker?: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
  size?: "default" | "wide";
  testId?: string;
}) {
  const dialogRef = useModalDialog<HTMLElement>(true, onClose);
  const titleId = useId();
  return (
    <div
      className="df-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className={size === "wide" ? "df-dialog wide" : "df-dialog"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid={testId}
      >
        <header className="df-dialog-header">
          <div>
            {kicker && <p className="kicker">{kicker}</p>}
            <h2 id={titleId}>{title}</h2>
          </div>
          <button type="button" className="df-dialog-close" aria-label="关闭" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="df-dialog-body">{children}</div>
        {actions && <footer className="df-dialog-actions">{actions}</footer>}
      </section>
    </div>
  );
}
