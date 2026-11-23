-- Safe card fields. Object locators and private source identities stay internal.
SELECT member.id, a.artifact_type AS media_kind, ref.reference_role AS role,
       a.mime_type, a.width, a.height, a.duration_seconds,
       EXISTS ({content_query}) AS preview_available
FROM {schema}public_asset_publication_items member
JOIN {schema}public_asset_publications pub ON pub.id = member.publication_id
    AND pub.owner_user_id = member.owner_user_id
JOIN {schema}asset_version_references ref ON ref.id = member.source_reference_id
    AND ref.asset_version_id = pub.source_asset_version_id AND ref.artifact_id = member.artifact_id
JOIN {schema}artifacts a ON a.id = ref.artifact_id AND a.project_id = pub.source_project_id
WHERE pub.id = {publication} AND pub.owner_user_id = {actor}
  AND EXISTS (SELECT 1 FROM {schema}workspaces selected
              WHERE selected.id = {workspace} AND selected.owner_user_id = pub.owner_user_id)
ORDER BY member.created_at, member.id
