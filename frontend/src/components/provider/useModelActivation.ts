import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applySimpleMode,
  createWorkspaceModelProfile,
  getWorkspaceModelProfile,
  listModels,
  listWorkspaceModelProfiles,
  updateWorkspaceModelProfile,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { WORKSPACE_MODEL_ROLES, type WorkspaceModelRole } from "../../lib/workspaceModelRoles";

/** Activation changes one role; saved connections and other roles stay intact. */
export function useModelActivation(workspaceId: string) {
  const queryClient = useQueryClient();
  const profiles = useQuery({
    queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    queryFn: () => listWorkspaceModelProfiles(workspaceId),
    retry: false,
  });
  const defaultId = profiles.data?.find((item) => item.is_default)?.id ?? null;
  const profile = useQuery({
    queryKey: queryKeys.model.workspaceProfile(workspaceId, defaultId),
    queryFn: () => getWorkspaceModelProfile(workspaceId, defaultId!),
    enabled: Boolean(defaultId),
    retry: false,
  });
  const models = useQuery({
    queryKey: queryKeys.model.catalog(workspaceId),
    queryFn: ({ signal }) => listModels(undefined, workspaceId, signal),
    retry: false,
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.model.workspaceProfiles(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: ["workspace-model-profile", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["model-bindings-effective"] }),
      queryClient.invalidateQueries({ queryKey: ["execution-model-preflight"] }),
    ]);
  };
  const ready = profiles.isSuccess && models.isSuccess && (!defaultId || profile.isSuccess);
  const isActive = (role: WorkspaceModelRole, modelId: string) => {
    const slots = WORKSPACE_MODEL_ROLES.find((item) => item.id === role)!.slots;
    return slots.every((slot) => {
      const binding = profile.data?.bindings?.[slot];
      return binding?.model_id === modelId && binding.enabled !== false;
    });
  };
  const canActivate = (role: WorkspaceModelRole, modelId: string) => {
    const capabilities = WORKSPACE_MODEL_ROLES.find((item) => item.id === role)!.capabilities;
    return (
      ready &&
      models.data?.some(
        (model) =>
          model.id === modelId &&
          model.source === "workspace" &&
          model.available &&
          capabilities.some((capability) => model.capabilities.includes(capability)),
      )
    );
  };
  const activate = useMutation({
    retry: false,
    mutationFn: async ({ role, modelId }: { role: WorkspaceModelRole; modelId: string }) => {
      if (!canActivate(role, modelId)) throw new Error("请先连接并验证该模型。");
      let target = profile.data;
      if (!defaultId)
        target = await createWorkspaceModelProfile(workspaceId, {
          name: "默认",
          bindings: {},
          is_default: true,
        });
      if (!target) throw new Error("无法读取当前模型配置。");
      const slots = WORKSPACE_MODEL_ROLES.find((item) => item.id === role)!.slots;
      // Explicit activation also enables slots previously turned off. Simple mode
      // deliberately preserves disabled slots when merely saving the same model.
      if (
        slots.some(
          (slot) =>
            target.bindings?.[slot]?.model_id === modelId &&
            target.bindings[slot].enabled === false,
        )
      ) {
        return updateWorkspaceModelProfile(workspaceId, target.id, {
          expected_version: target.version,
          bindings: {
            ...target.bindings,
            ...Object.fromEntries(
              slots.map((slot) => [
                slot,
                {
                  ...(target.bindings?.[slot]?.model_id === modelId
                    ? target.bindings[slot]
                    : { model_id: modelId, native_options: {} }),
                  enabled: true,
                },
              ]),
            ),
          },
        });
      }
      return applySimpleMode(workspaceId, target.id, {
        [`${role}_model_id`]: modelId,
        expected_version: target.version,
      });
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(queryKeys.model.workspaceProfile(workspaceId, saved.id), saved);
      await refresh();
    },
    // Creation and activation are separate existing API operations. Re-read
    // after any error so a successful create or an uncertain write is retained.
    onError: refresh,
  });
  return {
    activate,
    isActive,
    canActivate,
    ready,
    loadError: profiles.isError || models.isError || profile.isError,
  };
}
