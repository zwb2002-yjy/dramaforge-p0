import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useContext, useEffect, useState } from "react";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ActionLink, Alert, Button, Field, Select, Disclosure } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { fetchOpenCutManifest } from "../editing/api";
import { fetchProjectShots, fetchShotWorkbench } from "../shots/api";
import { parseShotCandidates, isConfirmableShotCandidate } from "../shots/shotCandidates";
import { WORK_TYPE_LABELS } from "./projectIntent";
import type { ProjectRead } from "./api";

export function StudioOverview({
  project,
  resumePath,
}: {
  project: ProjectRead;
  resumePath: string | null;
}) {
  const projectId = project.id;
  const onPreview = useContext(StudioSelection)?.show;
  const manifest = useQuery({
    queryKey: queryKeys.production.opencutManifest(projectId),
    queryFn: () => fetchOpenCutManifest(projectId),
  });
  const shots = useQuery({
    queryKey: queryKeys.shot.review(projectId),
    queryFn: () => fetchProjectShots(projectId),
  });
  const [shotChoice, selectShot] = useState("");
  const shot = shots.data?.find((row) => row.id === shotChoice) ?? shots.data?.[0];
  const workbench = useQuery({
    queryKey: queryKeys.shot.reviewWorkbench(projectId, shot?.id),
    queryFn: () => fetchShotWorkbench(projectId, shot!.id),
    enabled: !!shot,
  });
  const candidates = parseShotCandidates(workbench.data?.candidates).filter(
    isConfirmableShotCandidate,
  );
  const [choice, choose] = useState("");
  const formal = manifest.data?.tracks
    ?.flatMap((track) => track.clips)
    .find((clip) => clip.shot_id === shot?.id && clip.track_kind === "video" && clip.artifact_id);
  const selected =
    candidates.find((item) => item.artifactId === choice) ??
    candidates.find((item) => item.artifactId === formal?.artifact_id) ??
    candidates[0];
  const id = selected?.artifactId ?? formal?.artifact_id;
  const video = selected ? selected.stage === "video" : !!formal;
  const media = id ? artifactContentUrl(projectId, id) : null;
  useEffect(() => {
    onPreview?.(media && id ? { id, url: media, video } : null);
    return () => onPreview?.(null);
  }, [onPreview, id, media, video]);
  return (
    <section className="studio-overview" aria-label="项目概览">
      {shots.isError || manifest.isError || workbench.isError ? (
        <Alert
          type="error"
          description="部分作品信息读取失败。"
          action={
            <Button
              onClick={() => {
                void shots.refetch();
                void manifest.refetch();
                if (shot) void workbench.refetch();
              }}
            >
              重新读取
            </Button>
          }
        />
      ) : null}
      {shot && (shots.data?.length ?? 0) > 1 && (
        <Field>
          当前镜头{" "}
          <Select
            value={shot.id}
            onChange={(event) => {
              selectShot(event);
              choose("");
            }}
          >
            {shots.data?.map((item) => (
              <option key={item.id} value={item.id}>
                镜头 {item.shot_number} · {item.visual_description}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <div className="studio-preview">
        {media ? (
          video ? (
            <video key={id} controls preload="metadata" src={media} aria-label="作品预览" />
          ) : (
            <img src={media} alt="当前关键帧候选" />
          )
        ) : shots.isPending || manifest.isPending || (shot && workbench.isPending) ? (
          <p role="status">正在读取作品…</p>
        ) : (
          <div>
            <h2>{shot ? "这个镜头还没有可预览的素材" : "从一个想法开始"}</h2>
            <ActionLink to="/projects/$projectId/files" params={{ projectId }}>
              加入项目资料
            </ActionLink>{" "}
            <Button
              onClick={() => {
                const input = document.getElementById("project-director-message");
                if (!input?.getClientRects().length)
                  document.getElementById("studio-chat-toggle")?.click();
                requestAnimationFrame(() => input?.focus());
              }}
            >
              和导演讨论
            </Button>
          </div>
        )}
      </div>
      {candidates.length > 0 && (
        <section className="studio-results">
          <h2>
            生成结果 <span>（{candidates.length}）</span>
          </h2>
          <div className="studio-candidates" aria-label="镜头候选">
            {candidates.map((item, index) => (
              <Button
                key={item.artifactId}
                className="studio-candidate"
                aria-label={`预览第 ${index + 1} 个${item.stage === "video" ? "视频" : "关键帧"}`}
                aria-pressed={item.artifactId === id}
                tone={item.artifactId === id ? "primary" : "default"}
                onClick={() => choose(item.artifactId)}
              >
                {item.stage === "video" ? (
                  <video
                    muted
                    playsInline
                    preload="metadata"
                    src={artifactContentUrl(projectId, item.artifactId) + "#t=0.01"}
                  />
                ) : (
                  <img src={artifactContentUrl(projectId, item.artifactId)} alt="" />
                )}
                <span>
                  {item.stage === "video" ? "视频" : "关键帧"} {index + 1}
                </span>
              </Button>
            ))}
          </div>
        </section>
      )}
      {selected && shot && (
        <ActionLink
          to="/projects/$projectId/review"
          params={{ projectId }}
          search={{
            shotId: shot.id,
            artifactId: selected.artifactId,
            stage: video ? "formal_video" : "formal_keyframe",
            reviewKind: video ? "video_drift" : "identity",
          }}
        >
          审查当前素材
        </ActionLink>
      )}
      {!candidates.length && project.creative_goal && <p>{project.creative_goal}</p>}
      <Disclosure title="项目目标与设定" compact>
        <header>
          <div>
            <p className="muted">
              {project.work_type ? WORK_TYPE_LABELS[project.work_type] : "项目"}
            </p>
            <h1>{project.name}</h1>
          </div>
          {resumePath && <Link to={resumePath}>继续上次工作</Link>}
        </header>
        {project.creative_goal && <p>{project.creative_goal}</p>}
      </Disclosure>
    </section>
  );
}
