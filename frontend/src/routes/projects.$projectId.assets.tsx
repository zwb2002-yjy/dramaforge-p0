import { createRoute } from "@tanstack/react-router";

import { AssetCardsPanel } from "../features/assets/AssetCardsPanel";
import { projectRoute } from "./projects.$projectId";

export const projectAssetsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/assets",
  component: AssetsPage,
});

function AssetsPage() {
  const { projectId } = projectAssetsRoute.useParams();
  return <AssetCardsPanel projectId={projectId} />;
}
