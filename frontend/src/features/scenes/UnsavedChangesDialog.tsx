import { useModalDialog } from "../../components/ui/useModalDialog";

type UnsavedChangesDialogProps = {
  title: string;
  detail: string;
  discardLabel: string;
  onReturnToSave: () => void;
  onDiscard: () => void;
};

/** Explicit save-or-discard boundary for a browser-only Shot design draft. */
export function UnsavedChangesDialog({
  title,
  detail,
  discardLabel,
  onReturnToSave,
  onDiscard,
}: UnsavedChangesDialogProps) {
  const dialogRef = useModalDialog<HTMLElement>(true, onReturnToSave);
  return (
    <div className="qc-unsaved-backdrop" data-testid="unsaved-changes-guard">
      <section
        ref={dialogRef}
        className="qc-unsaved-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="unsaved-title"
        tabIndex={-1}
      >
        <span className="director-stage-kicker">未保存的镜头设计</span>
        <h2 id="unsaved-title">{title}</h2>
        <p>{detail}</p>
        <div className="qc-unsaved-actions">
          <button type="button" className="secondary" onClick={onReturnToSave}>
            返回保存
          </button>
          <button type="button" onClick={onDiscard}>
            {discardLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
