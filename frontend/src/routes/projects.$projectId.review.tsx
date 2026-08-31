import { createRoute } from "@tanstack/react-router";

import { ReviewWorkspace } from "../features/review/ReviewWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectReviewRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/review",
  component: ReviewPage,
});

function ReviewPage() {
  const { projectId } = projectReviewRoute.useParams();
  return <ReviewWorkspace projectId={projectId} />;
}
