WITH permitted AS ({content_query})
SELECT i.artifact_id AS id, i.source_project_id AS project_id, a.artifact_type,
       a.storage_state, c.content_hash, c.mime_type, c.object_key, c.byte_size
FROM permitted c
JOIN {schema}public_asset_publication_items i ON i.id = {item} AND i.publication_id = {publication}
JOIN {schema}artifacts a ON a.id = i.artifact_id
WHERE {purpose} IN ('creation', 'export')
