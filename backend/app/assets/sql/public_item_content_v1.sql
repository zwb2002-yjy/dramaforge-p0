-- Frozen input to migration 0125. Bind identities at the call boundary.
-- Access is evaluated for this one publication item, in a single statement.
WITH RECURSIVE candidate AS (
    SELECT a.id, a.object_key, a.mime_type, a.byte_size, a.content_hash
    FROM {schema}public_asset_publication_items i
    JOIN {schema}public_asset_publications p
      ON p.id = i.publication_id AND p.owner_user_id = i.owner_user_id
    JOIN {schema}projects src ON src.id = p.source_project_id
    JOIN {schema}workspaces sw ON sw.id = src.workspace_id AND sw.owner_user_id = p.owner_user_id
    JOIN {schema}asset_versions v ON v.id = p.source_asset_version_id
      AND v.project_id = src.id AND v.status = 'formal'
    JOIN {schema}asset_version_references ref ON ref.id = i.source_reference_id
      AND ref.asset_version_id = v.id AND ref.project_id = src.id AND ref.artifact_id = i.artifact_id
    JOIN {schema}artifacts a ON a.id = i.artifact_id AND a.project_id = src.id
    WHERE i.id = {item} AND p.owner_user_id = {actor}
      AND p.status = 'available' AND p.withdrawn_at IS NULL
      AND i.source_asset_version_id = v.id AND i.source_project_id = src.id
      AND p.workspace_id = sw.id AND i.workspace_id = sw.id
      AND a.storage_state = 'available' AND a.deleted_at IS NULL
      AND EXISTS (SELECT 1 FROM {schema}workspaces cw
                  WHERE cw.id = {workspace} AND cw.owner_user_id = p.owner_user_id)
      AND (({project} IS NULL AND {link} IS NULL AND p.id = {publication})
        OR ({publication} IS NULL AND {project} = {active_project} AND EXISTS (
            SELECT 1 FROM {schema}project_public_asset_links l
            JOIN {schema}projects dest ON dest.id = l.project_id AND dest.deleted_at IS NULL
            WHERE l.id = {link} AND l.project_id = {project} AND l.publication_id = p.id
              AND l.workspace_id = {workspace} AND dest.workspace_id = l.workspace_id
              AND l.owner_user_id = p.owner_user_id AND l.source_asset_version_id = v.id
              AND l.detached_at IS NULL)))
), media(id, depth) AS (
    SELECT id, 0 FROM candidate
    UNION
    SELECT s.artifact_id, m.depth + 1 FROM media m
    JOIN {schema}artifact_source_uses u ON u.artifact_id = m.id
    JOIN {schema}source_use_subjects s ON s.id = u.source_subject_id
    WHERE s.artifact_id IS NOT NULL AND m.depth < 33
), bounded AS (SELECT id, depth FROM media LIMIT 1025),
required(id) AS (
    SELECT s.id FROM bounded m JOIN {schema}source_use_subjects s ON s.artifact_id = m.id
    UNION
    SELECT u.source_subject_id FROM bounded m JOIN {schema}artifact_source_uses u ON u.artifact_id = m.id
    LIMIT 1025
)
SELECT c.object_key, c.mime_type, c.byte_size, c.content_hash FROM candidate c
WHERE EXISTS (SELECT 1 FROM required)
  AND NOT EXISTS (SELECT 1 FROM bounded WHERE depth > 32)
  AND (SELECT count(*) FROM bounded) <= 1024 AND (SELECT count(*) FROM required) <= 1024
  AND NOT EXISTS (
    SELECT 1 FROM required q
    LEFT JOIN {schema}source_use_subjects s ON s.id = q.id
    LEFT JOIN {schema}source_use_revisions r
      ON r.id = s.current_revision_id AND r.subject_id = s.id AND r.project_id = s.project_id
    WHERE r.state IS NULL OR r.state <> 'declared' OR NOT ({permits_library})
  )
