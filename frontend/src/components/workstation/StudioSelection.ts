import { createContext, type MutableRefObject } from "react";
export type StudioMedia = {
  id: string;
  shotId: string;
  url: string;
  video: boolean;
  contentHash?: string | null;
  player: MutableRefObject<HTMLVideoElement | null>;
};
export type StudioFile = { revisionId: string; fragmentId: string; hash: string; label: string };
export const StudioSelection = createContext<{
  media: StudioMedia | null;
  file: StudioFile | null;
  showFile: (value: StudioFile | null) => void;
  show: (value: StudioMedia | null) => void;
} | null>(null);
