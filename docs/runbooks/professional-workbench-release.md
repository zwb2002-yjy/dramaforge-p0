# 专业版发布验收 Runbook

## 产品路径

1. 新项目从项目大厅进入专业制作，不进入旧四阶段预算页面。
2. `/projects/:projectId/quick` 只作为兼容重定向，最终落到专业工作台。
3. 专业工作台必须能完成：场景 → 镜头 → 画布 → 资产 → 导演台 → 生产 → 审片 → OpenCut Manifest。

## 专业 API 合同

- `GET/POST/PATCH /projects/:id/assets`：资产卡与版本。
- `GET /projects/:id/assets/:assetId/versions`：历史版本。
- `PATCH /projects/:id/shots/:shotId/canvas`：正式画布版本。
- `POST /projects/:id/shots/:shotId/change-proposals`：结构化提案。
- `POST /projects/:id/professional/shots/:shotId/start`：专业无预算生产启动。
- `POST /projects/:id/professional/shots/:shotId/rerun`：专业无预算局部重跑。
- `GET/POST /projects/:id/experiments`：正式/实验分支。
- `GET/POST /projects/:id/shots/:shotId/annotations`：时间点/时间段批注。
- `GET /projects/:id/opencut-manifest`：正式线剪辑清单。
- `GET/PUT /projects/:id/shots/:shotId/director-board`：2D/粗 3D 导演台状态。

## 预算/计费边界

专业版不维护预算上限、价格估算、充值、平台账单或计费 Gate。ProviderOperation 可以保存供应商返回的原始成本字段用于审计，但所有价格和结算由 Provider 负责。

## 自动化验证

```powershell
cd backend
.venv\Scripts\python.exe -m alembic -c alembic.ini heads
.venv\Scripts\python.exe -m ruff check app tests alembic/versions
.venv\Scripts\python.exe -m pytest tests/unit -q

cd ..\frontend
npm run typecheck
npm run test
npm run build
```

## 外部证据

以下项目内自动化不能替代真实外部证据：

- Provider 真实图片/视频请求与有效请求快照；
- OpenCut 实际导入；
- Docker 干净环境安装、升级、重启恢复、备份恢复；
- 离线硬件链；
- 三名目标用户无人代操作验收。

只有这些证据绑定同一个 release commit 后，才可以标记发布完成。
