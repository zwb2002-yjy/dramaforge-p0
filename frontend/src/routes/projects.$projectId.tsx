import { useQuery } from "@tanstack/react-query";
import {
  Link,
  Outlet,
  createRoute,
  useNavigate,
  useRouter,
  useRouterState,
} from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { CreativeAutonomySwitcher } from "../features/project/CreativeAutonomySwitcher";
import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, fetchProject } from "../lib/api";
import { fetchSceneWorkspace } from "../features/scenes/api";
import { Button } from "../components/ui";
import { queryKeys } from "../lib/queryKeys";
import { getRememberedProjectPath, rememberProjectPath } from "../lib/navigationPreferences";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const navigate = useNavigate();
  const router = useRouter();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const view = workspaceViewFromPath(pathname);
  const atRoot = pathname.replace(/\/$/, "") === `/projects/${projectId}`;
  const workspaceState = useProjectWorkspaceState(projectId);
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: () => fetchProject(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  const rememberedPath = atRoot ? getRememberedProjectPath(projectId) : null;
  const sceneId =
    (atRoot ? rememberedPath : pathname)
      ?.split(/[?#]/)[0]
      .match(/^\/projects\/[^/]+\/scenes\/([^/]+)$/)?.[1] ?? null;
  const scene = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, sceneId),
    queryFn: () => fetchSceneWorkspace(projectId, sceneId!),
    enabled:
      Boolean(sceneId) &&
      atRoot &&
      project.isSuccess &&
      !workspaceState.isLoading &&
      !workspaceState.isFetching &&
      !workspaceState.isError,
    retry: false,
    // Root entry validates even a previously visited scene. Deep-link reads
    // remain owned by SceneWorkspace and update this shared query observer.
    staleTime: atRoot ? 0 : 30_000,
  });
  const lostScene = scene.error instanceof ApiError && scene.error.status === 404;
  const recoveryError = workspaceState.isError || (Boolean(sceneId) && scene.isError && !lostScene);

  const lastRemembered = useRef<string | null>(null);
  useEffect(() => {
    if (!view || !project.isSuccess || (sceneId && !scene.isSuccess)) return;
    rememberProjectPath(projectId, location.href);
    if (lastRemembered.current !== `${projectId}:${view}`) {
      lastRemembered.current = `${projectId}:${view}`;
      workspaceState.rememberLastView(view);
    }
  }, [view, workspaceState, projectId, location.href, project.isSuccess, sceneId, scene.isSuccess]);

  // Restore the last view with an imperative replace instead of rendering a
  // <Navigate> element, and require that the router's current pathname is still
  // the project root. During a navigation away (for example the permanent
  // Settings entry) the router reports the next route at the parent path while
  // the old view is still committing; restoring there would outrun the user's
  // own navigation and replace it.
  useEffect(() => {
    if (
      !atRoot ||
      workspaceState.isLoading ||
      workspaceState.isFetching ||
      recoveryError ||
      !project.isSuccess ||
      scene.isFetching ||
      (sceneId && !scene.isSuccess && !lostScene) ||
      router.state.location.pathname !== pathname
    )
      return;
    const restoreTarget = workspaceState.lastView ?? "script";
    void navigate({
      href: (!lostScene && rememberedPath) || `/projects/${projectId}/${restoreTarget}`,
      replace: true,
    });
  }, [
    atRoot,
    workspaceState.isLoading,
    workspaceState.isFetching,
    workspaceState.lastView,
    recoveryError,
    project.isSuccess,
    sceneId,
    scene.isSuccess,
    scene.isFetching,
    lostScene,
    rememberedPath,
    router,
    navigate,
    projectId,
    pathname,
  ]);

  const projectRead = project.data ?? undefined;
  const activeView = view ?? "overview";

  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      projectName={projectRead?.name ?? "短剧项目"}
      activeView={activeView}
      creationControls={
        projectRead?.creative_profile ? (
          <CreativeAutonomySwitcher key={projectId} project={projectRead} compact />
        ) : undefined
      }
    >
      {project.isError && (
        <div className="flash err">
          无法读取项目事实：
          {project.error instanceof Error ? project.error.message : "未知错误"}
        </div>
      )}
      {project.isError ? (
        <Link to="/" search={{}}>
          返回我的项目
        </Link>
      ) : atRoot ? (
        recoveryError ? (
          <div role="alert" className="panel">
            <p>无法读取上次位置</p>
            <Button
              onClick={() => {
                void workspaceState.retry();
                if (sceneId) void scene.refetch();
              }}
            >
              重试
            </Button>
            <Link className="df-btn ghost" to="/projects/$projectId/script" params={{ projectId }}>
              进入故事剧本
            </Link>
          </div>
        ) : (
          <p className="muted" role="status">
            正在恢复上次位置…
          </p>
        )
      ) : (
        <Outlet />
      )}
    </ProjectWorkspaceShell>
  );
}
