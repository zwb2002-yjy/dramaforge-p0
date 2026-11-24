import { Button, Dialog } from "../../components/ui";
import { useState } from "react";

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
  const [decision, setDecision] = useState<"save" | "discard" | null>(null);
  return (
    <Dialog
      open={decision === null}
      afterClose={() => (decision === "discard" ? onDiscard() : onReturnToSave())}
      title={title}
      kicker="未保存的镜头设计"
      testId="unsaved-changes-guard"
      onClose={() => setDecision("save")}
      actions={
        <>
          <Button type="button" onClick={() => setDecision("save")}>
            返回保存
          </Button>
          <Button type="button" onClick={() => setDecision("discard")}>
            {discardLabel}
          </Button>
        </>
      }
    >
      <p>{detail}</p>
    </Dialog>
  );
}
