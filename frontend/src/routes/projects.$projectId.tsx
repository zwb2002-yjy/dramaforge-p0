import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, createRoute, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { CreativeAutonomySwitcher } from "../features/project/CreativeAutonomySwitcher";
import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError } from "../lib/api";
import { fetchProject } from "../features/project/api";
import { fetchSceneWorkspace } from "../features/scenes/api";
import { StudioOverview } from "../features/project/StudioOverview";
import { Alert } from "../components/ui";
import { queryKeys } from "../lib/queryKeys";
import { getRememberedProjectPath, rememberProjectPath } from "../lib/navigationPreferences";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  validateSearch: (
    search: Record<string, unknown>,
  ): { previewShot?: string; previewArtifact?: string } => ({
    ...(typeof search.previewShot === "string" && { previewShot: search.previewShot }),
    ...(typeof search.previewArtifact === "string" && { previewArtifact: search.previewArtifact }),
  }),
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const selection = projectRoute.useSearch();
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

  const projectRead = project.data ?? undefined;
  const activeView = view ?? "overview";

  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      goal={projectRead?.creative_goal}
      projectName={projectRead?.name ?? "短剧项目"}
      activeView={activeView}
      creationControls={
        projectRead?.creative_profile ? (
          <CreativeAutonomySwitcher key={projectId} project={projectRead} compact />
        ) : undefined
      }
    >
      {project.isError && (
        <Alert
          role="note"
          type="error"
          showIcon
          description={
            <>
              无法读取项目事实：
              {project.error instanceof Error ? project.error.message : "未知错误"}
            </>
          }
        />
      )}
      {project.isError ? (
        <Link to="/" search={{}}>
          返回我的项目
        </Link>
      ) : atRoot ? (
        projectRead ? (
          <StudioOverview
            key={JSON.stringify([projectId, selection.previewShot, selection.previewArtifact])}
            initialShot={selection.previewShot}
            initialArtifact={selection.previewArtifact}
            project={projectRead}
            resumePath={
              recoveryError || lostScene
                ? null
                : (rememberedPath ??
                  (workspaceState.lastView
                    ? `/projects/${projectId}/${workspaceState.lastView}`
                    : null))
            }
          />
        ) : (
          <p role="status">正在读取项目…</p>
        )
      ) : (
        <Outlet />
      )}
    </ProjectWorkspaceShell>
  );
}
