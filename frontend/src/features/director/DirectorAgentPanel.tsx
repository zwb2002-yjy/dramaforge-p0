import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Disclosure,
  Field,
  RecordItem,
  RecordList,
  SectionHeader,
  Textarea,
} from "../../components/ui";
import { ApiError } from "../../lib/api";
import {
  getSelectedWorkspaceId,
  subscribeSelectedWorkspaceId,
} from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import { fetchCurrentUser, type UserRead } from "../access/api";
import type { ShotLite } from "../shots/api";
import {
  applyDirectorAgentProposal,
  getDirectorAgentProposal,
  getDirectorAgentRequest,
  listDirectorAgentActivity,
  listDirectorTurns,
  openDirectorAgentThread,
  readDirectorAgentThread,
  sendDirectorAgentMessage,
  stopDirectorAgentTurn,
  type AgentTurnResult,
} from "./api";
import { agentErrorMessage, agentProposalResultLabel, agentStatusLabel } from "./agentPanelLabels";
import {
  agentPanelStorageKey,
  readAgentPanelRecovery,
  settleAgentPanelRecovery,
  writeAgentPanelRecovery,
  type AgentPanelRecovery,
} from "./agentPanelStorage";

type Props = {
  projectId: string;
  shot: ShotLite;
  dirty: boolean;
  onApplied: () => void;
  visible?: boolean;
};

const ACTIVE = new Set(["queued", "thinking", "awaiting_user", "awaiting_execution"]);
const TERMINAL = new Set(["completed", "failed", "cancelled", "stale"]);
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : typeof error === "string"
      ? error
      : "操作未完成，请核对状态。";
const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
const ids = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];

function subscribeVisibility(listener: () => void) {
  document.addEventListener("visibilitychange", listener);
  return () => document.removeEventListener("visibilitychange", listener);
}

export function DirectorAgentPanel(props: Props) {
  const user = useQuery({
    queryKey: queryKeys.auth.currentUser(),
    queryFn: fetchCurrentUser,
    enabled: props.visible !== false,
    staleTime: 0,
    refetchOnMount: "always",
    retry: false,
  });
  const workspaceId = useSyncExternalStore(subscribeSelectedWorkspaceId, getSelectedWorkspaceId);
  if (!user.isFetchedAfterMount || user.isFetching || user.isError || !user.data || !workspaceId)
    return (
      <p role="status">
        {user.isError ? "身份读取失败，请重新登录后恢复协作。" : "正在确认协作身份与工作空间…"}
      </p>
    );
  return (
    <AgentPanelScope
      key={`${user.data.id}:${workspaceId}:${props.projectId}:${props.shot.id}`}
      {...props}
      userId={user.data.id}
      workspaceId={workspaceId}
    />
  );
}

function AgentPanelScope({
  projectId,
  shot,
  dirty,
  onApplied,
  visible = true,
  userId,
  workspaceId,
}: Props & { userId: string; workspaceId: string }) {
  const client = useQueryClient();
  const mounted = useRef(true);
  const latestDirty = useRef(dirty);
  latestDirty.current = dirty;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const key = agentPanelStorageKey(userId, workspaceId, projectId, shot.id);
  const [recovery, setRecovery] = useState(() => readAgentPanelRecovery(key));
  const [lastRequest, setLastRequest] = useState(recovery.pending);
  const [openedThreadId, setOpenedThreadId] = useState<string | null>(null);
  const [offset, setOffset] = useState<number | undefined>();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [activityOffset, setActivityOffset] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const pageVisible = useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState !== "hidden",
  );
  const enabled = visible && pageVisible;
  const base = useMemo(
    () => [...queryKeys.director.turns(projectId, "shot", shot.id), userId, workspaceId, "agent"],
    [projectId, shot.id, userId, workspaceId],
  );
  const receiptKey = [...base, "receipt", lastRequest?.threadId, lastRequest?.requestKey];
  const current = () =>
    mounted.current &&
    getSelectedWorkspaceId() === workspaceId &&
    client.getQueryData<UserRead>(queryKeys.auth.currentUser())?.id === userId &&
    client.getQueryState(queryKeys.auth.currentUser())?.fetchStatus === "idle";
  const saveRecovery = (value: AgentPanelRecovery) => {
    const stored = writeAgentPanelRecovery(key, value);
    setRecovery(value);
    if (!stored) setError("浏览器无法保存恢复记录，请启用存储后再发送。");
    return stored;
  };
  const turns = useQuery({
    queryKey: [...base, "turns"],
    queryFn: ({ signal }) => listDirectorTurns(projectId, "shot", shot.id, 10, signal),
    enabled,
    retry: false,
    refetchInterval: (query) =>
      enabled &&
      (recovery.pending ||
        query.state.data?.some((turn) => turn.turn_kind === "agent" && ACTIVE.has(turn.status)))
        ? 3000
        : false,
  });
  const agentTurns = (turns.data ?? []).filter(
    (turn) => turn.turn_kind === "agent" && turn.thread_id,
  );
  const latest = agentTurns[0];
  const selected = lastRequest
    ? agentTurns.find((turn) => turn.request_key === lastRequest.requestKey)
    : latest;
  const threadId = lastRequest?.threadId ?? latest?.thread_id ?? openedThreadId;
  const receipt = useQuery({
    queryKey: receiptKey,
    queryFn: ({ signal }) =>
      getDirectorAgentRequest(projectId, lastRequest!.threadId, lastRequest!.requestKey, signal),
    enabled: enabled && Boolean(lastRequest),
    retry: false,
    refetchInterval: (query) =>
      enabled && recovery.pending && (!query.state.data || !TERMINAL.has(query.state.data.status))
        ? 3000
        : false,
  });
  const thread = useQuery({
    queryKey: [...base, "thread", threadId, offset ?? "latest"],
    queryFn: ({ signal }) => readDirectorAgentThread(projectId, threadId!, offset, signal),
    enabled: enabled && Boolean(threadId),
    retry: false,
  });
  const threadVerified =
    !thread.isError &&
    (thread.data
      ? thread.data.id === threadId &&
        thread.data.scope_type === "shot" &&
        thread.data.scope_entity_id === shot.id
      : openedThreadId !== null && openedThreadId === threadId);
  const receiptMismatch = Boolean(receipt.data && receipt.data.thread_id !== threadId);
  const scopeVerified = threadVerified && !receiptMismatch;
  const scopedReceipt = scopeVerified ? receipt.data : undefined;
  const scopedTurn = scopeVerified && selected?.thread_id === threadId ? selected : undefined;
  const status = scopedReceipt?.status ?? scopedTurn?.status;
  const turnId = scopedReceipt?.turn_id ?? scopedTurn?.id;
  const revision = scopedReceipt?.version ?? scopedTurn?.revision;
  const submissionUnknown =
    scopedReceipt?.transport_status === "unknown_submission" ||
    scopedReceipt?.stop_reason === "unknown_submission";
  const active = Boolean(status && ACTIVE.has(status));
  const activity = useQuery({
    queryKey: [...base, "activity", turnId, activityOffset],
    queryFn: ({ signal }) => listDirectorAgentActivity(projectId, turnId!, activityOffset, signal),
    enabled: enabled && scopeVerified && toolsOpen && Boolean(turnId),
    retry: false,
    refetchInterval: enabled && toolsOpen && active ? 3000 : false,
  });
  const proposalIds = scopeVerified
    ? [
        ...new Set([
          ...ids(scopedReceipt?.proposal_ids),
          ...agentTurns
            .filter((turn) => turn.thread_id === threadId)
            .flatMap((turn) => ids(turn.output_snapshot.proposal_ids)),
        ]),
      ]
    : [];
  const refresh = async () => {
    await Promise.allSettled([
      turns.refetch(),
      ...(lastRequest ? [receipt.refetch()] : []),
      ...(threadId ? [thread.refetch()] : []),
      ...(scopeVerified && toolsOpen && turnId ? [activity.refetch()] : []),
      client.invalidateQueries({ queryKey: [...base, "proposal"] }),
      refreshFacts(),
    ]);
  };
  const refreshFacts = async () => {
    await Promise.allSettled([
      client.invalidateQueries({ queryKey: queryKeys.shot.workbench(projectId, shot.id) }),
      client.invalidateQueries({ queryKey: queryKeys.scene.workspace(projectId, shot.scene_id) }),
      client.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) }),
      client.invalidateQueries({ queryKey: queryKeys.director.turns(projectId, "shot", shot.id) }),
    ]);
  };
  useEffect(() => {
    const result = scopedReceipt;
    if (
      !result ||
      !TERMINAL.has(result.status) ||
      submissionUnknown ||
      (result.status === "completed" && result.transport_status !== "succeeded")
    )
      return;
    if (recovery.pending) {
      const next = settleAgentPanelRecovery(
        key,
        recovery.pending,
        result.status === "completed" && result.transport_status === "succeeded",
      );
      if (!next) return;
      setRecovery(next);
      void client.invalidateQueries({ queryKey: [...base, "thread"] });
      void client.invalidateQueries({ queryKey: [...base, "turns"] });
    }
  }, [scopedReceipt, submissionUnknown, recovery, key, client, base]);

  const send = useMutation({
    retry: false,
    mutationFn: async () => {
      if (dirty || recovery.pending || !recovery.draft.trim())
        throw new Error("请先保存镜头并核对当前请求。");
      if (threadId && !threadVerified) throw new Error("会话范围尚未核对，请先核对状态。");
      const content = recovery.draft;
      let openedId = threadId;
      if (!openedId) {
        const opened = await openDirectorAgentThread(projectId, shot.id);
        if (opened.scope_type !== "shot" || opened.scope_entity_id !== shot.id)
          throw new Error("返回的会话不属于当前镜头，已停止发送。");
        openedId = opened.id;
        if (current()) setOpenedThreadId(opened.id);
      }
      if (!current() || latestDirty.current)
        throw new Error("创作范围或镜头草稿已变化，未发送新的导演请求。");
      const pending = { threadId: openedId, requestKey: `agent:${crypto.randomUUID()}` };
      if (!writeAgentPanelRecovery(key, { draft: content, pending }))
        throw new Error("恢复记录未保存，尚未发送导演请求。");
      setRecovery({ draft: content, pending });
      setLastRequest(pending);
      setOffset(undefined);
      setError(null);
      try {
        const result = await sendDirectorAgentMessage(projectId, openedId, {
          content,
          request_key: pending.requestKey,
          expected_versions: { [`shot:${shot.id}`]: shot.version },
        });
        return { result, pending };
      } catch (failure) {
        if (failure instanceof ApiError && failure.details.request_accepted === false) {
          const settled = settleAgentPanelRecovery(key, pending);
          if (current() && settled) {
            setRecovery(settled);
            setLastRequest(null);
          }
        }
        throw failure;
      }
    },
    onSuccess: ({ result, pending }) => {
      client.setQueryData([...base, "receipt", pending.threadId, pending.requestKey], result);
      if (current()) void refresh();
    },
    onError: (failure) => {
      if (!current()) return;
      setError(failure);
      // Even a 4xx can arrive after admission. Only a read receipt may settle
      // the persisted observation identity; reconnecting never replays this POST.
    },
  });
  const stop = useMutation({
    retry: false,
    mutationFn: async () => {
      if (!current() || !scopeVerified || !turnId || revision === undefined)
        throw new Error("请先核对本轮与镜头范围。");
      return stopDirectorAgentTurn(projectId, turnId, {
        expected_revision: revision,
        request_key: `stop:${crypto.randomUUID()}`,
      });
    },
    onSuccess: (result) => {
      if (!current()) return;
      if (lastRequest) client.setQueryData<AgentTurnResult | null>(receiptKey, result);
      void refresh();
    },
    onError: (failure) => {
      if (current()) setError(failure);
    },
  });
  const activityRows =
    scopeVerified && Array.isArray(activity.data?.tools) ? activity.data.tools : [];
  return (
    <section data-testid="director-agent-panel" data-shot-id={shot.id} aria-label="导演对话协作">
      <SectionHeader title="对话协作" />
      <p>围绕当前镜头读取资料、分析和提出修改建议，采纳前不会改写镜头。</p>
      {dirty && (
        <p role="status" data-testid="director-agent-dirty-guard">
          镜头有未保存修改，请先保存后发送或采纳。
        </p>
      )}
      <Field>
        导演要求
        <Textarea
          aria-label="导演要求"
          value={recovery.draft}
          maxLength={16000}
          disabled={send.isPending || Boolean(recovery.pending)}
          onChange={(event) => saveRecovery({ ...recovery, draft: event.target.value })}
        />
      </Field>
      <div className="df-section-actions">
        <Button
          tone="primary"
          data-testid="director-agent-send"
          disabled={
            dirty ||
            send.isPending ||
            Boolean(recovery.pending) ||
            active ||
            agentTurns.some((turn) => ACTIVE.has(turn.status)) ||
            !turns.isSuccess ||
            Boolean(threadId && !threadVerified) ||
            !recovery.draft.trim() ||
            !enabled
          }
          onClick={() => send.mutate()}
        >
          {send.isPending ? "发送中…" : "发送给导演"}
        </Button>
        <Button
          data-testid="director-agent-refresh"
          onClick={() => void refresh()}
          disabled={!enabled}
        >
          核对状态
        </Button>
        {active && (
          <Button
            data-testid="director-agent-stop"
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            {stop.isPending ? "正在停止…" : "停止本轮"}
          </Button>
        )}
      </div>
      <p role="status" data-testid="director-agent-status">
        {threadId && !scopeVerified
          ? "会话范围待核对，已暂停显示与操作。"
          : recovery.pending && !scopedReceipt
            ? "提交结果待核对；只查询已有回执，不会重新发送。"
            : agentStatusLabel(status)}
        {submissionUnknown && " 提交状态待核实，请勿重复发送。"}
      </p>
      {Boolean(error || receipt.isError || turns.isError) && (
        <p role="alert">{agentErrorMessage(error ?? receipt.error ?? turns.error)}</p>
      )}
      {thread.isError && <p role="alert">会话读取失败，请核对状态；这不表示没有消息。</p>}
      {((thread.data && !threadVerified) || receiptMismatch) && (
        <p role="alert">会话范围与当前镜头不一致，已隐藏内容并阻止操作。</p>
      )}
      {thread.data && scopeVerified && (
        <section aria-label="导演会话">
          <RecordList>
            {thread.data.messages.map((row) => (
              <RecordItem key={row.id} title={row.role === "user" ? "你" : "导演"}>
                <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{row.content}</p>
              </RecordItem>
            ))}
          </RecordList>
          <div className="df-section-actions">
            <Button
              disabled={!thread.data.has_previous}
              onClick={() => setOffset(Math.max(0, thread.data!.offset - thread.data!.limit))}
            >
              更早消息
            </Button>
            <Button
              disabled={!thread.data.has_more}
              onClick={() => setOffset(thread.data!.offset + thread.data!.limit)}
            >
              较新消息
            </Button>
            <Button onClick={() => setOffset(undefined)}>最新消息</Button>
          </div>
        </section>
      )}
      {proposalIds.map((id) => (
        <AgentProposalCard
          key={id}
          proposalId={id}
          projectId={projectId}
          shot={shot}
          dirty={dirty}
          threadId={threadId}
          queryPrefix={base}
          enabled={enabled}
          onReadRefresh={refreshFacts}
          onApplied={() => {
            if (current()) {
              void refreshFacts();
              if (!latestDirty.current) onApplied();
            }
          }}
        />
      ))}
      <Disclosure
        title="工具活动与诊断"
        testId="director-agent-tools"
        open={toolsOpen}
        onOpenChange={setToolsOpen}
        lazy
      >
        {error != null && <p>{message(error)}</p>}
        {activity.isError && <p role="alert">工具活动读取失败，请核对状态。</p>}
        <RecordList>
          {activityRows.map((raw, index) => {
            const row = record(raw);
            return (
              <RecordItem
                key={String(row?.call_id ?? index)}
                title={`步骤 ${String(row?.step ?? index + 1)}`}
                status={agentStatusLabel(typeof row?.status === "string" ? row.status : null)}
              >
                <p>{typeof row?.name === "string" ? row.name : "工具信息待核对"}</p>
              </RecordItem>
            );
          })}
        </RecordList>
        <Button
          disabled={activityOffset === 0}
          onClick={() => setActivityOffset(Math.max(0, activityOffset - 20))}
        >
          上一页活动
        </Button>
        <Button
          disabled={activityRows.length < 20}
          onClick={() => setActivityOffset(activityOffset + 20)}
        >
          下一页活动
        </Button>
      </Disclosure>
    </section>
  );
}

function AgentProposalCard({
  proposalId,
  projectId,
  shot,
  dirty,
  threadId,
  queryPrefix,
  enabled,
  onApplied,
  onReadRefresh,
}: {
  proposalId: string;
  projectId: string;
  shot: ShotLite;
  dirty: boolean;
  threadId: string | null;
  queryPrefix: unknown[];
  enabled: boolean;
  onApplied: () => void;
  onReadRefresh: () => Promise<void>;
}) {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const proposal = useQuery({
    queryKey: [...queryPrefix, "proposal", proposalId],
    queryFn: ({ signal }) => getDirectorAgentProposal(projectId, proposalId, signal),
    enabled,
    retry: false,
  });
  const value = proposal.data;
  const owned =
    value?.project_id === projectId &&
    value.thread_id === threadId &&
    value.scope_type === "shot" &&
    value.scope_entity_id === shot.id;
  const pending = owned ? value.items.filter((item) => item.status === "pending") : [];
  const supported = pending.every(
    (item) =>
      ["shot.update_image_prompt", "shot.update_video_prompt"].includes(item.command) &&
      item.payload.shot_id === shot.id &&
      typeof item.payload[
        item.command.endsWith("image_prompt") ? "image_prompt" : "video_prompt"
      ] === "string",
  );
  const stale = pending.some((item) => item.expected_target_version !== shot.version);
  const decide = useMutation({
    retry: false,
    mutationFn: async (decision: "accepted" | "rejected") => {
      if (!owned || !pending.length || (decision === "accepted" && (dirty || stale || !supported)))
        throw new Error("请先保存镜头并重新核对提案。");
      return applyDirectorAgentProposal(projectId, proposalId, {
        decisions: pending.map((item) => ({ item_id: item.id, decision })),
      });
    },
    onSuccess: (result) => {
      if ((result.accepted?.length ?? 0) > 0) onApplied();
      setError((result.failed?.length ?? 0) > 0 ? "部分建议未能处理，请核对版本后再操作。" : null);
      void client.invalidateQueries({ queryKey: [...queryPrefix, "proposal", proposalId] });
    },
    onError: (failure) => {
      setError(`${agentErrorMessage(failure)} 未覆盖你的输入，请重新核对版本。`);
      void client.invalidateQueries({ queryKey: [...queryPrefix, "proposal", proposalId] });
      void onReadRefresh();
    },
  });
  if (proposal.isError) return <p role="alert">提案读取失败，不能据此判断已采纳。{error}</p>;
  if (!value) return <p role="status">正在读取待采纳建议…</p>;
  if (!owned) return <p role="alert">提案不属于当前镜头，已阻止操作。</p>;
  if (!pending.length)
    return (
      <section data-testid="director-agent-proposal-result" aria-label="建议处理结果">
        <RecordList>
          <RecordItem
            title={agentProposalResultLabel(
              value.status,
              value.items.map((item) => item.status),
            )}
          >
            {error && <p role="alert">{error}</p>}
          </RecordItem>
        </RecordList>
      </section>
    );
  return (
    <section data-testid="director-agent-proposal" aria-label="待采纳提示词建议">
      <SectionHeader title="待采纳建议" />
      <RecordList>
        {pending.map((item) => {
          const image = item.command === "shot.update_image_prompt";
          return (
            <RecordItem key={item.id} title={image ? "画面提示词" : "视频提示词"}>
              <p>{item.rationale}</p>
              <p>当前内容</p>
              <p data-testid="director-agent-before" style={{ overflowWrap: "anywhere" }}>
                {image ? shot.image_prompt : shot.video_prompt}
              </p>
              <p>建议内容</p>
              <p data-testid="director-agent-after" style={{ overflowWrap: "anywhere" }}>
                {String(
                  item.payload[image ? "image_prompt" : "video_prompt"] ?? "当前界面不支持此建议",
                )}
              </p>
            </RecordItem>
          );
        })}
      </RecordList>
      {stale && <p role="status">镜头版本已变化，请重新核对建议。</p>}
      {error && <p role="alert">{error}</p>}
      <Button
        tone="accent"
        data-testid="director-agent-apply"
        disabled={dirty || stale || !supported || decide.isPending || !enabled}
        onClick={() => decide.mutate("accepted")}
      >
        采纳建议
      </Button>
      <Button
        data-testid="director-agent-reject"
        disabled={decide.isPending || !enabled}
        onClick={() => decide.mutate("rejected")}
      >
        拒绝建议
      </Button>
    </section>
  );
}
