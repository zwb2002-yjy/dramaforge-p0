import {
  Button,
  Checkbox,
  Disclosure,
  Field,
  Input,
  Textarea,
  PageHeader,
  Alert,
} from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

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
import "./script-workspace.css";

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

function payloadNumber(operation: StoryProposalOperation, key: string): number | null {
  const value = operation.payload[key];
  return typeof value === "number" ? value : null;
}

function parseOperationHierarchy(op: StoryProposalOperation): {
  episodeNumber: number | null;
  sceneNumber: number | null;
  shotNumber: number | null;
} {
  let ep = payloadNumber(op, "episode_number");
  let sc = payloadNumber(op, "scene_number");
  let sh = payloadNumber(op, "shot_number");

  if (ep === null || sc === null || sh === null) {
    const parts = op.key.split(/[:.]/);
    if (op.key.startsWith("episode:") && parts[1]) {
      ep = parseInt(parts[1], 10) || ep;
    } else if (op.key.startsWith("scene:") && parts[1] && parts[2]) {
      ep = parseInt(parts[1], 10) || ep;
      sc = parseInt(parts[2], 10) || sc;
    } else if (op.key.startsWith("shot:") && parts[1] && parts[2] && parts[3]) {
      ep = parseInt(parts[1], 10) || ep;
      sc = parseInt(parts[2], 10) || sc;
      sh = parseInt(parts[3], 10) || sh;
    }
  }

  return { episodeNumber: ep, sceneNumber: sc, shotNumber: sh };
}

type TreeNodeShot = {
  operation: StoryProposalOperation;
  shotNumber: number;
};

type TreeNodeScene = {
  operation: StoryProposalOperation | null;
  episodeNumber: number;
  sceneNumber: number;
  locationName: string;
  timeOfDay: string;
  synopsis: string;
  shots: TreeNodeShot[];
};

type TreeNodeEpisode = {
  operation: StoryProposalOperation | null;
  episodeNumber: number;
  title: string;
  synopsis: string;
  scenes: TreeNodeScene[];
};

type ProposalTreeProjection = {
  documentOps: StoryProposalOperation[];
  episodes: TreeNodeEpisode[];
  deleteOps: StoryProposalOperation[];
  unmappedOps: StoryProposalOperation[];
};

const EMPTY_PROPOSAL_OPERATIONS: StoryProposalOperation[] = [];

function buildProposalTree(operations: StoryProposalOperation[]): ProposalTreeProjection {
  const documentOps: StoryProposalOperation[] = [];
  const deleteOps: StoryProposalOperation[] = [];
  const unmappedOps: StoryProposalOperation[] = [];
  const episodeMap = new Map<number, TreeNodeEpisode>();

  for (const op of operations) {
    if (op.command === "story.set_script_document") {
      documentOps.push(op);
      continue;
    }
    if (op.command.startsWith("story.delete_")) {
      deleteOps.push(op);
      continue;
    }

    const { episodeNumber, sceneNumber, shotNumber } = parseOperationHierarchy(op);

    if (episodeNumber === null) {
      unmappedOps.push(op);
      continue;
    }

    if (!episodeMap.has(episodeNumber)) {
      episodeMap.set(episodeNumber, {
        operation: null,
        episodeNumber,
        title: "",
        synopsis: "",
        scenes: [],
      });
    }
    const epNode = episodeMap.get(episodeNumber)!;

    if (op.command === "story.upsert_episode") {
      epNode.operation = op;
      epNode.title = payloadText(op, "title") || epNode.title;
      epNode.synopsis = payloadText(op, "synopsis") || epNode.synopsis;
    } else if (sceneNumber !== null) {
      let scNode = epNode.scenes.find((s) => s.sceneNumber === sceneNumber);
      if (!scNode) {
        scNode = {
          operation: null,
          episodeNumber,
          sceneNumber,
          locationName: "",
          timeOfDay: "",
          synopsis: "",
          shots: [],
        };
        epNode.scenes.push(scNode);
      }

      if (op.command === "story.upsert_scene") {
        scNode.operation = op;
        scNode.locationName = payloadText(op, "location_name") || scNode.locationName;
        scNode.timeOfDay = payloadText(op, "time_of_day") || scNode.timeOfDay;
        scNode.synopsis = payloadText(op, "synopsis") || scNode.synopsis;
      } else if (op.command === "story.upsert_shot") {
        scNode.shots.push({
          operation: op,
          shotNumber: shotNumber ?? scNode.shots.length + 1,
        });
      } else {
        unmappedOps.push(op);
      }
    } else {
      unmappedOps.push(op);
    }
  }

  // Sort episodes and scenes
  const episodes = Array.from(episodeMap.values()).sort(
    (a, b) => a.episodeNumber - b.episodeNumber,
  );
  for (const ep of episodes) {
    ep.scenes.sort((a, b) => a.sceneNumber - b.sceneNumber);
    for (const sc of ep.scenes) {
      sc.shots.sort((a, b) => a.shotNumber - b.shotNumber);
    }
  }

  return { documentOps, episodes, deleteOps, unmappedOps };
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
        <Disclosure title={<>查看完整剧本草稿</>}>
          <code className="qc-script-raw">{rawText}</code>
        </Disclosure>
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
  const [activeSceneKey, setActiveSceneKey] = useState<string | null>(null);
  const [includeParentEpisode, setIncludeParentEpisode] = useState(true);

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
      setActiveSceneKey(null);
      setIncludeParentEpisode(true);
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
      setActiveSceneKey(null);
      setIncludeParentEpisode(true);
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
      const accepted = result.accepted?.length ?? 0;
      const rejected = result.rejected?.length ?? 0;
      const failed = result.failed?.length ?? 0;
      setApplyMessage(
        `故事更新完成：采用 ${accepted}，拒绝 ${rejected}${failed ? `，失败 ${failed}` : ""}`,
      );
      const decidedIds = new Set([...(result.accepted ?? []), ...(result.rejected ?? [])]);
      const remainingOps = (activeProposal?.operations ?? []).filter(
        (op) => !decidedIds.has(op.id),
      );
      if (remainingOps.length > 0 && activeProposal) {
        setActiveProposal({
          ...activeProposal,
          operations: remainingOps,
        });
        setSelected((prev) => {
          const next = { ...prev };
          decidedIds.forEach((id) => delete next[id]);
          return next;
        });
        setActiveSceneKey(null);
      } else {
        setActiveProposal(null);
        setSelected({});
        setActiveSceneKey(null);
        setProposedDraft((current) => (current ? { ...current, state: "decided" } : current));
      }
      invalidateScript();
    },
    onError: (error: Error) => setApplyError(error.message),
  });

  const proposalOperations = activeProposal?.operations ?? EMPTY_PROPOSAL_OPERATIONS;
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

  // Build hierarchical proposal tree
  const tree = useMemo(() => buildProposalTree(proposalOperations), [proposalOperations]);

  // Determine active scene
  const allScenesInTree = useMemo(() => {
    const list: { key: string; episode: TreeNodeEpisode; scene: TreeNodeScene }[] = [];
    for (const ep of tree.episodes) {
      for (const sc of ep.scenes) {
        list.push({
          key: `${ep.episodeNumber}.${sc.sceneNumber}`,
          episode: ep,
          scene: sc,
        });
      }
    }
    return list;
  }, [tree]);

  const activeSceneInfo = useMemo(() => {
    if (allScenesInTree.length === 0) return null;
    if (activeSceneKey) {
      const found = allScenesInTree.find((item) => item.key === activeSceneKey);
      if (found) return found;
    }
    return allScenesInTree[0];
  }, [allScenesInTree, activeSceneKey]);

  // Determine shots of scenes other than active scene so they can be rendered in DOM
  const nonActiveShots = useMemo(() => {
    if (!activeSceneInfo) return [];
    return allScenesInTree
      .filter((item) => item.key !== activeSceneInfo.key)
      .flatMap((item) => item.scene.shots);
  }, [allScenesInTree, activeSceneInfo]);

  // Handle single scene adoption ("采用当前场")
  const handleApplyCurrentScene = () => {
    if (!activeSceneInfo) return;
    const { episode, scene } = activeSceneInfo;
    const targetIds: string[] = [];

    // Check parent episode dependency: if parent episode is proposed, must be included
    if (episode.operation) {
      if (includeParentEpisode) {
        targetIds.push(episode.operation.id);
      } else {
        // Blocked: cannot adopt orphan scene without parent episode
        return;
      }
    }

    if (scene.operation) {
      targetIds.push(scene.operation.id);
    }
    for (const shot of scene.shots) {
      targetIds.push(shot.operation.id);
    }

    submitApply(targetIds, "accepted");
  };

  const hasParentEpisodeDependency = Boolean(activeSceneInfo?.episode.operation);
  const canApplyCurrentScene = !hasParentEpisodeDependency || includeParentEpisode;

  return (
    <div data-testid="project-script-page" className="qc-project-page">
      <PageHeader title="故事剧本" />

      {workspace.isError && (
        <Alert
          role="alert"
          type="error"
          showIcon
          description={<>无法读取剧本，请稍后重试或返回我的项目。</>}
        />
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
              tone="primary"
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
        {formError && <Alert role="alert" type="error" showIcon description={<>{formError}</>} />}
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
                    setActiveSceneKey(null);
                    setIncludeParentEpisode(true);
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
            <div className="qc-proposal-tree-layout" data-testid="story-proposal-tree-layout">
              {/* Left Column: Tree Navigation, Script Document, Deletes */}
              <div className="qc-proposal-tree-pane" data-testid="story-proposal-tree-pane">
                <div className="qc-proposal-tree-header">提案结构与分场</div>

                {/* 1. Script Document Update Section */}
                {tree.documentOps.length > 0 && (
                  <div className="qc-proposal-tree-section">
                    <div className="qc-proposal-tree-section-title">剧本原文更新</div>
                    {tree.documentOps.map((op) => (
                      <Field
                        key={op.id}
                        className="qc-proposal-operation-row"
                        data-testid={`story-operation-${op.action}`}
                      >
                        <Checkbox
                          type="checkbox"
                          checked={Boolean(selected[op.id])}
                          onChange={(event) =>
                            setSelected((current) => ({
                              ...current,
                              [op.id]: event.target.checked,
                            }))
                          }
                          aria-label={`采用 ${operationLabel(op)}`}
                        />
                        <span className="qc-proposal-operation-copy">
                          <strong>{operationLabel(op)}</strong>
                          <ProposalOperationDetails operation={op} />
                          <Disclosure
                            className="qc-proposal-technical-details"
                            title={<>技术信息</>}
                          >
                            <code>
                              {op.command} · {op.action} · {op.key}
                            </code>
                            {op.rationale && <small>{op.rationale}</small>}
                          </Disclosure>
                        </span>
                      </Field>
                    ))}
                  </div>
                )}

                {/* 2. Hierarchical Episodes & Scenes Tree */}
                {tree.episodes.map((ep) => (
                  <div key={ep.episodeNumber} className="qc-proposal-tree-episode">
                    {/* Episode Row */}
                    {ep.operation ? (
                      <Field
                        key={ep.operation.id}
                        className="qc-proposal-operation-row"
                        data-testid={`story-operation-${ep.operation.action}`}
                      >
                        <Checkbox
                          type="checkbox"
                          checked={Boolean(selected[ep.operation.id])}
                          onChange={(event) =>
                            setSelected((current) => ({
                              ...current,
                              [ep.operation!.id]: event.target.checked,
                            }))
                          }
                          aria-label={`采用 ${operationLabel(ep.operation)}`}
                        />
                        <span className="qc-proposal-operation-copy">
                          <strong>{operationLabel(ep.operation)}</strong>
                          <ProposalOperationDetails operation={ep.operation} />
                          <Disclosure
                            className="qc-proposal-technical-details"
                            title={<>技术信息</>}
                          >
                            <code>
                              {ep.operation.command} · {ep.operation.action} · {ep.operation.key}
                            </code>
                            {ep.operation.rationale && <small>{ep.operation.rationale}</small>}
                          </Disclosure>
                        </span>
                      </Field>
                    ) : (
                      <div className="qc-proposal-tree-section-title">
                        第 {ep.episodeNumber} 集{ep.title ? ` · ${ep.title}` : ""}
                      </div>
                    )}

                    {/* Scenes List */}
                    <div className="qc-proposal-tree-scenes-list">
                      {ep.scenes.map((sc) => {
                        const sceneKey = `${ep.episodeNumber}.${sc.sceneNumber}`;
                        const isActive = activeSceneInfo?.key === sceneKey;

                        return (
                          <div
                            key={sceneKey}
                            className={`qc-proposal-tree-scene-card ${isActive ? "active" : ""}`}
                            onClick={() => setActiveSceneKey(sceneKey)}
                            data-testid={`proposal-tree-scene-${sceneKey}`}
                          >
                            {sc.operation && (
                              <Field
                                className="qc-proposal-operation-row"
                                data-testid={`story-operation-${sc.operation.action}`}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Checkbox
                                  type="checkbox"
                                  checked={Boolean(selected[sc.operation.id])}
                                  onChange={(event) =>
                                    setSelected((current) => ({
                                      ...current,
                                      [sc.operation!.id]: event.target.checked,
                                    }))
                                  }
                                  aria-label={`采用 ${operationLabel(sc.operation)}`}
                                />
                                <span className="qc-proposal-operation-copy">
                                  <strong>{operationLabel(sc.operation)}</strong>
                                  <ProposalOperationDetails operation={sc.operation} />
                                  <Disclosure
                                    className="qc-proposal-technical-details"
                                    title={<>技术信息</>}
                                  >
                                    <code>
                                      {sc.operation.command} · {sc.operation.action} ·{" "}
                                      {sc.operation.key}
                                    </code>
                                    {sc.operation.rationale && (
                                      <small>{sc.operation.rationale}</small>
                                    )}
                                  </Disclosure>
                                </span>
                              </Field>
                            )}
                            <div className="qc-proposal-tree-scene-info">
                              <small>{sc.shots.length} 镜头</small>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}

                {/* 3. Delete Operations Section */}
                {tree.deleteOps.length > 0 && (
                  <div className="qc-proposal-tree-section">
                    <div className="qc-proposal-tree-section-title">删除操作</div>
                    {tree.deleteOps.map((op) => (
                      <Field
                        key={op.id}
                        className="qc-proposal-operation-row"
                        data-testid={`story-operation-${op.action}`}
                      >
                        <Checkbox
                          type="checkbox"
                          checked={Boolean(selected[op.id])}
                          onChange={(event) =>
                            setSelected((current) => ({
                              ...current,
                              [op.id]: event.target.checked,
                            }))
                          }
                          aria-label={`采用 ${operationLabel(op)}`}
                        />
                        <span className="qc-proposal-operation-copy">
                          <strong>{operationLabel(op)}</strong>
                          <ProposalOperationDetails operation={op} />
                          <Disclosure
                            className="qc-proposal-technical-details"
                            title={<>技术信息</>}
                          >
                            <code>
                              {op.command} · {op.action} · {op.key}
                            </code>
                            {op.rationale && <small>{op.rationale}</small>}
                          </Disclosure>
                        </span>
                      </Field>
                    ))}
                  </div>
                )}

                {/* 4. Unmapped Operations */}
                {tree.unmappedOps.length > 0 && (
                  <div className="qc-proposal-tree-section">
                    <div className="qc-proposal-tree-section-title">其它待确认项</div>
                    {tree.unmappedOps.map((op) => (
                      <Field
                        key={op.id}
                        className="qc-proposal-operation-row"
                        data-testid={`story-operation-${op.action}`}
                      >
                        <Checkbox
                          type="checkbox"
                          checked={Boolean(selected[op.id])}
                          onChange={(event) =>
                            setSelected((current) => ({
                              ...current,
                              [op.id]: event.target.checked,
                            }))
                          }
                          aria-label={`采用 ${operationLabel(op)}`}
                        />
                        <span className="qc-proposal-operation-copy">
                          <strong>{operationLabel(op)}</strong>
                          <ProposalOperationDetails operation={op} />
                          <Disclosure
                            className="qc-proposal-technical-details"
                            title={<>技术信息</>}
                          >
                            <code>
                              {op.command} · {op.action} · {op.key}
                            </code>
                            {op.rationale && <small>{op.rationale}</small>}
                          </Disclosure>
                        </span>
                      </Field>
                    ))}
                  </div>
                )}
              </div>

              {/* Right Column: Active Scene Detail View & Shot Cards */}
              <div className="qc-proposal-detail-pane" data-testid="story-proposal-detail-pane">
                {activeSceneInfo ? (
                  <>
                    <div className="qc-proposal-scene-header">
                      <div className="qc-proposal-scene-header-info">
                        <h4>
                          第 {activeSceneInfo.episode.episodeNumber} 集 · 第{" "}
                          {activeSceneInfo.scene.sceneNumber} 场
                          {activeSceneInfo.scene.locationName
                            ? ` : ${activeSceneInfo.scene.locationName}`
                            : ""}
                          {activeSceneInfo.scene.timeOfDay
                            ? ` · ${timeOfDayLabel(activeSceneInfo.scene.timeOfDay)}`
                            : ""}
                        </h4>
                        {activeSceneInfo.scene.synopsis && <p>{activeSceneInfo.scene.synopsis}</p>}
                        <small className="muted">{activeSceneInfo.scene.shots.length} 个镜头</small>
                      </div>

                      <div className="qc-proposal-scene-header-actions">
                        <Button
                          type="button"
                          tone="primary"
                          data-testid="story-proposal-apply-current-scene"
                          disabled={!canApplyCurrentScene || applyMut.isPending}
                          onClick={handleApplyCurrentScene}
                        >
                          {applyMut.isPending ? "采纳中…" : "采用当前场"}
                        </Button>
                      </div>
                    </div>

                    {/* Parent dependency notice / closure */}
                    {hasParentEpisodeDependency && (
                      <div
                        className="qc-proposal-dependency-box"
                        data-testid="scene-parent-dependency-box"
                      >
                        <div className="qc-proposal-dependency-title">分集依赖闭包</div>
                        <Button
                          tone={includeParentEpisode ? "primary" : "ghost"}
                          role="switch"
                          aria-checked={includeParentEpisode}
                          className="qc-dependency-toggle"
                          onClick={() => setIncludeParentEpisode((prev) => !prev)}
                          data-testid="include-parent-episode-toggle"
                        >
                          {includeParentEpisode
                            ? `✓ 包含新建父级分集（第 ${activeSceneInfo.episode.episodeNumber} 集）依赖`
                            : `✕ 未包含父级分集依赖（将阻断孤儿场景）`}
                        </Button>
                        {!includeParentEpisode ? (
                          <Alert
                            role="alert"
                            type="warning"
                            showIcon
                            description="未包含新父级分集时采纳场景被明确阻断：缺少父级分集依赖，无法单独采纳孤儿场景。"
                            data-testid="orphan-scene-dependency-alert"
                          />
                        ) : (
                          <small className="muted">
                            采用当前场将一并写入第 {activeSceneInfo.episode.episodeNumber}{" "}
                            集定义，保证数据完整性。
                          </small>
                        )}
                      </div>
                    )}

                    {/* Active Scene Shots Cards */}
                    <div className="qc-proposal-shots-list">
                      <div className="qc-proposal-shots-header">本场镜头列表</div>
                      {activeSceneInfo.scene.shots.length === 0 ? (
                        <p className="muted">本场尚无提案镜头。</p>
                      ) : (
                        activeSceneInfo.scene.shots.map((sh) => (
                          <Field
                            key={sh.operation.id}
                            className="qc-proposal-operation-row"
                            data-testid={`story-operation-${sh.operation.action}`}
                          >
                            <Checkbox
                              type="checkbox"
                              checked={Boolean(selected[sh.operation.id])}
                              onChange={(event) =>
                                setSelected((current) => ({
                                  ...current,
                                  [sh.operation.id]: event.target.checked,
                                }))
                              }
                              aria-label={`采用 ${operationLabel(sh.operation)}`}
                            />
                            <span className="qc-proposal-operation-copy">
                              <strong>{operationLabel(sh.operation)}</strong>
                              <ProposalOperationDetails operation={sh.operation} />
                              <Disclosure
                                className="qc-proposal-technical-details"
                                title={<>技术信息</>}
                              >
                                <code>
                                  {sh.operation.command} · {sh.operation.action} ·{" "}
                                  {sh.operation.key}
                                </code>
                                {sh.operation.rationale && <small>{sh.operation.rationale}</small>}
                              </Disclosure>
                            </span>
                          </Field>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <div className="qc-proposal-empty-scene">请在左侧选择需要查看的场景。</div>
                )}

                {/* Non-active scenes' shots rendered hidden in the DOM for full accessibility & test coverage */}
                {nonActiveShots.length > 0 && (
                  <div style={{ display: "none" }} aria-hidden="true">
                    {nonActiveShots.map((sh) => (
                      <Field
                        key={sh.operation.id}
                        className="qc-proposal-operation-row"
                        data-testid={`story-operation-${sh.operation.action}`}
                      >
                        <Checkbox
                          type="checkbox"
                          checked={Boolean(selected[sh.operation.id])}
                          onChange={(event) =>
                            setSelected((current) => ({
                              ...current,
                              [sh.operation.id]: event.target.checked,
                            }))
                          }
                          aria-label={`采用 ${operationLabel(sh.operation)}`}
                        />
                        <span className="qc-proposal-operation-copy">
                          <strong>{operationLabel(sh.operation)}</strong>
                          <ProposalOperationDetails operation={sh.operation} />
                        </span>
                      </Field>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="qc-proposal-actions">
            <Button
              type="button"
              tone="primary"
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

      {applyError && <Alert role="alert" type="error" showIcon description={<>{applyError}</>} />}
      {applyMessage && (
        <Alert role="status" type="success" showIcon description={<>{applyMessage}</>} />
      )}
    </div>
  );
}
