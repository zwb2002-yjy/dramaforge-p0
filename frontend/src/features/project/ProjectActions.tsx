import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { Button, Dialog } from "../../components/ui";
import { deleteProject, type ProjectRead } from "../../lib/api";
import { forgetProject } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";

export function ProjectActions({
  project,
}: {
  project: Pick<ProjectRead, "id" | "name" | "version">;
}) {
  const [target, setTarget] = useState<Pick<ProjectRead, "id" | "name" | "version"> | null>(null);
  const menuRef = useRef<HTMLDetailsElement>(null);
  const queryClient = useQueryClient();
  const deletion = useMutation({
    retry: false,
    mutationFn: (confirmed: Pick<ProjectRead, "id" | "name" | "version">) =>
      deleteProject(confirmed.id, confirmed.version),
    onSuccess: async (_data, confirmed) => {
      forgetProject(confirmed.id);
      queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(confirmed.id) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.projectsRoot() });
      setTarget(null);
    },
  });
  const close = () => {
    if (!deletion.isPending) {
      setTarget(null);
      deletion.reset();
    }
  };
  return (
    <>
      <details className="df-project-menu" ref={menuRef}>
        <summary className="df-btn ghost" aria-label={`更多操作 ${project.name}`}>
          <MoreHorizontal size={18} aria-hidden="true" />
        </summary>
        <div className="df-project-menu-items">
          <Button
            tone="ghost"
            onClick={() => {
              if (menuRef.current) {
                menuRef.current.open = false;
                menuRef.current.querySelector("summary")?.focus();
              }
              setTarget({ id: project.id, name: project.name, version: project.version });
            }}
          >
            <Trash2 size={16} aria-hidden="true" />
            删除项目
          </Button>
        </div>
      </details>
      {target && (
        <Dialog
          title={`删除项目「${target.name}」？`}
          onClose={close}
          testId="project-delete-dialog"
          actions={
            <>
              <Button disabled={deletion.isPending} onClick={close}>
                取消
              </Button>
              <Button
                tone="danger"
                disabled={deletion.isPending}
                onClick={() => deletion.mutate(target)}
              >
                {deletion.isPending ? "正在删除…" : "确认删除"}
              </Button>
            </>
          }
        >
          <p>删除后，该项目将从工作台移除，无法在界面中恢复。历史生成记录会保留用于对账。</p>
          {deletion.isError && <p role="alert">{deletion.error.message}</p>}
        </Dialog>
      )}
    </>
  );
}
