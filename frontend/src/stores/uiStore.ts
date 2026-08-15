import { create } from "zustand";

type UiState = {
  leftNavOpen: boolean;
  selectedShotId: string | null;
  toggleLeftNav: () => void;
  setLeftNavOpen: (open: boolean) => void;
  setSelectedShotId: (id: string | null) => void;
};

export const useUiStore = create<UiState>((set) => ({
  leftNavOpen: true,
  selectedShotId: null,
  toggleLeftNav: () => set((s) => ({ leftNavOpen: !s.leftNavOpen })),
  setLeftNavOpen: (open) => set({ leftNavOpen: open }),
  setSelectedShotId: (id) => set({ selectedShotId: id }),
}));
