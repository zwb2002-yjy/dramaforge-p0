import { createRoute } from "@tanstack/react-router";

import { KnowledgePanel } from "../features/knowledge/KnowledgePanel";
import { rootRoute } from "./__root";

export const knowledgeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/knowledge",
  component: KnowledgePanel,
});
