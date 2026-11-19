import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Alert, Button, Card, Field, Select, Textarea } from "../ui";
import {
  getMediaConfig,
  listWorkspaceModelBindings,
  putMediaConfig,
  reconcileMediaConfig,
  reviewMediaConfig,
} from "../../features/model-controls/api";
import { queryKeys } from "../../lib/queryKeys";

type MediaConfigSectionProps = {
  workspaceId: string | null;
  profileId: string | null;
  profileVersion: number | null;
};

/**
 * D6 media defaults (image / video / voice) on the project profile row.
 *
 * Legacy (version 1) profiles are read-only until the user reviews the listed
 * legacy media slots and reconciles them with one explicit fingerprint.
 */
export function MediaConfigSection({
  workspaceId,
  profileId,
  profileVersion,
}: MediaConfigSectionProps) {
  const queryClient = useQueryClient();
  const [imageId, setImageId] = useState("");
  const [videoId, setVideoId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [voiceOptions, setVoiceOptions] = useState("{}");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(workspaceId && profileId);
  const config = useQuery({
    queryKey: queryKeys.model.mediaConfig(profileId),
    queryFn: () => getMediaConfig(workspaceId!, profileId!),
    enabled,
  });
  const review = useQuery({
    queryKey: queryKeys.model.mediaConfigReview(profileId),
    queryFn: () => reviewMediaConfig(workspaceId!, profileId!),
    enabled,
  });
  const bindings = useQuery({
    queryKey: queryKeys.model.workspaceBindings(workspaceId),
    queryFn: () => listWorkspaceModelBindings(workspaceId!),
    enabled: Boolean(workspaceId),
  });

  useEffect(() => {
    if (!config.data) return;
    setImageId(config.data.image_model_binding_id ?? "");
    setVideoId(config.data.video_model_binding_id ?? "");
    setVoiceId(config.data.voice_model_binding_id ?? "");
    setVoiceOptions(JSON.stringify(config.data.voice_options ?? {}, null, 2));
  }, [config.data]);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.model.mediaConfig(profileId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.model.mediaConfigReview(profileId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.model.projectProfile(profileId ?? ""),
    });
  };

  const parseOptions = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(voiceOptions || "{}") as unknown;
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setError("语音选项必须是 JSON 对象。");
        return null;
      }
      return parsed as Record<string, unknown>;
    } catch {
      setError("语音选项不是合法 JSON。");
      return null;
    }
  };

  const save = useMutation({
    mutationFn: async () => {
      const options = parseOptions();
      if (options === null) throw new Error("invalid voice options");
      return putMediaConfig(workspaceId!, profileId!, {
        expected_version: profileVersion ?? 0,
        image_model_binding_id: imageId || null,
        video_model_binding_id: videoId || null,
        voice_model_binding_id: voiceId || null,
        voice_options: options,
      });
    },
    onSuccess: () => {
      setError(null);
      setMessage("媒体默认已保存。");
      invalidate();
    },
    onError: (cause) => {
      setMessage(null);
      setError(cause instanceof Error ? cause.message : "保存失败");
    },
  });

  const reconcile = useMutation({
    mutationFn: async () => {
      if (!review.data) throw new Error("缺少旧配置核对信息");
      const options = parseOptions();
      if (options === null) throw new Error("invalid voice options");
      return reconcileMediaConfig(workspaceId!, profileId!, {
        expected_version: profileVersion ?? 0,
        review_fingerprint: review.data.review_fingerprint,
        image_model_binding_id: imageId || null,
        video_model_binding_id: videoId || null,
        voice_model_binding_id: voiceId || null,
        voice_options: options,
      });
    },
    onSuccess: () => {
      setError(null);
      setMessage("旧媒体配置已核对并迁移。");
      invalidate();
    },
    onError: (cause) => {
      setMessage(null);
      setError(cause instanceof Error ? cause.message : "核对失败");
    },
  });

  if (!enabled) return null;
  const optionsFor = (mediaType: string) =>
    (bindings.data ?? [])
      .filter((item) => item.media_type === mediaType)
      .map((item) => ({ value: item.id, label: `${item.model_id} (${item.purpose})` }));
  const legacy = review.data?.media_config_version === 1;

  return (
    <Card aria-label="媒体默认">
      <h3>媒体默认</h3>
      <p className="muted">图片/视频/语音的项目默认；语音选项只在选择语音模型后可填。</p>
      {message && <p role="status">{message}</p>}
      {error && <Alert type="error" description={error} />}
      {legacy && (
        <Alert
          type="warning"
          description={`该方案仍是旧媒体配置，需核对以下媒体槽后再迁移：${
            review.data?.conflicts.map((item) => String(item.slot)).join("、") || "无"
          }`}
        />
      )}
      <Field>
        <span>图片默认</span>
        <Select
          value={imageId}
          onChange={(value) => setImageId(value)}
          options={[{ value: "", label: "未配置" }, ...optionsFor("image")]}
        />
      </Field>
      <Field>
        <span>视频默认</span>
        <Select
          value={videoId}
          onChange={(value) => setVideoId(value)}
          options={[{ value: "", label: "未配置" }, ...optionsFor("video")]}
        />
      </Field>
      <Field>
        <span>语音默认</span>
        <Select
          value={voiceId}
          onChange={(value) => setVoiceId(value)}
          options={[{ value: "", label: "未配置" }, ...optionsFor("voice")]}
        />
      </Field>
      <Field>
        <span>语音选项（JSON）</span>
        <Textarea
          value={voiceOptions}
          onChange={(event) => setVoiceOptions(event.target.value)}
          rows={3}
        />
      </Field>
      {legacy ? (
        <Button disabled={reconcile.isPending} onClick={() => reconcile.mutate()}>
          核对并迁移旧媒体配置
        </Button>
      ) : (
        <Button disabled={save.isPending} onClick={() => save.mutate()}>
          保存媒体默认
        </Button>
      )}
    </Card>
  );
}
