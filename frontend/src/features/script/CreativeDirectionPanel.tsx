import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Button, Field, Textarea } from "../../components/ui";
import {
  openProjectDirectorThread,
  readDirectorAgentThread,
  sendDirectorAgentMessage,
} from "../director/api";
import { fetchCreativeDirection, saveCreativeDirection } from "./api";

type CreativeDirectionPanelProps = {
  projectId: string;
};

/**
 * Project creative direction plus a project-scoped Director discussion.
 *
 * The note is user-authored context for the story brief; the discussion reuses
 * the existing agent thread (one per project scope) and only copies an
 * assistant message into the draft when the user explicitly adopts it.
 */
export function CreativeDirectionPanel({ projectId }: CreativeDirectionPanelProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [awaitingReply, setAwaitingReply] = useState(false);

  const direction = useQuery({
    queryKey: ["creative-direction", projectId],
    queryFn: () => fetchCreativeDirection(projectId),
    retry: false,
  });
  const thread = useQuery({
    queryKey: ["direction-thread", projectId, threadId],
    queryFn: () => readDirectorAgentThread(projectId, threadId!),
    enabled: threadId !== null,
    retry: false,
    refetchInterval: awaitingReply ? 2000 : false,
  });

  useEffect(() => {
    if (direction.data && typeof direction.data.direction === "string") {
      setDraft(direction.data.direction);
    }
  }, [direction.data]);

  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data]);
  const lastMessage = messages[messages.length - 1];

  useEffect(() => {
    if (awaitingReply && lastMessage?.role === "assistant") {
      setAwaitingReply(false);
    }
  }, [awaitingReply, lastMessage]);

  const save = useMutation({
    mutationFn: () =>
      saveCreativeDirection(projectId, {
        expected_profile_version: direction.data?.profile_version ?? 1,
        direction: draft,
      }),
    onSuccess: (saved) => {
      setError(null);
      setMessage("创作方向已保存。");
      setDraft(saved.direction);
      queryClient.setQueryData(["creative-direction", projectId], saved);
    },
    onError: (cause) => {
      setMessage(null);
      setError(cause instanceof Error ? cause.message : "保存失败");
    },
  });

  const openThread = useMutation({
    mutationFn: () => openProjectDirectorThread(projectId),
    onSuccess: (ref) => {
      setThreadId(ref.id);
      setError(null);
    },
    onError: (cause) => {
      setError(cause instanceof Error ? cause.message : "无法开始方向讨论");
    },
  });

  const send = useMutation({
    mutationFn: () =>
      sendDirectorAgentMessage(projectId, threadId!, {
        content: question,
        request_key: `direction:${Date.now()}`,
        intent: "conversation",
      }),
    onSuccess: () => {
      setQuestion("");
      setAwaitingReply(true);
      void thread.refetch();
    },
    onError: (cause) => {
      setError(cause instanceof Error ? cause.message : "发送失败");
    },
  });

  return (
    <section className="qc-script-direction" data-testid="creative-direction">
      <div className="panel-header">
        <h3>创作方向</h3>
      </div>
      <p className="muted">写清题材、时代、语气与禁区；生成故事时作为 brief 的上下文。</p>
      {direction.isError && <p role="alert">创作方向读取失败，请稍后重试。</p>}
      <Field>
        <span>方向说明</span>
        <Textarea
          aria-label="创作方向"
          rows={3}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </Field>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      <div className="toolbar">
        <Button
          type="button"
          tone="primary"
          disabled={save.isPending || draft.trim().length === 0}
          onClick={() => save.mutate()}
        >
          保存创作方向
        </Button>
        {threadId === null && (
          <Button
            type="button"
            tone="ghost"
            disabled={openThread.isPending}
            onClick={() => openThread.mutate()}
          >
            开始方向讨论
          </Button>
        )}
      </div>
      {threadId !== null && (
        <div className="direction-discussion" aria-label="方向讨论">
          <ul className="direction-messages">
            {messages.slice(-6).map((item) => (
              <li key={item.id}>
                <span className="status-label">{item.role === "assistant" ? "导演" : "你"}</span>
                <p>{item.content}</p>
                {item.role === "assistant" && (
                  <Button type="button" tone="ghost" onClick={() => setDraft(item.content)}>
                    采用为方向
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {awaitingReply && <p role="status">导演正在思考…</p>}
          <Field>
            <span>讨论问题</span>
            <Textarea
              aria-label="讨论问题"
              rows={2}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </Field>
          <Button
            type="button"
            tone="primary"
            disabled={send.isPending || question.trim().length === 0}
            onClick={() => send.mutate()}
          >
            发送讨论
          </Button>
        </div>
      )}
    </section>
  );
}
