import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { updateProjectCreativeProfile, type ProjectRead } from "../../lib/api";

export type CreativeAutonomy = "AUTO" | "ASSIST" | "MANUAL";

type CreativeAutonomySwitcherProps = {
  project: ProjectRead;
};

const AUTONOMY_OPTIONS: Array<{ value: CreativeAutonomy; label: string; hint: string }> = [
  { value: "AUTO", label: "导演自动", hint: "主动分析并给出完整导演建议" },
  { value: "ASSIST", label: "导演辅助", hint: "主动提示，但关键决定由你确认" },
  { value: "MANUAL", label: "手动控制", hint: "只在请求时提供导演建议" },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Project-level DirectorAutonomy switch.
 *
 * The switch only changes the Director behavior policy on the project's
 * canonical CreativeProfile. It never migrates the Project, copies
 * Scene/Shot facts, or changes the execution/Runtime identity.
 */
export function CreativeAutonomySwitcher({ project }: CreativeAutonomySwitcherProps) {
  const queryClient = useQueryClient();
  const profile = project.creative_profile;
  const [message, setMessage] = useState<string | null>(null);

  const update = useMutation({
    mutationFn: (next: CreativeAutonomy) =>
      updateProjectCreativeProfile(project.id, profile.version, next),
    onMutate: () => setMessage(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<ProjectRead>(["project", project.id], (current) =>
        current ? { ...current, creative_profile: updated } : current,
      );
      setMessage(
        `导演参与度已切换为 ${updated.director_autonomy}（Profile v${updated.version}）。`,
      );
    },
    onError: (error: unknown) => {
      setMessage(`切换失败：${errorMessage(error)}`);
    },
  });

  const current = profile.director_autonomy as CreativeAutonomy;
  const selected = AUTONOMY_OPTIONS.find((option) => option.value === current);

  return (
    <section
      className="qc-settings-band creative-autonomy-switcher"
      data-testid="creative-autonomy-switcher"
      data-project-id={project.id}
      data-autonomy={current}
      data-profile-version={profile.version}
    >
      <header>
        <p className="director-stage-kicker">导演参与度</p>
        <h3>项目级 DirectorAutonomy</h3>
        <p className="muted">
          只改变导演行为策略与建议密度；不会迁移项目，也不改变 Scene/Shot 或 Runtime 执行身份。
        </p>
      </header>
      <div className="creative-autonomy-controls">
        <label>
          当前策略
          <select
            data-testid="creative-autonomy-select"
            aria-label="导演参与度"
            value={current}
            disabled={update.isPending}
            onChange={(event) => update.mutate(event.target.value as CreativeAutonomy)}
          >
            {AUTONOMY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <p className="creative-autonomy-hint" data-testid="creative-autonomy-hint">
          {selected ? `${selected.label}：${selected.hint}` : current}
        </p>
        {update.isPending && (
          <p className="muted" role="status">
            正在切换…
          </p>
        )}
        {message && (
          <p
            className={message.includes("失败") ? "flash err" : "flash ok"}
            data-testid="creative-autonomy-message"
            role={message.includes("失败") ? "alert" : "status"}
          >
            {message}
          </p>
        )}
      </div>
    </section>
  );
}
