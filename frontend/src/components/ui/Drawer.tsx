import { X } from "lucide-react";
import { useId, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useModalDialog } from "./useModalDialog";

/**
 * The single drawer primitive: sliding modal from the right edge,
 * focus trap, Escape, restore focus.
 */
export function Drawer({
  open,
  onClose,
  title,
  kicker,
  children,
  actions,
  size = "default",
  testId,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  kicker?: string;
  children: ReactNode;
  actions?: ReactNode;
  size?: "default" | "wide";
  testId?: string;
}) {
  const dialogRef = useModalDialog<HTMLElement>(open, onClose);
  const titleId = useId();

  if (!open) return null;

  return createPortal(
    <div
      className="df-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className={size === "wide" ? "df-drawer wide" : "df-drawer"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid={testId}
      >
        <header className="df-drawer-header">
          <div>
            {kicker && <p className="kicker">{kicker}</p>}
            <h2 id={titleId}>{title}</h2>
          </div>
          <button type="button" className="df-drawer-close" aria-label="关闭" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="df-drawer-body">{children}</div>
        {actions && <footer className="df-drawer-actions">{actions}</footer>}
      </section>
    </div>,
    document.body,
  );
}
