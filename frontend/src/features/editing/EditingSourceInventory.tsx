import { Disclosure, Table } from "../../components/ui";
import type { OpenCutManifestRead } from "../../lib/api";
import { timelineCopy as copy } from "./timelineCopy";

function seconds(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(parsed)
    : value;
}

/** Inspect the Formal handoff on demand; it is never a second editable timeline. */
export function EditingSourceInventory({ manifest }: { manifest: OpenCutManifestRead }) {
  const shotNumbers = new Map(manifest.shots.map((shot) => [shot.shot_id, shot.shot_number]));
  const rows = manifest.tracks
    .flatMap((track) => track.clips.map((clip) => ({ track: track.name, clip })))
    .map((row, index) => ({ ...row, position: index + 1 }));
  return (
    <Disclosure
      title={copy.inventory}
      description={copy.inventoryCount(rows.length)}
      testId="editing-source-inventory"
    >
      <Table
        rowKey={(row) => row.clip.id}
        dataSource={rows}
        size="small"
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{ emptyText: <span data-testid="editing-no-clips">{copy.inventoryEmpty}</span> }}
        onRow={() => ({ className: "editing-inventory-row", "data-testid": "editing-clip" })}
        columns={[
          { title: copy.inventoryTrack, dataIndex: "track", key: "track" },
          {
            title: copy.inventoryShot,
            key: "shot",
            render: (_, { clip, position }) =>
              `${copy.clip} ${position}${shotNumbers.has(clip.shot_id) ? ` · ${copy.shot} #${shotNumbers.get(clip.shot_id)}` : ""}`,
          },
          {
            title: copy.inventoryRange,
            key: "range",
            render: (_, { clip }) =>
              `${seconds(clip.timeline_start_seconds)}–${seconds(clip.timeline_end_seconds)} 秒`,
          },
          {
            title: copy.inventoryContent,
            key: "content",
            render: (_, { clip }) =>
              clip.text ||
              (clip.source_url
                ? copy.sourceDelivered
                : clip.artifact_id
                  ? copy.sourcePending
                  : copy.sourceUnbound),
          },
        ]}
      />
    </Disclosure>
  );
}
