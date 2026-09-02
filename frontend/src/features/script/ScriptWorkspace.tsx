import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  applyStoryProposal,
  createStoryProposal,
  fetchScriptWorkspace,
  type ScriptWorkspaceRead,
  type StoryProposalOperation,
  type StoryProposalRead,
} from "./api";

type ScriptWorkspaceProps = {
  projectId: string;
};

const COMMAND_LABELS: Record<string, string> = {
  "story.set_script_document": "剧本原文",
  "story.upsert_episode": "Episode",
  "story.upsert_scene": "Scene",
  "story.upsert_shot": "Shot",
  "story.delete_shot": "删除 Shot",
  "story.delete_scene": "删除 Scene",
  "story.delete_episode": "删除 Episode",
};

function operationLabel(operation: StoryProposalOperation): string {
  const kind = COMMAND_LABELS[operation.command] ?? operation.command;
  const numberPart = operation.key.includes(":") ? operation.key.split(":").slice(1).join(".") : "";
  return `${kind}${numberPart ? ` ${numberPart}` : ""}`;
}

export function ScriptWorkspace({ projectId }: ScriptWorkspaceProps) {
  const queryClient = useQueryClient();
  const [brief, setBrief] = useState("");
  const [filename, setFilename] = useState("story-draft.md");
  const [draftText, setDraftText] = useState("");
  const [activeProposal, setActiveProposal] = useState<StoryProposalRead | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);

  const workspace = useQuery({
    queryKey: ["script-workspace", projectId],
    queryFn: () => fetchScriptWorkspace(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const data = workspace.data as ScriptWorkspaceRead | undefined;

  const invalidateScript = () => {
    void queryClient.invalidateQueries({ queryKey: ["script-workspace", projectId] });
  };

  const createMut = useMutation({
    mutationFn: async () => {
      setFormError(null);
      setApplyMessage(null);
      return createStoryProposal(projectId, {
        idempotency_key: `story-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
        brief,
        filename: filename.trim() || "story-draft.md",
        draft_text: draftText,
      });
    },
    onSuccess: (proposal) => {
      setActiveProposal(proposal);
      setSelected(Object.fromEntries(proposal.operations.map((operation) => [operation.id, true])));
      setBrief("");
      setDraftText("");
    },
    onError: (error: Error) => setFormError(error.message),
  });

  const applyMut = useMutation({
    mutationFn: async ({
      proposalId,
      decisions,
    }: {
      proposalId: string;
      decisions: Array<{ item_id: string; decision: "accepted" | "rejected" }>;
    }) => applyStoryProposal(projectId, proposalId, decisions),
    onSuccess: (result) => {
      const accepted = result.accepted.length;
      const rejected = result.rejected.length;
      const failed = result.failed.length;
      setApplyMessage(
        `Story 更新完成：采用 ${accepted}，拒绝 ${rejected}${failed ? `，失败 ${failed}` : ""}`,
      );
      setActiveProposal(null);
      setSelected({});
      invalidateScript();
    },
    onError: (error: Error) => setApplyError(error.message),
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

  const proposalOperations = activeProposal?.operations ?? [];
  const selectedIds = proposalOperations
    .filter((operation) => selected[operation.id])
    .map((operation) => operation.id);

  function submitApply(ids: string[], decision: "accepted" | "rejected" = "accepted") {
    if (!activeProposal || ids.length === 0) return;
    setApplyError(null);
    setApplyMessage(null);
    applyMut.mutate({
      proposalId: activeProposal.id,
      decisions: ids.map((itemId) => ({ item_id: itemId, decision })),
    });
  }

  return (
    <div data-testid="project-script-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>剧本</p>
        <h1>剧本工作区</h1>
        <span>Proposal-first：先预览结构差异，再采用到 Canonical Story。</span>
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
        </>
      ) : (
        <p className="muted" data-testid="script-empty">
          当前还没有 Canonical Story。创建并采用第一个 Story 提案后，这里会显示 Episode / Scene /
          Shot 结构。
        </p>
      )}

      <section className="qc-settings-band" data-testid="story-proposal-composer">
        <h2>Story 导演提案</h2>
        <p className="muted">输入故事方向与 Markdown 草稿，生成可预览的 Canonical Story 差异。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            createMut.mutate();
          }}
        >
          <label>
            故事方向 Brief
            <textarea
              aria-label="故事方向"
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              rows={3}
              placeholder="例如：双人冲突反转短剧"
            />
          </label>
          <label>
            文件名
            <input
              aria-label="剧本文件名"
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
            />
          </label>
          <label>
            Markdown 草稿
            <textarea
              aria-label="剧本文本"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={12}
              placeholder={
                "# Episode 1 — Title\n## Scene 1 — Location / day\nsynopsis\n### Shot 1 — medium\nVisual: ...\nDialogue: ..."
              }
              disabled={createMut.isPending}
            />
          </label>
          <button
            type="submit"
            className="primary"
            data-testid="story-proposal-create"
            disabled={createMut.isPending || !draftText.trim()}
          >
            {createMut.isPending ? "生成中…" : "创建 Story 提案"}
          </button>
        </form>
        {formError && (
          <div className="flash err" role="alert">
            {formError}
          </div>
        )}
      </section>

      {activeProposal && (
        <section className="qc-settings-band" data-testid="story-proposal-preview">
          <header>
            <h3>提案差异预览</h3>
            <span className="muted">状态：{activeProposal.status}</span>
          </header>
          {proposalOperations.length === 0 ? (
            <p className="muted">草稿与当前 Canonical Story 没有差异。</p>
          ) : (
            <div className="qc-proposal-operation-list">
              {proposalOperations.map((operation) => (
                <label
                  key={operation.id}
                  className="qc-proposal-operation-row"
                  data-testid={`story-operation-${operation.action}`}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(selected[operation.id])}
                    onChange={(event) =>
                      setSelected((current) => ({
                        ...current,
                        [operation.id]: event.target.checked,
                      }))
                    }
                    aria-label={`采用 ${operationLabel(operation)}`}
                  />
                  <strong>{operationLabel(operation)}</strong>
                  <span className={`story-op-${operation.action}`}>{operation.action}</span>
                  <code>{operation.command}</code>
                  <small>{operation.rationale || operation.key}</small>
                </label>
              ))}
            </div>
          )}
          <div className="qc-proposal-actions">
            <button
              type="button"
              className="primary"
              data-testid="story-proposal-apply-selected"
              disabled={selectedIds.length === 0 || applyMut.isPending}
              onClick={() => submitApply(selectedIds, "accepted")}
            >
              {applyMut.isPending ? "采用中…" : "采用已选"}
            </button>
            <button
              type="button"
              data-testid="story-proposal-apply-all"
              disabled={proposalOperations.length === 0 || applyMut.isPending}
              onClick={() =>
                submitApply(
                  proposalOperations.map((op) => op.id),
                  "accepted",
                )
              }
            >
              全部采用
            </button>
            <button
              type="button"
              data-testid="story-proposal-reject-all"
              disabled={proposalOperations.length === 0 || applyMut.isPending}
              onClick={() =>
                submitApply(
                  proposalOperations.map((op) => op.id),
                  "rejected",
                )
              }
            >
              拒绝全部
            </button>
          </div>
        </section>
      )}

      {applyError && (
        <div className="flash err" role="alert">
          {applyError}
        </div>
      )}
      {applyMessage && (
        <div className="flash ok" role="status">
          {applyMessage}
        </div>
      )}
    </div>
  );
}
