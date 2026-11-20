import { createRoute } from "@tanstack/react-router";

import { LazyAssetCardsPanel } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectAssetsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/assets",
  validateSearch: (search: Record<string, unknown>): { kind?: string } => ({
    kind: typeof search.kind === "string" ? search.kind : undefined,
  }),
  component: AssetsPage,
});

function AssetsPage() {
  const { projectId } = projectAssetsRoute.useParams();
  const { kind } = projectAssetsRoute.useSearch();
  return (
    <LazyAssetCardsPanel
      key={projectId + ":" + (kind ?? "")}
      initialKind={kind}
      projectId={projectId}
    />
  );
}
