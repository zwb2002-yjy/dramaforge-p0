-- Resolve only the item fixed by this consuming project link.
WITH RECURSIVE candidate AS (
    SELECT a.id, a.project_id, CAST(a.artifact_type AS varchar) AS artifact_type,
           CAST(a.storage_state AS varchar) AS storage_state, a.object_key, a.mime_type,
           a.byte_size, CAST(a.content_hash AS varchar) AS content_hash,
           p.revision AS publication_revision, l.version AS link_version
    FROM {schema}project_public_asset_links l
    JOIN {schema}public_asset_publications p ON p.id = l.publication_id
      AND p.owner_user_id = l.owner_user_id AND p.source_asset_version_id = l.source_asset_version_id
    JOIN {schema}public_asset_publication_items i ON i.publication_id = p.id AND i.id = {item}
    JOIN {schema}artifacts a ON a.id = i.artifact_id
    JOIN {schema}asset_versions v ON v.id = p.source_asset_version_id
    WHERE l.id = {link} AND l.project_id = {project} AND EXISTS ({permitted})
    {row_lock}
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
), grants AS (
    SELECT s.id, s.project_id, r.id AS revision_id, r.state,
           ({external_use}) AS external_allowed
    FROM required q
    JOIN {schema}source_use_subjects s ON s.id = q.id
    LEFT JOIN {schema}source_use_revisions r
      ON r.id = s.current_revision_id AND r.subject_id = s.id AND r.project_id = s.project_id
)
{lock_ctes}
SELECT c.*, ({revision_key}) AS revision_key FROM candidate c
WHERE (SELECT count(*) FROM bounded) <= 1024 AND (SELECT count(*) FROM required) <= 1024
  AND NOT EXISTS (SELECT 1 FROM bounded WHERE depth > 32)
  AND ({preview} OR NOT EXISTS (
      SELECT 1 FROM grants WHERE state IS NULL OR state <> 'declared' OR NOT external_allowed
  ))
  {lock_check}
