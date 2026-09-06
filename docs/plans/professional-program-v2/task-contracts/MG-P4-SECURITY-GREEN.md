# Task: Phase 4 Merge Gate B06 — Security filesystem-scan green on latest HEAD

## Status

- **State:** COMPLETE
- **Task id:** `mg-p4-security-green`
- **Program order:** … Phase 4 Merge Gate（证据审计 + B06 CI 已绿）→ **B06 Security filesystem-scan（本任务）** → Owner Gate 确认 → P4 Manual Production Alpha
- **Task boundary:** 只修 GitHub Actions Security `filesystem-scan`（trivy）失败；**不宣布 merge gate 通过**，不进入 P4。

## 现状事实（CI 证据确立）

- CI（`d04e23b`）全绿：`postgres-integration` 已真实运行（alembic upgrade head + integration 23 passed），backend-unit/static、platform-baseline（3 OS）、frontend、frontend-smoke、litellm-integration、policy 全部 success。
- Security 唯一失败：`filesystem-scan`（trivy 0.70.0, `--severity HIGH,CRITICAL --ignore-unfixed --format sarif --exit-code 1`）。
- 从 GitHub code-scanning SARIF 确认：唯一发现为 `backend/uv.lock` 的 **pytest 8.4.2 → CVE-2025-71176**（MEDIUM，CVSS 6.8，修复版 9.0.3；dev-only 依赖，本地权限提升/DoS 类）。尽管 severity 过滤为 HIGH,CRITICAL，trivy sarif + exit-code 组合仍使其失败。

## 修复策略（按优先序，取第一个可落地的）

1. **根因修复**：升级 pytest 至 `>=9.0.3,<10`，并同步升级 pytest-asyncio（0.25.3 约束 `pytest<9`，需 1.x，如 `>=1.4.0,<2`）；`uv lock` 后本地全量 unit + integration 必须保持通过。
2. **兜底（仅当升级破坏测试基础设施且修复不成比例）**：在仓库根增加 `.trivyignore`，写入 `CVE-2025-71176` 并附注释说明（dev-only、MEDIUM、不进入生产镜像）。

## Owned paths

- `.trivyignore`（若采用兜底）
- `backend/pyproject.toml`
- `backend/uv.lock`
- `docs/plans/professional-program-v2/task-contracts/MG-P4-SECURITY-GREEN.md`
- `docs/plans/professional-program-v2/gate-reports/PHASE4-MERGE-GATE-AUDIT-REPORT.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- 宣布 Phase 4 Merge Gate 通过（独立 Gate 决策，需 Owner 确认）。
- P4 实现、真实 Provider 付费调用、新功能开发。
- 修改 07 方案正文。

## Verification gate（本任务完成标准）

- 本地 `uv lock` 解析成功；`uv sync --locked` 成功。
- 后端全量 unit `746 passed`（升级后不得少于升级前）；PG 集成 `23 passed`（真实 PG）。
- 本地 trivy 0.70.0 复现 CI 命令后无 HIGH/CRITICAL（且无 MEDIUM sarif 残留导致 exit 1）。
- Security workflow 在新 HEAD 上 `filesystem-scan` 通过；B06 状态如实记录，不自行宣布 Gate 通过。
