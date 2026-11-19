import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button, Field, Textarea } from "../../components/ui";
import { fetchCreativeDirection, saveCreativeDirection } from "./api";

type CreativeDirectionPanelProps = {
  projectId: string;
};

/**
 * Project creative direction: one explicit note with profile-version CAS.
 *
 * The note is user-authored context for the story brief; saving it never
 * generates anything and never rewrites other strategy facts.
 */
export function CreativeDirectionPanel({ projectId }: CreativeDirectionPanelProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const direction = useQuery({
    queryKey: ["creative-direction", projectId],
    queryFn: () => fetchCreativeDirection(projectId),
    retry: false,
  });

  useEffect(() => {
    if (direction.data && typeof direction.data.direction === "string") {
      setDraft(direction.data.direction);
    }
  }, [direction.data]);

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
      <Button
        type="button"
        tone="primary"
        disabled={save.isPending || draft.trim().length === 0}
        onClick={() => save.mutate()}
      >
        保存创作方向
      </Button>
    </section>
  );
}
