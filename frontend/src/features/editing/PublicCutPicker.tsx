import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Checkbox, Field } from "../../components/ui";
import { apiGet, projectPublicContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { loadPublicLinks } from "../assets/publicLinks";
import type { components } from "../../shared/api/generated";
import type { EditableClip } from "./useTimelineDraft";
import type { PublicCutSelection } from "./publicCutSource";

type Link = components["schemas"]["PublicLinkReadModel"];
type Item = components["schemas"]["PublicItemRead"];
type Publication = components["schemas"]["PublicAssetReadModel"];
type Props = {
  projectId: string;
  clip?: EditableClip;
  onUse: (selection: PublicCutSelection) => void;
};

function LinkedPublication({ projectId, link, clip, onUse }: Props & { link: Link }) {
  const publication = useQuery({
    queryKey: ["editing-linked-publication", projectId, link.id, link.version],
    queryFn: ({ signal }) =>
      apiGet<Publication>(`/api/v1/public-assets/${link.publication_id}`, undefined, signal),
    retry: false,
  });
  const [selected, setSelected] = useState<Item | null>(null);
  const media =
    publication.data?.items.filter(
      (item) =>
        item.preview_available && (item.media_kind === "video" || item.media_kind === "audio"),
    ) ?? [];
  if (publication.isPending) return <li>正在读取素材…</li>;
  if (publication.isError)
    return (
      <li role="alert">
        素材详情读取失败。<Button onClick={() => void publication.refetch()}>重新读取</Button>
      </li>
    );
  if (!publication.data?.usable || !media.length)
    return <li>{link.local_label || publication.data?.safe_name} · 暂无可选音视频</li>;
  const item = media.find((value) => value.id === selected?.id);
  return (
    <li>
      <strong>{link.local_label || publication.data.safe_name}</strong>
      {media.map((value, i) => (
        <Button
          key={value.id}
          aria-pressed={item?.id === value.id}
          onClick={() => setSelected(item?.id === value.id ? null : value)}
        >
          {value.media_kind === "video" ? "预览视频" : "试听音频"}
          {media.length > 1 ? ` ${i + 1}` : ""}
        </Button>
      ))}
      {item && (
        <Preview
          key={item.id}
          projectId={projectId}
          link={link}
          item={item}
          clip={clip}
          onUse={onUse}
        />
      )}
    </li>
  );
}

function Preview({ projectId, link, item, clip, onUse }: Props & { link: Link; item: Item }) {
  const [seconds, setSeconds] = useState(0);
  const [failed, setFailed] = useState(false);
  const [reset, setReset] = useState(false);
  const video = item.media_kind === "video";
  const url = projectPublicContentUrl(projectId, link.id, item.id);
  const start = Number(clip?.source_in_seconds ?? clip?.trim_start_seconds ?? 0);
  const end = Number(
    clip?.source_out_seconds ??
      clip?.trim_end_seconds ??
      start + Number(clip?.duration_seconds ?? 0),
  );
  const outside = !!clip && (start < 0 || end <= start || end > seconds + 0.001);
  const Media = video ? "video" : "audio";
  const usable = !failed && Number.isFinite(seconds) && seconds > 0;
  function apply(action: PublicCutSelection["action"]) {
    onUse({
      action,
      source: {
        kind: "public_material",
        publication_id: link.publication_id,
        publication_item_id: item.id,
        public_asset_link_id: link.id,
      },
      seconds,
      resetCrop: outside && reset,
    });
  }
  return (
    <div>
      <Media
        controls
        preload="metadata"
        src={url}
        aria-label={video ? "公共视频预览" : "公共音频试听"}
        onLoadedMetadata={(e) => {
          setSeconds(e.currentTarget.duration);
          setFailed(false);
        }}
        onError={() => setFailed(true)}
      />
      {failed && <p role="alert">这份固定素材无法播放，请核对项目引用和来源许可。</p>}
      {video && usable && outside && (
        <Field>
          <Checkbox checked={reset} onChange={(e) => setReset(e.target.checked)} />
          原裁切超出新视频长度，替换时使用完整视频
        </Field>
      )}
      {video && (
        <Button disabled={!usable} onClick={() => apply("append")}>
          添加为新片段
        </Button>
      )}
      {clip && (
        <Button
          disabled={!usable || (video && outside && !reset)}
          onClick={() => apply(video ? "replace" : "audio")}
        >
          {video ? "替换当前片段画面" : "用作当前片段音轨"}
        </Button>
      )}
    </div>
  );
}

export function PublicCutPicker({ projectId, clip, onUse }: Props) {
  const [page, setPage] = useState(0);
  const links = useQuery({
    queryKey: queryKeys.asset.publicLinks(projectId),
    queryFn: ({ signal }) => loadPublicLinks(projectId, signal),
    retry: false,
  });
  const available = [...(links.data?.values() ?? [])].filter(
    (link) => !link.detached_at && link.availability === "available",
  );
  const size = 12;
  const current = Math.min(page, Math.max(0, Math.ceil(available.length / size) - 1));
  return (
    <section aria-label="本项目引用的公共素材">
      {links.isPending && <p role="status">正在读取项目引用…</p>}
      {links.isError && (
        <p role="alert">
          项目引用读取失败。<Button onClick={() => void links.refetch()}>重试</Button>
        </p>
      )}
      {links.isSuccess && !available.length && <p>请先在公共资产页将素材引用到当前项目。</p>}
      <ul>
        {available.slice(current * size, (current + 1) * size).map((link) => (
          <LinkedPublication
            key={link.id}
            projectId={projectId}
            link={link}
            clip={clip}
            onUse={onUse}
          />
        ))}
      </ul>
      {available.length > size && (
        <nav aria-label="素材分页">
          <Button disabled={!current} onClick={() => setPage(current - 1)}>
            上一页
          </Button>
          <Button
            disabled={(current + 1) * size >= available.length}
            onClick={() => setPage(current + 1)}
          >
            下一页
          </Button>
        </nav>
      )}
    </section>
  );
}
