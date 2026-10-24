import { createRoute } from "@tanstack/react-router";

import { reviewTargetSearch } from "../features/review/reviewTarget";
import { LazyReviewWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectReviewRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/review",
  component: ReviewPage,
  validateSearch: reviewTargetSearch,
});

function ReviewPage() {
  const { projectId } = projectReviewRoute.useParams();
  const targetSearch = projectReviewRoute.useSearch();
  return <LazyReviewWorkspace projectId={projectId} targetSearch={targetSearch} />;
}
