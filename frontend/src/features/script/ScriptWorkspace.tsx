import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { importScript } from "../../lib/api";
import { fetchScriptWorkspace, type ScriptWorkspaceRead } from "./api";

type ScriptWorkspaceProps = {
  projectId: string;
};

/**
 * §17.4 real Script workspace: read the ScriptDocument (raw text) + Episodes/Scenes,
 * and allow a FIRST import only. Once a ScriptDocument exists, no active
 * import/re-import/re-parse control is shown — safe script replacement /
 * reconciliation is a later Story-domain task, and re-import here could create a
 * new ScriptDocument without reconciling stale Scene/Shot rows.
 */
export function ScriptWorkspace({ projectId }: ScriptWorkspaceProps) {
  const [filename, setFilename] = useState("script.md");
  const [text, setText] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const workspace = useQuery({
    queryKey: ["script-workspace", projectId],
    queryFn: () => fetchScriptWorkspace(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const data = workspace.data as ScriptWorkspaceRead | undefined;

  const importMut = useMutation({
    mutationFn: async () => {
      setImportError(null);
      return importScript(projectId, filename.trim() || "script.md", text);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["script-workspace", projectId] });
      setText("");
    },
    onError: (error: Error) => setImportError(error.message),
  });

  if (projectId === "demo") {
    return (
      <div data-testid="project-script-page" className="qc-project-page">
        <header className="qc-page-heading">
          <p>剧本</p>
          <h1>剧本工作区</h1>
          <span>演示项目不读取真实剧本数据。</span>
        </header>
      </div>
    );
  }

  return (
    <div data-testid="project-script-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>剧本</p>
        <h1>剧本工作区</h1>
        <span>读取剧本原文与分场结构，支持首次导入。</span>
      </header>

      {workspace.isError && (
        <div className="flash err">无法读取剧本：{String(workspace.error)}</div>
      )}

      {data?.document ? (
        <>
          <section className="qc-script-document" data-testid="script-document">
            <h2>{data.document.filename}</h2>
            <code className="qc-script-raw">{data.document.raw_text}</code>
          </section>
          <section data-testid="script-episodes">
            {data.episodes.map((episode) => (
              <article key={episode.id} className="qc-script-episode">
                <h3>
                  第 {episode.episode_number} 集{episode.title ? ` · ${episode.title}` : ""}
                </h3>
                {episode.synopsis && <p className="muted">{episode.synopsis}</p>}
                <ul>
                  {episode.scenes.map((scene) => (
                    <li key={scene.id} className="qc-script-scene">
                      <strong>
                        {scene.scene_number}. {scene.location_name} · {scene.time_of_day}
                      </strong>
                      <span>{scene.shot_count} 镜头</span>
                      {scene.synopsis && <p className="muted">{scene.synopsis}</p>}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </section>
          <p className="muted qc-script-reparse-note">
            剧本替换 / 重新解析将在 Story 域结构调和实现后启用。
          </p>
        </>
      ) : (
        <section className="qc-settings-band" data-testid="script-empty">
          <h2>尚未导入剧本</h2>
          <p className="muted">导入一个 markdown 剧本后会生成 Episode / Scene / Shot 结构。</p>
          <form
            className="qc-script-import-form"
            data-testid="script-import"
            onSubmit={(event) => {
              event.preventDefault();
              importMut.mutate();
            }}
          >
            <label>
              文件名
              <input
                aria-label="剧本文件名"
                value={filename}
                onChange={(event) => setFilename(event.target.value)}
                disabled={workspace.isLoading || importMut.isPending}
              />
            </label>
            <label>
              剧本文本
              <textarea
                aria-label="剧本文本"
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={12}
                placeholder="# Episode 1 — Title&#10;Lead: Name&#10;## Scene 1 — Location / day&#10;synopsis&#10;### Shot 1 — medium&#10;Visual: ...&#10;Dialogue: ..."
                disabled={workspace.isLoading || importMut.isPending}
              />
            </label>
            <button
              type="submit"
              className="primary"
              disabled={workspace.isLoading || importMut.isPending || !text.trim()}
            >
              {importMut.isPending ? "导入中…" : "导入剧本"}
            </button>
          </form>
          {importError && (
            <div className="flash err" data-testid="script-import-error" role="alert">
              {importError}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
