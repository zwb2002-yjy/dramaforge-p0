import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getProjectModelProfile, putProjectModelProfile } from "../../features/model-controls/api";
import { ApiError } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { WORKSPACE_MODEL_ROLES } from "../../lib/workspaceModelRoles";
import { Button } from "../ui";

const mediaSlots = new Set<string>(
  WORKSPACE_MODEL_ROLES.filter((role) => role.id !== "llm").flatMap((role) => [...role.slots]),
);

/** Explicitly release old project media overrides; workspace selection alone never does it. */
export function ProjectModelInheritance({
  projectId,
  workspaceId,
}: {
  projectId: string;
  workspaceId: string;
}) {
  const client = useQueryClient();
  const profile = useQuery({
    queryKey: queryKeys.model.projectProfile(projectId),
    queryFn: async () => {
      try {
        return await getProjectModelProfile(projectId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
  const inherit = useMutation({
    retry: false,
    mutationFn: () => {
      if (!profile.data || profile.data.workspace_id !== workspaceId)
        throw new Error("请重新读取项目配置。");
      return putProjectModelProfile(projectId, {
        expected_version: profile.data.version,
        bindings: Object.fromEntries(
          Object.entries(profile.data.bindings ?? {})
            .filter(([slot]) => !mediaSlots.has(slot))
            .map(([slot, binding]) => [
              slot,
              {
                model_id: binding.model_id,
                enabled: binding.enabled,
                native_options: binding.native_options,
              },
            ]),
        ),
      });
    },
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.model.projectProfile(projectId) }),
        client.invalidateQueries({ queryKey: queryKeys.model.executionPreflight(projectId) }),
        client.invalidateQueries({ queryKey: queryKeys.model.effectiveBindings(projectId) }),
        client.invalidateQueries({ queryKey: queryKeys.model.generationOptionsRoot(projectId) }),
      ]);
    },
  });
  if (profile.isError)
    return (
      <p role="alert">
        无法读取项目模型配置。<Button onClick={() => void profile.refetch()}>重试</Button>
      </p>
    );
  if (
    !profile.data ||
    profile.data.workspace_id !== workspaceId ||
    !Object.keys(profile.data.bindings ?? {}).some((slot) => mediaSlots.has(slot))
  )
    return null;
  return (
    <div className="df-settings-block" data-testid="project-model-inheritance">
      <p>
        本项目已有独立的生图 /
        视频配置，工作空间的模型选择尚不会生效。改为继承后，将使用下方选中的工作空间模型。
      </p>
      <Button disabled={inherit.isPending || profile.isFetching} onClick={() => inherit.mutate()}>
        本项目改用工作空间生图和视频模型
      </Button>
      {inherit.isError && (
        <p role="alert">
          {inherit.error instanceof Error ? inherit.error.message : "更新失败，请重新读取配置。"}
        </p>
      )}
    </div>
  );
}
