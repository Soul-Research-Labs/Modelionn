import { create } from "zustand";
import { persist } from "zustand/middleware";

// ── Auth store ──────────────────────────────────────────────

interface AuthState {
  hotkey: string | null;
  setHotkey: (hotkey: string | null) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      hotkey: null,
      setHotkey: (hotkey) => set({ hotkey }),
    }),
    { name: "modelionn-auth" },
  ),
);

// ── Search store ────────────────────────────────────────────

interface SearchState {
  query: string;
  artifactType: string | null;
  task: string | null;
  page: number;
  setQuery: (q: string) => void;
  setArtifactType: (t: string | null) => void;
  setTask: (t: string | null) => void;
  setPage: (p: number) => void;
  reset: () => void;
}

export const useSearchStore = create<SearchState>()((set) => ({
  query: "",
  artifactType: null,
  task: null,
  page: 1,
  setQuery: (query) => set({ query, page: 1 }),
  setArtifactType: (artifactType) => set({ artifactType, page: 1 }),
  setTask: (task) => set({ task, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ query: "", artifactType: null, task: null, page: 1 }),
}));

// ── UI preferences store ────────────────────────────────────

interface UIState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  pageSize: number;
  setPageSize: (size: number) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      pageSize: 20,
      setPageSize: (pageSize) => set({ pageSize }),
    }),
    { name: "modelionn-ui" },
  ),
);
