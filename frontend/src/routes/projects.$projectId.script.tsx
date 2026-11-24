import { createRoute } from "@tanstack/react-router";

import { LazyScriptWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectScriptRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/script",
  validateSearch: (search: Record<string, unknown>) => {
    if (
      search.goalId === undefined &&
      search.planId === undefined &&
      search.goalEpoch === undefined
    )
      return {};
    if (
      typeof search.goalId !== "string" ||
      typeof search.planId !== "string" ||
      typeof search.goalEpoch !== "number" ||
      !Number.isInteger(search.goalEpoch) ||
      search.goalEpoch < 0
    )
      throw new Error("分集计划链接不完整，请从持续目标重新进入");
    return { goalId: search.goalId, planId: search.planId, goalEpoch: search.goalEpoch };
  },
  component: ScriptPage,
});

function ScriptPage() {
  const { projectId } = projectScriptRoute.useParams();
  const { goalId, planId, goalEpoch } = projectScriptRoute.useSearch();
  const navigate = projectScriptRoute.useNavigate();
  return (
    <LazyScriptWorkspace
      key={projectId}
      projectId={projectId}
      arrangementPlan={
        goalId && planId && goalEpoch !== undefined
          ? { master_run_id: goalId, plan_id: planId, control_epoch: goalEpoch }
          : undefined
      }
      onOpenScene={(sceneId) =>
        void navigate({
          to: "/projects/$projectId/scenes/$sceneId",
          params: { projectId, sceneId },
          search: { shotId: undefined, tool: undefined },
        })
      }
    />
  );
}
