import { createContext, type MutableRefObject } from "react";
import type { components } from "../../shared/api/generated";
export type StudioMedia = {
  id: string;
  shotId: string;
  url: string;
  video: boolean;
  contentHash?: string | null;
  player: MutableRefObject<HTMLVideoElement | null>;
};
export type ResearchAttachment = {
  label: string;
  research_ref: { result_id: string; revision_id: string; content_hash: string };
  body: Record<string, unknown>;
  prompt: string;
};
export type StudioAttachment =
  | ResearchAttachment
  | {
      label: string;
      knowledge_ref: { reference_id: string; revision_id: string; content_hash: string };
      body: Record<string, unknown>;
      prompt: string;
    }
  | {
      label: string;
      part: components["schemas"]["FileVisionInput"] | components["schemas"]["PublicVisionInput"];
    };
export const StudioSelection = createContext<{
  media: StudioMedia | null;
  attachment: StudioAttachment | null;
  showAttachment: (value: StudioAttachment | null) => void;
  show: (value: StudioMedia | null) => void;
} | null>(null);
