import { createRoute } from "@tanstack/react-router";

import { LazyReviewWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectReviewRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/review",
  component: ReviewPage,
});

function ReviewPage() {
  const { projectId } = projectReviewRoute.useParams();
  return <LazyReviewWorkspace projectId={projectId} />;
}
