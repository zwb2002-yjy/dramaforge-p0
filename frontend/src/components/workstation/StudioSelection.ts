import { createContext } from "react";
export type StudioMedia = { id: string; shotId: string; url: string; video: boolean };
export const StudioSelection = createContext<{
  media: StudioMedia | null;
  show: (value: StudioMedia | null) => void;
} | null>(null);
