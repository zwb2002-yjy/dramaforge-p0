import { Badge } from "../ui";
import { nodeRunStatusKind, nodeRunStatusLabel } from "../../lib/runLabels";

export function RunStatusBadge({ status }: { status: string }) {
  const kind = nodeRunStatusKind(status);
  const tone =
    kind === "succeeded"
      ? "success"
      : kind === "failed"
        ? "danger"
        : kind === "active"
          ? "info"
          : kind === "unknown_submission"
            ? "warning"
            : "default";
  return <Badge tone={tone}>{nodeRunStatusLabel(status)}</Badge>;
}
