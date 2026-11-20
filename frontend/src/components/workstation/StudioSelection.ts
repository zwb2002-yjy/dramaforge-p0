import { createContext, type MutableRefObject } from "react";
export type StudioMedia = {
  id: string;
  shotId: string;
  url: string;
  video: boolean;
  contentHash?: string | null;
  player: MutableRefObject<HTMLVideoElement | null>;
};
export const StudioSelection = createContext<{
  media: StudioMedia | null;
  show: (value: StudioMedia | null) => void;
} | null>(null);
