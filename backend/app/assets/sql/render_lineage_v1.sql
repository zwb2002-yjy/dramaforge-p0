-- Whether a render (or an upstream render it consumes) has complete public origins.
-- Historical downloads do not call this gate. It is for new use only.
WITH RECURSIVE lineage(id,depth) AS (
    SELECT {root},0 UNION
    SELECT s.artifact_id,c.depth+1 FROM lineage c
    JOIN {schema}artifact_source_uses u ON u.artifact_id=c.id
    JOIN {schema}source_use_subjects s ON s.id=u.source_subject_id
    WHERE c.depth<33 AND s.artifact_id IS NOT NULL
), bounded AS (SELECT id,depth FROM lineage LIMIT 1025)
SELECT (SELECT count(*) FROM bounded)<=1024 AND NOT EXISTS (SELECT 1 FROM bounded WHERE depth>32)
AND NOT EXISTS (
    SELECT 1 FROM bounded b
    JOIN {schema}artifacts a ON a.id=b.id
    JOIN {schema}node_runs n ON n.id=a.produced_by_run_id
    JOIN {schema}graph_nodes g ON g.id=n.graph_node_id
    WHERE g.node_key IN ('edit_session_render','final_film_assembly') AND (
        ((g.node_key='edit_session_render' OR CAST(n.input_snapshot->'timeline'->>'schema_version' AS text)='2')
         AND n.input_snapshot->'public_inputs' IS NULL)
        OR (CASE WHEN n.input_snapshot->'public_inputs' IS NULL THEN 0
            WHEN {json_type}(n.input_snapshot->'public_inputs')='array' THEN {length}(n.input_snapshot->'public_inputs')
            ELSE -1 END)
           <> (CASE WHEN n.input_snapshot->'public_source_grants' IS NULL THEN 0
            WHEN {json_type}(n.input_snapshot->'public_source_grants')='array' THEN {length}(n.input_snapshot->'public_source_grants')
            ELSE -1 END)
        OR (CASE WHEN a.artifact_type='subtitle' AND a.mime_type='application/x-subrip'
                          AND n.input_snapshot->>'subtitle_input_kind'='saved_text_and_timing' THEN 0
                 WHEN n.input_snapshot->'public_inputs' IS NULL THEN 0
            WHEN {json_type}(n.input_snapshot->'public_inputs')='array' THEN {length}(n.input_snapshot->'public_inputs')
            ELSE -1 END)
           <> (SELECT count(*) FROM {schema}artifact_source_uses u
               WHERE u.artifact_id=a.id AND u.source_access_kind='public_asset')
    )
)
AND NOT EXISTS (
    SELECT 1 FROM bounded b JOIN {schema}artifact_source_uses u ON u.artifact_id=b.id
    WHERE u.source_access_kind='public_asset' AND NOT EXISTS (
        SELECT 1 FROM {schema}project_public_asset_links l
        JOIN {schema}public_asset_publications p ON p.id=l.publication_id
        JOIN {schema}public_asset_publication_items i ON i.publication_id=p.id
        JOIN {schema}asset_versions v ON v.id=p.source_asset_version_id AND v.status='formal'
        JOIN {schema}source_use_subjects s ON s.id=u.source_subject_id AND s.artifact_id=i.artifact_id
        JOIN {schema}source_use_revisions r ON r.id=s.current_revision_id AND r.subject_id=s.id AND r.state='declared'
        JOIN {schema}artifacts a ON a.id=i.artifact_id AND a.deleted_at IS NULL AND a.storage_state='available'
        WHERE l.project_id=u.project_id AND p.source_project_id=u.source_project_id
          AND ({library_allowed})
          AND l.detached_at IS NULL AND p.status='available' AND p.withdrawn_at IS NULL
          AND replace(CAST(l.id AS text),'-','')=replace(u.access_basis->>'public_asset_link_id','-','')
          AND replace(CAST(i.id AS text),'-','')=replace(u.access_basis->>'publication_item_id','-','')
    )
)
