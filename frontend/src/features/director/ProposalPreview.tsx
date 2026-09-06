/**
 * ProposalPreview (P7-06 / 03 §66).
 *
 * Renders every proposal item with per-item accept/reject (P7-07).
 */

import { ProposalItem, type ProposalItemData } from "./ProposalItem";

export type { ProposalItemData };

export interface ProposalPreviewProps {
  items: ProposalItemData[];
  onAccept?: (id: string) => void;
  onReject?: (id: string) => void;
}

export function ProposalPreview({ items, onAccept, onReject }: ProposalPreviewProps) {
  return (
    <div data-testid="proposal-preview" className="space-y-2">
      <h4 className="text-sm font-medium">导演建议</h4>
      {items.map((item) => (
        <ProposalItem key={item.id} item={item} onAccept={onAccept} onReject={onReject} />
      ))}
    </div>
  );
}
