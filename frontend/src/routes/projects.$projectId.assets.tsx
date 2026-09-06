import { createRoute } from "@tanstack/react-router";

import { LazyAssetCardsPanel } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectAssetsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/assets",
  component: AssetsPage,
});

function AssetsPage() {
  const { projectId } = projectAssetsRoute.useParams();
  return <LazyAssetCardsPanel projectId={projectId} />;
}
