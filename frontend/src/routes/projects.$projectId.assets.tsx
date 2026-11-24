import { createRoute } from "@tanstack/react-router";

import { LazyAssetCardsPanel, LazyPublicAssetLibrary } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectAssetsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/assets",
  validateSearch: (search: Record<string, unknown>): { kind?: string; scope?: "public" } => ({
    kind: typeof search.kind === "string" ? search.kind : undefined,
    scope: search.scope === "public" ? "public" : undefined,
  }),
  component: AssetsPage,
});

function AssetsPage() {
  const { projectId } = projectAssetsRoute.useParams();
  const { kind, scope } = projectAssetsRoute.useSearch();
  if (scope === "public") return <LazyPublicAssetLibrary key={projectId} projectId={projectId} />;
  return (
    <LazyAssetCardsPanel
      key={projectId + ":" + (kind ?? "")}
      initialKind={kind}
      projectId={projectId}
    />
  );
}
