"""Stable, content-free PostgreSQL fingerprints for backup and restore verification."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

CATALOG = """
SELECT n.nspname,c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY n.nspname,c.relname,a.attnum
"""

PENDING_IDENTITIES = """
SELECT 'node', id::text,project_id::text,status::text,idempotency_key,input_hash FROM node_runs
WHERE status IN ('queued','running','cancel_requested')
UNION ALL
SELECT 'operation',id::text,node_run_id::text,status::text,request_fingerprint,provider_operation_id
FROM provider_operations
WHERE status IN ('submission_started','submitted','running','unknown_submission')
ORDER BY 1,2
"""

PRIMARY_AUTHORITY = """
SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),owner.rolname,
       coalesce(p.proconfig::text,''),grantor.rolname,coalesce(grantee.rolname,'PUBLIC'),
       a.privilege_type,a.is_grantable
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
JOIN pg_roles owner ON owner.oid=p.proowner
CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
JOIN pg_roles grantor ON grantor.oid=a.grantor
LEFT JOIN pg_roles grantee ON grantee.oid=a.grantee
WHERE n.nspname IN ('app','public') AND p.prosecdef
ORDER BY 1,2,3,4,5,6,7,8,9
"""


def fingerprint(rows: Iterable[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()
