/**
 * ProposalItem (P7-06 / 03 §66).
 *
 * One proposal item showing 建议/原因/收益/创作代价/风险/影响范围 with
 * accept/reject controls (P7-07 partial apply).
 */

export interface ProposalItemData {
  id: string;
  command: string;
  suggestion: string;
  rationale: string;
  benefit: string;
  cost: string;
  risk: string;
  impact: string;
  status: "pending" | "accepted" | "rejected";
}

export interface ProposalItemProps {
  item: ProposalItemData;
  onAccept?: (id: string) => void;
  onReject?: (id: string) => void;
}

export function ProposalItem({ item, onAccept, onReject }: ProposalItemProps) {
  return (
    <div data-testid={`proposal-item-${item.id}`} className="rounded border p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="font-medium">{item.suggestion}</span>
          <span className="ml-2 font-mono text-xs text-gray-500">{item.command}</span>
        </div>
        <span
          className={
            item.status === "accepted"
              ? "text-green-600"
              : item.status === "rejected"
                ? "text-red-600"
                : "text-amber-600"
          }
        >
          {item.status}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-1 text-xs">
        <div><dt className="text-gray-500">原因</dt><dd>{item.rationale || "—"}</dd></div>
        <div><dt className="text-gray-500">收益</dt><dd>{item.benefit || "—"}</dd></div>
        <div><dt className="text-gray-500">创作代价</dt><dd>{item.cost || "—"}</dd></div>
        <div><dt className="text-gray-500">风险</dt><dd>{item.risk || "—"}</dd></div>
        <div><dt className="text-gray-500">影响范围</dt><dd>{item.impact || "—"}</dd></div>
      </dl>
      {item.status === "pending" && (
        <div className="mt-2 flex gap-2">
          <button type="button" className="rounded bg-green-600 px-2 py-1 text-xs text-white"
                  onClick={() => onAccept?.(item.id)}>接受</button>
          <button type="button" className="rounded bg-red-600 px-2 py-1 text-xs text-white"
                  onClick={() => onReject?.(item.id)}>拒绝</button>
        </div>
      )}
    </div>
  );
}
