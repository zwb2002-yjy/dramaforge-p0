import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Button } from "../../components/ui";
import { getWorkspaceModelProfile, listModels, listWorkspaceModelProfiles } from "../../lib/api";
import { validateSettingsReturnTo } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import { WORKSPACE_MODEL_ROLES } from "../../lib/workspaceModelRoles";

/** Availability and saved bindings only; never probes or saves a provider. */
export function WorkspaceModelNotice({
  workspaceId,
  returnTo,
}: {
  workspaceId: string;
  returnTo: string;
}) {
  const models = useQuery({
    queryKey: queryKeys.model.catalog(workspaceId),
    queryFn: ({ signal }) => listModels(undefined, workspaceId, signal),
    retry: false,
  });
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
  const failed = models.isError || profiles.isError || (Boolean(defaultId) && profile.isError);
  const ready = models.isSuccess && profiles.isSuccess && (!defaultId || profile.isSuccess);
  const missing: string[] = [];
  const unbound: string[] = [];
  if (ready) {
    for (const role of WORKSPACE_MODEL_ROLES) {
      const available = (models.data ?? []).filter(
        (model) =>
          model.source === "workspace" &&
          model.available &&
          role.capabilities.some((capability) => model.capabilities.includes(capability)),
      );
      if (!available.length) {
        missing.push(role.label.replace("模型", ""));
      } else if (
        role.slots.some((slot) => {
          const binding = profile.data?.bindings?.[slot];
          return !binding?.model_id || binding.enabled === false;
        })
      ) {
        unbound.push(role.label.replace("模型", ""));
      } else if (
        role.slots.some(
          (slot) =>
            !available.some((model) => model.id === profile.data?.bindings?.[slot]?.model_id),
        )
      ) {
        missing.push(role.label.replace("模型", ""));
      }
    }
    if (!failed && !missing.length && !unbound.length) return null;
  }
  return (
    <section
      className="df-model-notice"
      aria-label="模型配置提示"
      data-testid="workspace-model-notice"
    >
      <div role={failed ? "alert" : "status"}>
        {failed ? (
          "无法读取模型配置"
        ) : !ready ? (
          "正在读取模型配置…"
        ) : (
          <>
            {missing.length > 0 && <span>缺少可用的{missing.join("／")}模型</span>}
            {unbound.length > 0 && <span>尚未配置默认模型（{unbound.join("／")}）</span>}
          </>
        )}
      </div>
      {failed && (
        <Button
          onClick={() => {
            void models.refetch();
            void profiles.refetch();
            if (defaultId) void profile.refetch();
          }}
        >
          重试
        </Button>
      )}
      <Link
        className="df-btn ghost"
        to="/settings/models"
        search={{
          returnTo: validateSettingsReturnTo(returnTo),
        }}
      >
        配置模型
      </Link>
    </section>
  );
}
