import {
  Button,
  Checkbox,
  Disclosure,
  Field,
  Input,
  Textarea,
  PageHeader,
} from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import {
  applyStoryProposal,
  createStoryProposal,
  fetchScriptWorkspace,
  generateStoryProposal,
  listStoryProposals,
  type ScriptWorkspaceRead,
  type StoryProposalOperation,
  type StoryProposalRead,
} from "./api";
import { ScriptImportPanel } from "./ScriptImportPanel";
import type { DirectorInvocationEvidence } from "../director/suggestion-types";

type ScriptWorkspaceProps = {
  projectId: string;
  /** Leave the Script workspace for one imported Scene. */
  onOpenScene?: (sceneId: string) => void;
};

const PROPOSAL_STATUS_LABEL: Record<string, string> = {
  pending: "待确认",
  applied: "已采用",
  rejected: "已拒绝",
  stale: "已过期",
};

const COMMAND_LABELS: Record<string, string> = {
  "story.set_script_document": "剧本原文",
  "story.upsert_episode": "分集",
  "story.upsert_scene": "场景",
  "story.upsert_shot": "镜头",
  "story.delete_shot": "删除镜头",
  "story.delete_scene": "删除场景",
  "story.delete_episode": "删除分集",
};

function operationLabel(operation: StoryProposalOperation): string {
  const kind = COMMAND_LABELS[operation.command] ?? operation.command;
  const numberPart = operation.key.includes(":") ? operation.key.split(":").slice(1).join(".") : "";
  return `${kind}${numberPart ? ` ${numberPart}` : ""}`;
}

type ProposedDraftSnapshot = {
  brief: string;
  filename: string;
  draftText: string;
  state: "pending" | "decided";
};

function payloadText(operation: StoryProposalOperation, key: string): string {
  const value = operation.payload[key];
  return typeof value === "string" ? value : "";
}

function proposalDraftSnapshot(proposal: StoryProposalRead): ProposedDraftSnapshot | null {
  const documentOperation = proposal.operations.find(
    (operation) => operation.command === "story.set_script_document",
  );
  if (!documentOperation) return null;
  const draftText = payloadText(documentOperation, "raw_text");
  if (!draftText) return null;
  return {
    brief: payloadText(documentOperation, "brief"),
    filename: payloadText(documentOperation, "filename") || "story-draft.md",
    draftText,
    state: "pending",
  };
}

function ProposalOperationDetails({ operation }: { operation: StoryProposalOperation }) {
  const synopsis = payloadText(operation, "synopsis");
  if (operation.command === "story.set_script_document") {
    const filename = payloadText(operation, "filename") || "story-draft.md";
    const rawText = payloadText(operation, "raw_text");
    return (
      <div className="qc-proposal-operation-details">
        <p>
          <strong>{filename}</strong> · {rawText.length.toLocaleString()} 字符 ·
          <span className="status-chip">采用后写入</span>
        </p>
        <details>
          <summary>查看完整剧本草稿</summary>
          <code className="qc-script-raw">{rawText}</code>
        </details>
      </div>
    );
  }
  if (operation.command === "story.upsert_episode") {
    return (
      <div className="qc-proposal-operation-details">
        <p>{payloadText(operation, "title") || "未命名分集"}</p>
        {synopsis && <small>{synopsis}</small>}
      </div>
    );
  }
  if (operation.command === "story.upsert_scene") {
    const timeOfDay = payloadText(operation, "time_of_day");
    return (
      <div className="qc-proposal-operation-details">
        <p>
          {payloadText(operation, "location_name") || "未命名地点"}
          {timeOfDay ? ` · ${timeOfDayLabel(timeOfDay)}` : ""}
        </p>
        {synopsis && <small>{synopsis}</small>}
      </div>
    );
  }
  if (operation.command === "story.upsert_shot") {
    const visual = payloadText(operation, "visual_description");
    const dialogue = payloadText(operation, "dialogue");
    const shotType = payloadText(operation, "shot_type");
    const cameraMove = payloadText(operation, "camera_move");
    return (
      <div className="qc-proposal-operation-details">
        {(shotType || cameraMove) && <p>{[shotType, cameraMove].filter(Boolean).join(" · ")}</p>}
        {visual && <small>画面：{visual}</small>}
        {dialogue && <small>对白：{dialogue}</small>}
      </div>
    );
  }
  return null;
}

export function ScriptWorkspace({ projectId, onOpenScene }: ScriptWorkspaceProps) {
  const queryClient = useQueryClient();
  const [brief, setBrief] = useState("");
  const [filename, setFilename] = useState("story-draft.md");
  const [draftText, setDraftText] = useState("");
  const [activeProposal, setActiveProposal] = useState<StoryProposalRead | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [generationEvidence, setGenerationEvidence] = useState<DirectorInvocationEvidence | null>(
    null,
  );
  const [proposedDraft, setProposedDraft] = useState<ProposedDraftSnapshot | null>(null);

  const workspace = useQuery({
    queryKey: queryKeys.script.workspace(projectId),
    queryFn: () => fetchScriptWorkspace(projectId),
    enabled: Boolean(projectId),
  });
  const data = workspace.data as ScriptWorkspaceRead | undefined;
  const proposals = useQuery({
    queryKey: queryKeys.script.proposals(projectId),
    queryFn: () => listStoryProposals(projectId),
    enabled: Boolean(projectId),
  });
  const pendingProposals = (Array.isArray(proposals.data) ? proposals.data : []).filter(
    (proposal) => proposal.status === "pending",
  );

  const invalidateScript = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.script.proposals(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.script.workspace(projectId) });
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
      const effectiveFilename = filename.trim() || "story-draft.md";
      void queryClient.invalidateQueries({ queryKey: queryKeys.script.proposals(projectId) });
      setActiveProposal(proposal);
      setSelected(Object.fromEntries(proposal.operations.map((operation) => [operation.id, true])));
      setFilename(effectiveFilename);
      setProposedDraft({
        brief,
        filename: effectiveFilename,
        draftText,
        state: "pending",
      });
      setGenerationEvidence(null);
    },
    onError: (error: Error) => setFormError(error.message),
  });

  const generateMut = useMutation({
    mutationFn: async () => {
      setFormError(null);
      setApplyMessage(null);
      return generateStoryProposal(projectId, {
        request_key: `story-generation:${globalThis.crypto.randomUUID()}`,
        brief: brief.trim(),
        filename: filename.trim() || "generated-story.md",
      });
    },
    onSuccess: (result) => {
      const effectiveFilename = filename.trim() || "generated-story.md";
      void queryClient.invalidateQueries({ queryKey: queryKeys.script.proposals(projectId) });
      setDraftText(result.draft_text);
      setFilename(effectiveFilename);
      setActiveProposal(result.proposal);
      setSelected(
        Object.fromEntries(result.proposal.operations.map((operation) => [operation.id, true])),
      );
      setProposedDraft({
        brief,
        filename: effectiveFilename,
        draftText: result.draft_text,
        state: "pending",
      });
      setGenerationEvidence(result.director_evidence);
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
      // The backend defaults these to empty lists; the generated contract keeps
      // them optional because they carry schema defaults.
      const accepted = result.accepted?.length ?? 0;
      const rejected = result.rejected?.length ?? 0;
      const failed = result.failed?.length ?? 0;
      setApplyMessage(
        `故事更新完成：采用 ${accepted}，拒绝 ${rejected}${failed ? `，失败 ${failed}` : ""}`,
      );
      setActiveProposal(null);
      setSelected({});
      setProposedDraft((current) => (current ? { ...current, state: "decided" } : current));
      invalidateScript();
    },
    onError: (error: Error) => setApplyError(error.message),
  });

  const proposalOperations = activeProposal?.operations ?? [];
  const normalizedFilename = filename.trim() || "story-draft.md";
  const currentDraftAlreadyProposed = Boolean(
    proposedDraft &&
    proposedDraft.brief === brief &&
    proposedDraft.filename === normalizedFilename &&
    proposedDraft.draftText === draftText,
  );
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
      <PageHeader title="故事剧本" />

      {workspace.isError && (
        <div className="flash err" role="alert">
          无法读取剧本，请稍后重试或返回项目大厅。
        </div>
      )}

      {data?.document ? (
        <>
          <Disclosure
            title={`当前正式剧本 · ${data.document.filename}`}
            description="待确认提案不会覆盖这里；只有明确采用后才会更新"
          >
            <section className="qc-script-document" data-testid="script-document">
              <h2>{data.document.filename}</h2>
              <code className="qc-script-raw">{data.document.raw_text}</code>
            </section>
          </Disclosure>
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
                        {scene.scene_number}. {scene.location_name} ·{" "}
                        {timeOfDayLabel(scene.time_of_day)}
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
          当前还没有正式剧本。创建并采用第一个剧本提案后，这里会显示集 / 场景 / 镜头结构。
        </p>
      )}

      <section className="qc-settings-band" data-testid="story-proposal-composer">
        <h2>从一个故事开始</h2>
        <p className="muted">
          描述人物、情节与预期时长。先生成建议，检查后再采用，不会直接制作视频。
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!currentDraftAlreadyProposed) createMut.mutate();
          }}
        >
          <Field>
            故事方向
            <Textarea
              aria-label="故事方向"
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              rows={3}
              placeholder="例如：双人冲突反转短剧"
              disabled={createMut.isPending || generateMut.isPending}
            />
          </Field>
          <Button
            type="button"
            tone="primary"
            data-testid="story-proposal-generate"
            disabled={generateMut.isPending || createMut.isPending || !brief.trim()}
            onClick={() => generateMut.mutate()}
          >
            {generateMut.isPending ? "模型正在写剧本提案…" : "生成剧本提案"}
          </Button>
          <Field>
            剧本文档名
            <Input
              aria-label="剧本文档名"
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
              disabled={createMut.isPending || generateMut.isPending}
            />
          </Field>
          <p className="muted">这是正式剧本记录的名称；创建或采用提案不会生成本地 .md 文件。</p>
          <Field>
            Markdown 草稿
            <Textarea
              aria-label="剧本文本"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={12}
              placeholder={
                "# 第 1 集 — 标题\n## 场景 1 — 地点 / 日间\n本场梗概\n### 镜头 1 — 中景\n画面: ...\n对白: ..."
              }
              disabled={createMut.isPending || generateMut.isPending}
            />
          </Field>
          {!currentDraftAlreadyProposed && (
            <Button
              type="submit"
              className="primary"
              data-testid="story-proposal-create"
              disabled={createMut.isPending || generateMut.isPending || !draftText.trim()}
            >
              {createMut.isPending ? "创建中…" : "创建剧本提案"}
            </Button>
          )}
        </form>
        {currentDraftAlreadyProposed && (
          <p className="muted" data-testid="story-proposal-saved-note">
            {proposedDraft?.state === "decided"
              ? "本次提案已经处理；正式内容以顶部读取结果为准。修改 Markdown 后可创建新提案。"
              : "生成成功，当前草稿已经保存为唯一提案，无需再次创建。请在下方预览并选择采用；修改 Markdown 后可创建新提案。"}
          </p>
        )}
        {generationEvidence && (
          <p className="muted" data-testid="story-generation-evidence">
            模型 {generationEvidence.actual_model ?? generationEvidence.model_id} ·
            {generationEvidence.cost_status === "reported"
              ? ` ${generationEvidence.reported_cost} ${generationEvidence.currency}`
              : " 费用未返回"}
          </p>
        )}
        {formError && (
          <div className="flash err" role="alert">
            {formError}
          </div>
        )}
      </section>

      {proposedDraft && (
        <section
          className="qc-settings-band qc-story-draft-preview"
          data-testid="story-draft-preview"
        >
          <header>
            <div>
              <h2>当前提案中的完整剧本</h2>
              <p className="muted">
                剧本文档名：{proposedDraft.filename} ·
                {proposedDraft.state === "pending" ? " 尚未写入正式剧本" : " 本次提案已处理"}
              </p>
            </div>
          </header>
          <code className="qc-script-raw">{proposedDraft.draftText}</code>
        </section>
      )}

      <Disclosure title="导入已有剧本" description="支持文本文件或粘贴结构化剧本">
        <ScriptImportPanel
          projectId={projectId}
          onImported={async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: queryKeys.script.workspace(projectId) }),
              queryClient.invalidateQueries({ queryKey: queryKeys.scene.summaries(projectId) }),
            ]);
          }}
          onOpenFirstShot={() => {
            // The refreshed Script tree is the reliable way to locate the imported
            // Shot: the first Scene of the first Episode owns the first Shot.
            const firstScene = data?.episodes[0]?.scenes[0];
            if (firstScene) onOpenScene?.(firstScene.id);
          }}
        />
      </Disclosure>

      {pendingProposals.length > 0 && (
        <Disclosure
          title="继续处理已保存的提案"
          description="刷新或离开页面后，提案仍保留；不会再次调用模型"
        >
          <ul>
            {pendingProposals.map((proposal) => (
              <li key={proposal.id}>
                <span>
                  {new Date(proposal.created_at).toLocaleString()} · {proposal.operations.length}{" "}
                  项待确认
                </span>
                <Button
                  onClick={() => {
                    const snapshot = proposalDraftSnapshot(proposal);
                    setActiveProposal(proposal);
                    setSelected(
                      Object.fromEntries(
                        proposal.operations.map((operation) => [operation.id, true]),
                      ),
                    );
                    if (snapshot) {
                      setBrief(snapshot.brief);
                      setFilename(snapshot.filename);
                      setDraftText(snapshot.draftText);
                      setProposedDraft(snapshot);
                    }
                    setGenerationEvidence(null);
                  }}
                >
                  查看并确认提案
                </Button>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {proposals.isError && (
        <p role="alert">
          已保存提案读取失败。<Button onClick={() => void proposals.refetch()}>重新读取提案</Button>
        </p>
      )}
      {activeProposal && (
        <section className="qc-settings-band" data-testid="story-proposal-preview">
          <header>
            <h3>提案预览</h3>
            <span className="muted">
              状态：{PROPOSAL_STATUS_LABEL[activeProposal.status] ?? activeProposal.status}
            </span>
          </header>
          <p className="muted qc-proposal-gate-note">
            以下内容目前只保存在提案中，不是正式剧本。文件名和勾选内容只有在点击采用后才写入正式剧本记录。
          </p>
          {proposalOperations.length === 0 ? (
            <p className="muted">
              此提案未返回可确认内容。请重新读取已保存提案，不要重复调用模型。
            </p>
          ) : (
            <div className="qc-proposal-operation-list">
              {proposalOperations.map((operation) => (
                <Field
                  key={operation.id}
                  className="qc-proposal-operation-row"
                  data-testid={`story-operation-${operation.action}`}
                >
                  <Checkbox
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
                  <span className="qc-proposal-operation-copy">
                    <strong>{operationLabel(operation)}</strong>
                    <ProposalOperationDetails operation={operation} />
                    <details className="qc-proposal-technical-details">
                      <summary>技术信息</summary>
                      <code>
                        {operation.command} · {operation.action} · {operation.key}
                      </code>
                      {operation.rationale && <small>{operation.rationale}</small>}
                    </details>
                  </span>
                </Field>
              ))}
            </div>
          )}
          <div className="qc-proposal-actions">
            <Button
              type="button"
              className="primary"
              data-testid="story-proposal-apply-selected"
              disabled={selectedIds.length === 0 || applyMut.isPending}
              onClick={() => submitApply(selectedIds, "accepted")}
            >
              {applyMut.isPending ? "采用中…" : "采用已选"}
            </Button>
            <Button
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
            </Button>
            <Button
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
            </Button>
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
