-- Return aggregates only, scoped from the authenticated origin to the same Owner.
WITH RECURSIVE owned(id) AS (
    SELECT p.id FROM {schema}projects p JOIN {schema}workspaces w ON w.id=p.workspace_id
    WHERE w.owner_user_id={actor} AND p.deleted_at IS NULL
), origin AS (
    SELECT s.id,s.file_revision_id,s.artifact_id FROM {schema}source_use_subjects s
    JOIN {schema}projects p ON p.id=s.project_id JOIN owned o ON o.id=p.id
    WHERE s.id={subject} AND p.id={project} AND p.id={active_project} AND p.workspace_id={workspace}
), descendants(subject_id,depth) AS (
    SELECT id,0 FROM origin UNION
    SELECT next.id,d.depth+1 FROM descendants d
    JOIN {schema}artifact_source_uses u ON u.source_subject_id=d.subject_id
    JOIN owned o ON o.id=u.project_id
    JOIN {schema}source_use_subjects next ON next.project_id=u.project_id AND next.artifact_id=u.artifact_id
    WHERE d.depth<33
), bounded AS (SELECT * FROM descendants LIMIT 1025),
media(id) AS (
    SELECT artifact_id FROM origin WHERE artifact_id IS NOT NULL
    UNION SELECT u.artifact_id FROM bounded b JOIN {schema}artifact_source_uses u ON u.source_subject_id=b.subject_id
    JOIN owned o ON o.id=u.project_id
), base_research(id) AS (
    SELECT c.research_revision_id FROM origin s JOIN {schema}research_citations c
      ON c.project_id={project} AND c.file_revision_id=s.file_revision_id
    UNION SELECT r.research_revision_id FROM origin s JOIN {schema}research_analyses a
      ON a.project_id={project} AND a.file_revision_id=s.file_revision_id
    JOIN {schema}research_analysis_results r ON r.project_id=a.project_id AND r.analysis_id=a.id
), research(id,depth) AS (
    SELECT id,0 FROM base_research UNION
    SELECT r.id,y.depth+1 FROM research y JOIN {schema}research_result_revisions r
      ON r.project_id={project} AND coalesce(r.restores_revision_id,r.accepts_revision_id,r.base_revision_id)=y.id
    WHERE y.depth<33
), research_bound AS (SELECT * FROM research LIMIT 1025),
impacts(kind,id) AS (
    SELECT 'output',u.id FROM bounded b JOIN {schema}artifact_source_uses u ON u.source_subject_id=b.subject_id
    JOIN owned o ON o.id=u.project_id WHERE u.project_id<>{project}
    UNION SELECT 'library',l.id FROM media m JOIN {schema}public_asset_publication_items i ON i.artifact_id=m.id
    JOIN {schema}project_public_asset_links l ON l.publication_id=i.publication_id AND l.owner_user_id={actor}
    JOIN owned o ON o.id=l.project_id WHERE l.project_id<>{project} AND l.detached_at IS NULL
    UNION SELECT 'knowledge',r.id FROM research_bound y JOIN {schema}knowledge_source_links s
      ON s.research_revision_id=y.id AND s.project_id={project} AND s.owner_user_id={actor}
    JOIN {schema}knowledge_revisions old ON old.id=s.knowledge_revision_id
    JOIN {schema}project_knowledge_references r ON r.knowledge_entry_id=old.entry_id AND r.owner_user_id={actor}
    JOIN {schema}knowledge_revisions pin ON pin.id=r.knowledge_revision_id AND pin.number>=old.number
    JOIN owned o ON o.id=r.project_id WHERE r.project_id<>{project} AND r.detached_at IS NULL
)
SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM origin) THEN -1
    WHEN EXISTS(SELECT 1 FROM bounded WHERE depth>32) OR (SELECT count(*) FROM bounded)>1024
      OR EXISTS(SELECT 1 FROM research_bound WHERE depth>32) OR (SELECT count(*) FROM research_bound)>1024 THEN -2
    ELSE (SELECT count(*) FROM impacts) END
