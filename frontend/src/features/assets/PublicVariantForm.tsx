import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActionLink, Button, Dialog, Field, Input, Textarea } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import { assetDecisionKey, createProjectVariant, fetchAssetVersions } from "./api";
import type { components } from "../../shared/api/generated";

type Publication = components["schemas"]["PublicAssetReadModel"];
type Link = components["schemas"]["PublicLinkReadModel"];

export function PublicVariantForm({
  projectId,
  asset,
  link,
  onClose,
}: {
  projectId: string;
  asset: Publication;
  link: Link;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(`${asset.safe_name} · 项目变体`.slice(0, 160));
  const [description, setDescription] = useState(asset.safe_description);
  const [key, setKey] = useState(assetDecisionKey);
  const create = useMutation({
    mutationFn: () =>
      createProjectVariant(projectId, {
        request_key: key,
        base_public_asset_link_id: link.id,
        kind: asset.kind,
        name: name.trim(),
        description: description.trim(),
      }),
    retry: false,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
    },
  });
  const id = create.data?.id;
  const history = useQuery({
    queryKey: queryKeys.asset.versions(projectId, id ?? ""),
    queryFn: () => fetchAssetVersions(projectId, id!),
    enabled: !!id,
    retry: false,
  });
  const created = history.data?.find(
    (v) => v.base_publication_id === asset.id && v.base_public_asset_link_id === link.id,
  );
  return (
    <Dialog
      open
      title="创建项目变体"
      onClose={() => {
        if (!create.isPending) onClose();
      }}
      actions={
        id ? (
          <Button onClick={onClose}>完成</Button>
        ) : (
          <>
            <Button disabled={create.isPending} onClick={onClose}>
              取消
            </Button>
            <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
              创建变体候选
            </Button>
          </>
        )
      }
    >
      <p>基于「{asset.safe_name}」的固定引用，为当前项目保存独立名称与说明。</p>
      {!id && (
        <>
          <Field>
            <span>变体名称</span>
            <Input
              value={name}
              maxLength={160}
              disabled={create.isPending}
              onChange={(e) => {
                setName(e.target.value);
                setKey(assetDecisionKey());
              }}
            />
          </Field>
          <Field>
            <span>项目说明</span>
            <Textarea
              value={description}
              maxLength={12000}
              disabled={create.isPending}
              onChange={(e) => {
                setDescription(e.target.value);
                setKey(assetDecisionKey());
              }}
            />
          </Field>
        </>
      )}
      {create.isError && <p role="alert">{create.error.message}</p>}
      {id && history.isPending && <p role="status">正在读取项目版本…</p>}
      {id && history.isError && (
        <p role="alert">
          变体已创建，版本历史读取失败。
          <Button onClick={() => void history.refetch()}>重读历史</Button>
        </p>
      )}
      {created && (
        <>
          <p role="status">
            已保存「{created.name}」的项目版本 v{created.version_number}（
            {created.status === "formal"
              ? "正式"
              : created.status === "candidate"
                ? "候选"
                : "历史"}
            ）。
          </p>
          <ActionLink
            to="/projects/$projectId/assets"
            params={{ projectId }}
            search={{ kind: asset.kind }}
            onClick={onClose}
          >
            查看项目素材
          </ActionLink>
        </>
      )}
    </Dialog>
  );
}
