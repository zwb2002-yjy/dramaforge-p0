import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useSyncExternalStore } from "react";

import { ProductionFactsSse } from "./components/sse/ProductionFactsSse";
import { getSelectedWorkspaceId, subscribeSelectedWorkspaceId } from "./lib/navigationPreferences";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
    // Explicit writes fail in the context where the user requested them.
    // Reconnecting must not flush a paused Save/Formal/Generate/Export command.
    mutations: {
      networkMode: "always",
      retry: false,
    },
  },
});

function LiveProductionFacts() {
  const workspaceId = useSyncExternalStore(
    subscribeSelectedWorkspaceId,
    getSelectedWorkspaceId,
    () => null,
  );
  return <ProductionFactsSse workspaceId={workspaceId} />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LiveProductionFacts />
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
