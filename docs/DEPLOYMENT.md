# DEPLOYMENT — 部署权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

机构版D7目标扩展见本文末尾。现有部署方式保持Owner N03指定的Windows/现有WSL2/Docker，
目标合同不代表服务已升级；设计阶段不据本文命令启动业务环境，D8后依主合同/N11及对应准入实际执行。

## Supported deployment shape

The default `docker-compose.yml` is the current `dramaforge-dev` topology. Local
images are built from current source through `docker-compose.build.yml`; future
release bundles supply immutable image references. It publishes only the unprivileged Nginx gateway on
`127.0.0.1:8080`, and contains no source `build` instructions. PostgreSQL,
Redis, MinIO, LiteLLM, the API, dispatcher and workers remain on the Compose
network. A packaged-release host needs Docker Compose v2; it does not need
Python, Node.js, or a compiler. The source-development setup below invokes
`scripts/init_env.py` and therefore needs Python for that step.

This topology is intended to behave the same with Docker Compose v2 on Linux,
Windows Docker Desktop and macOS Docker Desktop. The authoritative CI quality
gate builds dedicated quality images from the candidate source and locked dependencies.
The release path builds production images from that same candidate; a release claim still
requires the candidate's Docker smoke test and evidence on each claimed host.

## Current development start

Generate a unique local environment, set the exact source commit, and build the current images:

```text
python scripts/init_env.py
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

The project is unreleased. Retain old instance volumes separately only while recovery or
delivery still needs them; once that purpose ends, follow DEVELOPMENT's lifecycle and
authorized cleanup scope. Current startup does not reuse another worktree, old image tags
or queued provider tasks.

### Frontend hot reload and backend identity

A frontend source bind mount or Vite hot reload updates only browser code. It does not
rebuild or replace the API, dispatcher, workers, or database migrations. After a change that
requires a new API, build the current images, apply the current migration chain, and update
the application services together, using the same source identity. Preserve credentials,
volumes and existing execution records; never resubmit old Provider operations during rollout.

When a task claims that an affected workflow is fixed in a deployed local instance, check
`/health` through its actual browser gateway and compare `source_commit` with the deployed
image identity. Check the dispatcher/workers involved in that workflow and exercise the
affected API from that page; a full-stack rollout must verify all application service identities.
Source tests or frontend hot reload alone do not establish that the running backend has the
change. A source-only fix follows DEVELOPMENT's risk-based checks and makes no deployment claim.

## Future packaged release start

Download and extract the complete online bundle from one GitHub Release. On
Windows PowerShell run:

```text
.\install.ps1
```

On Linux or macOS run:

```text
chmod +x install.sh
./install.sh
```

The installer verifies `release.env`, pulls the immutable release images,
generates unique secrets by running `app.install_env` inside the backend image,
and starts the stack with `--no-build`. It never invokes a host package manager.
It first requires `migrate`, `database-bootstrap`, and `litellm-bootstrap` to
exit successfully, then checks the health of the long-running services without
restarting those initialization jobs. A failed initialization or unhealthy
runtime prevents the installer from reporting readiness.
Initialization also generates a separate `DIRECTOR_CHECKPOINT_PASSWORD` and
its local `DIRECTOR_CHECKPOINT_DATABASE_URL`; the release workflow supplies
the checkpoint password explicitly when validating and smoke-testing Compose.

Open `http://localhost:8080`. A clean instance lets the first person create the
Owner account. Public registration is closed after that bootstrap unless an
operator explicitly enables it.

On upgrade the installer updates only the release version, source commit and
image identities in `.env`. It preserves database credentials,
`BYOK_FERNET_KEY`, and Provider settings. Back up `.env` and the named volumes
before an upgrade; replacing the Fernet key makes saved Provider credentials
unreadable.

PostgreSQL connections use `DATABASE_SSL=false` for the local Compose network.
Set it to `true` when the database endpoint requires TLS; the setting is passed
to the API, dispatcher and Workers and is not encoded in application code.

## Complete offline install

Use the architecture-specific offline release bundle, not the online bundle.
It contains `images.tar.gz` with the complete runtime image set. Extract it into
a directory and run the installer from that same directory (the archive holds the
installer, `release.env`, the Compose files and the image archive at its top
level):

```text
.\install.ps1 -Offline
```

or:

```text
./install.sh --offline
```

The installer imports `images.tar.gz` and layers `docker-compose.offline.yml`,
whose `pull_policy: never` contract covers every service. Offline installation
means no registry access during installation. Cloud media Providers still need
network access and user credentials; this release does not claim that the full
creative workflow runs offline.

## Network and TLS boundary

The local default binds only to loopback and does not provide TLS. To place the
application behind an external HTTPS reverse proxy, set:

```dotenv
APP_ENV=production
DRAMAFORGE_BIND_ADDRESS=127.0.0.1
DRAMAFORGE_PORT=8080
DRAMAFORGE_PUBLIC_ORIGIN=https://drama.example.com
SESSION_COOKIE_SECURE=true
```

Terminate TLS at the reverse proxy and forward to `127.0.0.1:8080`. Do not
publish PostgreSQL, Redis, MinIO, LiteLLM or the API. Setting the bind address to
`0.0.0.0` exposes an unauthenticated HTTP boundary and is not a recommended
internet deployment.

## Provider connection security boundary

DramaForge Provider HTTP clients (including poll/cancel) connect directly with
`trust_env=False`; `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` do not route these
calls. These variables are available to Proxy-side upstream access and build
tools. `PROVIDER_TRUSTED_HTTP_NETWORKS` authorizes only declared private HTTP
endpoints; it does not configure a forward proxy. HTTP connection pools belong
to the API/worker event loop and close at shutdown. Headers and cookies remain
local to each request client.

| Hop | Routing and trust policy |
|---|---|
| Application → media Provider (create/query/cancel/discovery) | Direct guarded transport; environment forward proxies disabled. Private HTTPS needs explicit private policy; plaintext LAN needs the exact trusted IP network. Neither setting trusts redirects or a forward proxy. |
| Worker → returned media URL | Direct public HTTPS with validated/pinned DNS, no redirects or environment proxy; bounded file transfer checks MIME, size and hash. A trusted private Provider API does not grant private download URLs access. |
| Application → internal LiteLLM data/management plane | Explicit deployment address/credentials, environment proxies disabled; no direct upstream fallback. |
| LiteLLM → configured upstream | Separate Proxy namespace ACL and upstream configuration policy; application Provider allowlists do not authorize this hop. |

The real-socket HTTP pool regression poisons `HTTP_PROXY` while exercising an
explicitly trusted LAN endpoint; the media-resource gate poisons `HTTPS_PROXY`
while downloading real TLS fixtures. The LiteLLM integration gate independently
tests its restricted network namespace. Enterprise forward proxies and proxy
authentication are not supported by enabling environment variables; they require
a separate SSRF policy and connection-time enforcement design.

The public Nginx gateway limits login and registration together to five requests
per minute per remote address, allowing a burst of five, and returns 429 on
excess requests with `AUTH_RATE_LIMITED` Problem Details and `Retry-After: 12`.
The quota uses the TCP peer address; client-supplied `X-Forwarded-For` / `X-Real-IP`
never select a different quota. Uvicorn's shipped commands disable proxy headers.
If an additional reverse proxy is placed before this gateway, its clients share
the proxy's quota by default. Trusting a separately controlled proxy requires an
explicit Nginx real-IP policy for its exact addresses/networks and a forwarding-chain
test; do not enable blanket header trust or publish the internal API as a bypass.
Unknown and inactive accounts perform the same password KDF as a known account,
and failed logins have the same public error. `/metrics` is available on the internal API listener; Nginx
does not forward it. `/worker/tick` requires development mode and the worker
token; production and test reject it.

Workspace-supplied Provider connections send their encrypted credentials to
the configured `base_url` through the server-side guarded transport; a supported
media connection with explicit `auth_mode=none` sends no Authorization header.
New text connections instead store the internal Proxy address and restricted
data credential. Their upstream address/key are registered through the existing
workspace management API and stored by the Proxy, never used as an application
direct-call fallback.
The boundary is layered — write-time static validation, then connection-time
egress enforcement:

- `PROVIDER_BASE_URL_ALLOW_PRIVATE` (default `false`): connection base URLs
  must be public HTTPS origins. Private/loopback IP literals are rejected
  unless an operator explicitly sets this to `true` for an authenticated
  self-hosted private deployment. Link-local, multicast, unspecified,
  reserved and shared (CGNAT) destinations are rejected regardless — they
  are credential-exfiltration primitives, not private deployments. Reserved
  addresses that Python also classifies as private (for example `240.0.0.1`)
  stay blocked even when private deployments are authorized.
- `PROVIDER_TRUSTED_HTTP_NETWORKS` (default empty): scoped plaintext-HTTP
  trust for local model deployments, e.g.
  `PROVIDER_TRUSTED_HTTP_NETWORKS=172.18.6.0/24` then a connection
  `base_url` of `http://172.18.6.80:30020`. HTTP is accepted only for IP
  literals inside a declared network; a whole-address-space entry (`/0`) is
  rejected at startup. Named hosts over HTTP are rejected — terminate TLS on
  a reverse proxy, or address the service by IP. This is deliberately a
  separate, narrower trust than the global private opt-in above.
- Connection-time egress enforcement: every provider TCP connection (probe,
  submit, poll, cancel) resolves its destination, classifies every resolved
  address with the same rules, and opens the socket against one validated
  address. A hostname that resolves to a private or reserved target fails
  closed before credentials leave the process; DNS-rebinding cannot redirect
  an in-flight connection because the socket is pinned to the validated
  address. Connections saved under an earlier policy are re-validated on
  every new socket.
  DNS resolution and TCP attempts share the connect timeout. If an address
  cannot establish a socket, other addresses in the same validated answer
  set may be tried before any HTTP bytes are sent; no request is replayed.
  Every request also rechecks the URL before entering the pool, including old
  stored URLs; the private opt-in alone cannot authorize plaintext HTTP.
  Historical workspace text probes use this guard too. The operator-configured
  internal LiteLLM Proxy URL retains its separate deployment trust boundary.
- `REFERENCE_PUBLIC_BASE_URL` (default empty): public HTTPS API origin used
  for short-lived signed Provider references. Models whose wire contract
  consumes public URLs (Ark, MiniMax, Agnes video contract revisions) issue
  these grants from the Worker; without this setting those reference-bearing
  generations fail closed with `REFERENCE_DELIVERY_NOT_CONFIGURED` instead of
  silently degrading.

## PostgreSQL connection budget

`docker-compose.yml` sets `max_connections=160` on PostgreSQL and sizes each
service role's engine pool explicitly: api `DB_POOL_SIZE=20` +
`DB_MAX_OVERFLOW=10`, dispatcher `3+2`, worker-default `10+5`,
worker-director `4+2`, worker-heavy `5+5`. At one process per listed role,
the application engine ceilings sum to 66. The remaining capacity must also
cover Director checkpoint pools, migrations, maintenance, PostgreSQL reserved
slots and every other client; `160` is a deployment setting, not a general
capacity guarantee.

Scaling changes the arithmetic: every additional API or Worker replica, a
larger checkpoint pool, or extra administrative clients (analytics, manual
`psql` sessions) consumes from the same `max_connections` budget. Recompute
the per-role values (and raise `max_connections`) before adding replicas —
exhaustion surfaces as pool checkout timeouts, not as queue backlog.

## Health and lifecycle

```text
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
docker compose ps
docker compose logs --tail 200 api dispatcher worker-default worker-director worker-heavy
docker compose down
```

运行中的 Compose 服务统一使用 `json-file` 日志驱动并配置轮转（每容器 `max-size: 10m`、
`max-file: 3`），不会无限增长；需要长期保留的内容应显式导出，不能依赖容器日志充当
业务事实或审计记录。

`/gateway-health` checks the gateway process. `/health` is proxied to the API
and includes its database readiness. Queue processing should additionally be
checked from service status and worker logs: `worker-default` consumes
`dramaforge:default`, `worker-director` consumes `dramaforge:director`
(Director turns, event intake and wakeup replay), and `worker-heavy` consumes
`dramaforge:heavy`. Recoverable work is republished by the resident
`dispatcher` and by the Director worker's startup recovery.
Provider reconciliation runs in an independent dispatcher loop, not a heavy-queue cron job;
media execution still uses the existing queue. Apply migrations through the
candidate head (see [DATA_MODEL.md](DATA_MODEL.md); confirm with `alembic heads`) before
updating the dispatcher and media workers. This rollout is not implied by a source-only push.

The current unreleased schema has a one-way cleanup head (see [DATA_MODEL.md](DATA_MODEL.md)).
Use a fresh development database and retain old environment volumes separately. Do not translate
old queued requests, relabel old image identities, or stamp past unapplied migrations.

PostgreSQL, Redis, MinIO and the LiteLLM database use `restart: unless-stopped` plus bounded
startup health periods. The API, dispatcher and every Worker wait for PostgreSQL health and
the completed database bootstrap, then also restart unless explicitly stopped. The frontend
waits for API health. This ordering prevents a surviving gateway from presenting an API that
started before its DNS/database dependencies recovered after a Docker restart.

Director health uses `python -m app.workers.healthcheck` rather than importing
all WorkerSettings/jobs for the Arq CLI. It checks the configured queue's nonempty
Redis heartbeat plus a positive TTL of at most 3,601,000ms (not Redis PING), with
no retries and a 3-second total probe deadline; Docker's timeout remains 5 seconds.
Arq's existing 3600-second refresh / 3601-second expiry window is unchanged. This
is **queue-level liveness, not per-process readiness**: another worker on the same
queue can maintain the heartbeat. Check worker logs and actual job progress when
diagnosing an individual process.

The LiteLLM process shares the network namespace of `litellm-network`, which
reuses the backend image and has only the NET_ADMIN capability required to
install its own default-deny rules. The Proxy has no capabilities. This does
not alter the host firewall or media workers. Exact authorized origins and
trusted private/plaintext CIDRs come from `LITELLM_EGRESS_ALLOWED_ORIGINS` and
`LITELLM_EGRESS_TRUSTED_NETWORKS` JSON lists; defaults allow no model upstream.
All DNS answers are validated and pinned to IP/port rules until the namespace
is recreated. Recreate the guard and Proxy together when grants or DNS change.
Only the optional `docker-compose.dev.yml` overlay publishes port 4000 on the namespace owner,
never the shared Proxy. The default topology and build-only overlay do not publish that port.

Keep `LITELLM_SALT_KEY` stable with the Proxy DB backup. For an old database
encrypted using the Master fallback, preserve and verify the original effective
salt before enabling DB management. Never generate a replacement salt over
existing ciphertext. The single-worker pinned Proxy rejects duplicate YAML/DB
aliases, request-level transport overrides and shadow calls; HTTPX, requests and
aiohttp do not follow redirects. Prisma's local control channel uses fixed
port 4001 rather than a broad loopback port grant. Admin and data keys remain
separate. The one-shot trusted `litellm-bootstrap` provisions restricted service
keys without upstream calls or secret output. Only the API receives the model
management key; generation workers do not. The API keeps existing workspace
ownership/RLS and CSRF enforcement, while the Proxy enforces immutable managed
targets and monotonic credential revisions. This is restricted credentials in
the same API process, not full management-process isolation.

New text execution requires a ready workspace-owned managed reference. Keep
historical connection and credential revisions, BYOK key versions, original
resume tokens and frozen contracts. Static YAML aliases remain isolated from
new managed aliases and cannot be selected for new production. Do not infer
an old alias's physical deployment from its name or automatically remap an old
profile. A queued old plan without its required identity stays blocked for
explicit review; a possibly submitted operation is never resubmitted.

Back up both application and Proxy databases with their schema/image versions
and matching encryption keys before migration. The current head is recorded
in [DATA_MODEL.md](DATA_MODEL.md). Model reference/auth migrations refuse a
downgrade when it would discard retained references or no-auth facts; an
application rollback must still understand the data already written. Restore
and verify a separate copy first. Preserving a volume without its effective
SALT/BYOK keys is not a usable rollback.

Schema upgrade and catalog publication are separate maintenance steps. New
file-backed contracts are not inserted automatically by the API or by replaying
old frozen seed migrations. With the matching source and backend image, compare
the catalog first, then explicitly apply it using the maintenance database role:

```bash
docker compose --profile maintenance run --rm --entrypoint python maintenance /workspace/scripts/sync_model_catalog.py
docker compose --profile maintenance run --rm --entrypoint python maintenance /workspace/scripts/sync_model_catalog.py --apply
```

This appends exact contract revisions and synchronizes publication state. An
existing identity with a different hash is rejected; historical JSON, hashes,
Bindings and execution identities are never rewritten. Ordinary API/Worker
roles remain read-only for the catalog.

Media protocol admission is independent of text Proxy health. Choose only an
installed versioned wire contract; service URL/model ID remain connection and
Binding data. Discovery, contract checks, revision-specific generated Artifacts,
browser playback and quality review are separate evidence. An unknown response
shape, unsupported encoding or false duration must block the corresponding
service acceptance rather than silently transcode, change the request or certify
advanced capabilities. Live generation requires its own current Owner contract;
mock/contract gates do not authorize a live create or a remote service restart.

Named volumes `postgres_data`, `minio_data`, and `litellm_db_data` contain
persistent state. `docker compose down` preserves them; do not use `--volumes`
unless permanent data deletion is intended and backups have been verified.
Backup and restore-verify run through the profiled maintenance service, whose
entrypoint is `scripts/p0_backup_restore.py` (see
[DEVELOPMENT.md](DEVELOPMENT.md)).

## Director runtime engine

`DIRECTOR_RUNTIME_ENGINE` only accepts `langgraph`. Both API and worker-director receive
`DIRECTOR_CHECKPOINT_DATABASE_URL`; the dedicated checkpoint password is required and
`database-bootstrap` provisions the private schema role. Worker startup verifies the store.
Manual production remains available independently of the Director worker.

## AIOS/AISphere handoff boundary

AIOS/AISphere support has not been verified. This repository provides the standard
Docker Compose topology, not a custom or certified platform manifest. An integrator
must map that topology to the platform's official schema, inject secrets without
committing them, preserve the named volumes, route the single HTTP entrypoint and
verify installation, first-owner bootstrap, health and backup/restore in the target
environment before claiming compatibility.

## 机构版部署与恢复目标（D7设计，未实施）

Owner N03要求保留现有本地方式：Windows + 当前WSL2/Docker Desktop Linux容器，浏览器入口沿127.0.0.1:8080。
Ubuntu是现有WSL发行版，不把应用Bookworm/Alpine基础镜像强制换Ubuntu；不新增桌面客户端、第二Runtime或消息集群。
API、PostgreSQL、Redis、MinIO、Proxy与Workers继续内网服务；对外LAN/TLS或正式发布另行授权，设计原型4179不是业务部署入口。
目前Docker引擎不可达，实例Schema/活动任务仍未知，不能据源码compose声称目标机已经通过。

### 构建、处理器与执行隔离

沿现有build/quality/release镜像链与lock文件；代码/SHA、镜像ID、迁移head、目录合同、Parser/模型权重版本共同记录。
D4的Poppler/Tesseract/whisper.cpp及openpyxl/defusedxml在同一受控构建中锁定，已有FFmpeg/Pillow/OpenCV复用；
不让首次业务请求临时pip安装、下载权重或拉取未知容器。离线包包括必需二进制/权重的许可证、来源与实际hash，
构建时验证，缺失按能力不可用报告，不静默转云。D4处理档由API/网关/Worker同源配置并做边界测试。
Parser以非root运行，仅任务私有spool可写；原件只读，不挂载宿主任意目录、不执行文档宏/外部链接。
每进程时间/内存/输出/并发限制及清理只作用本任务资源；超限保留原件/已完成块和明确覆盖缺口。
默认本地重处理并发1，设备吞吐通过I0/I4实测后公布；不将此值当GPU/CPU性能保证。

worker-director在O5路径只通过统一Invocation/外发准入访问内部受管LiteLLM，不开放媒体Provider直连。
已有Proxy network guard继续为真实下游、代理与重定向实施默认拒绝；可信本地位置依据部署/网络合同核验，
不是看到localhost或Docker服务名就认作本地推理。媒体仍由原Production worker经冻结Binding和网络守卫发送。
本地资料处理器没有隐式网络路径；Vision/云端语义研究沿单独显式模型与许可，不能借Parser下载绕过。
每类实际出口都要有拒绝零发送的测试；只更新compose环境变量不等于接线验收。

N06未来实施清理已盘点的TTS_ENABLED、TTS_ENGINE、TTS_VOICE、TTS_PROXY（实际.env仅读取了键名，未输出值），
连同config/Compose透传/env示例/edge-tts锁定依赖/活动适配器/UI默认及测试消费者一起替换。
当前本次没有删除上述配置。新配音从项目或单次明确Binding取身份，无配置提示设置，不fallback到Edge/eSpeak。
旧Edge Spec/Operation/Artifact仍能解释为历史身份；没有可恢复远端ID的未知旧调用不重发、不装回SDK制造一次“恢复”。
本地空对白静音与本地ASR不属于TTS模型兜底。现有其它连接凭据、网络设置和授权不因这项清理被重写。

### 维护窗口与升级顺序

以下是未来运行规程，不是当前执行授权。未发布实例也必须先确认真实卷/数据库/活动任务，不能用另一工作树的镜像顶替。
1. 只读盘点实际Compose project、服务镜像ID/SHA、主库/检查点/Proxy库身份、schema head/角色、对象桶与未决操作。
2. 通过拟增的服务端运行准入模式进入maintenance：阻止新创作写入与新模型Create，返回明确维护原因；
   已发调用只收敛原回执。待写事务/上传对象安全落地后，在明确维护窗口暂停dispatcher/workers及Proxy配置变更。
3. 完成下文一致备份及隔离恢复验证，再执行已批准迁移；迁移使用专用owner，API/Worker永不成为owner/BYPASSRLS。
4. 同候选API/dispatcher/worker启动到recovery_only：允许授权只读检查及原任务poll/download/回执落库，
   拒绝新Create、自动研究和自动补生成。旧未知身份保持；不重放旧Redis队列来假装恢复。
5. 核对RLS、控制epoch/checkpoint、队列重建、配置/准入与媒体读取后才开放normal。真实模型/资料外发/发布分别遵守硬门。

`normal|maintenance|recovery_only`是待实施的运行准入合同，现有服务尚无该保证；不能现在设置一个同名环境变量就当安全门已启用。
目标配置为Settings.runtime_admission_mode / RUNTIME_ADMISSION_MODE，默认normal，未知值启动失败。
它是部署端只读配置，HTTP/队列/模型输入不能覆盖。改变模式须按维护规程重启对应进程并逐个核对，
不是修改.env后假定所有旧Worker已经改变。每个API/dispatcher/worker需报告自身mode、配置hash和进程就绪身份，
不能用同队列的共享心跳替一个未切换进程证明ready；不新增业务状态表。
normal仍逐次核验用户门/策略；maintenance禁止新业务接纳并将写者收敛到静止；
recovery_only只允许原已开始操作的查询、下载和注册恢复策略补原证据，不能为尚未开始的步骤新建NodeRun/Operation。
已开始本地操作仅在同一冻结身份下恢复；身份/输入不足就等待，不借恢复模式补新制作。
它只收紧服务端入口和Worker新发送，不代替项目策略/用户批准，也不引入第二任务状态源。
Redis只承担唤醒/通知，持久进度来自PG/Outbox/RuntimeControl；恢复从DB验证原事实再重建通知，不重建已发操作。
旧Turn状态版本按O6处理，未知旧运行不能静默升级为新checkpoint格式；新版本旧写者混跑不在本期无损升级承诺内。

### 备份现状与必须补强的合同

已实际读取scripts/p0_backup_restore.py：当前备份一个settings.database_url的pg_dump和一个MinIO桶，
清单校验对象hash并用Fernet加密；restore-verify目前以URL字符串/桶名不同判断隔离，使用pg_restore --clean，
容器分支只从目标DSN取database名；恢复结果主要是public表数量和对象数量。
因此当前脚本不证明Proxy独立库已备份，也不证明任意目标URL不会被容器分支解析到错误实例，
更不证明恢复后业务角色/检查点/外部副作用身份正确。本任务不运行restore，不把现状称为完整机构恢复能力。

继续扩展同一maintenance服务/脚本，目标bundle_schema_version=2，采用下文restic快照承载，不设计自制密码算法：
- manifest列出主库、检查点实际数据库/私有schema、Proxy数据库（按真实同库身份去重）、全部需要的对象桶、
  应用/Proxy部署ID、镜像及schema版本、原操作未决摘要与对象/备份文件hash。检查点默认在主库不等于所有配置都同库。
- 备份在已验证写入静止窗口完成，PG一致快照与MinIO清单属于同一窗口；不将分别成功的任意时刻dump拼成一致恢复点。
  每个对象再次确认大小/hash，记录遗漏为失败而非跳过。包含源原件、生成媒体及不可变研究/公开引用/导出依赖。
- BYOK密钥、Proxy有效SALT/管理身份与备份解密Key的恢复条件单列；敏感值不写明文manifest/日志/命令展示。
  必需秘密经受控独立保管或加密恢复材料提供，备份解密Key不装进其自身密文作为唯一副本。
  不生成新SALT去“修复”旧密文；验证使用合成凭据/本地解密，不请求真实Provider。
  当前会话/CSRF采用SESSION_SECRET签名（shared/security.py已核对），恢复目标生成新的会话签名密钥并要求重新登录，
  不让备份时的旧cookie自动进入恢复实例；这不改变BYOK/Proxy解密密钥，也不改源实例秘密。
- 现有一次性Fernet写入不作为v2正常路径；旧v1只保留历史解密/检查用途。restic按其自身格式处理数据块，
  包装脚本流式读对象并落受限staging，不再read_bytes整个tar。目标机仍测实际峰值内存/磁盘及完整保护集，
  空间不足或处理失败拒绝本次备份，不截断、跳过或宣称固定低内存SLA。

恢复目标使用明确的多资源target-config（计划新增--target-config参数，现有CLI尚不支持），
将app/checkpoint/Proxy和对象存储分别映射到隔离目标及凭据引用。旧双参数示例只描述当前单库工具，
未来替换所有调用方与测试，不以旧接口静默忽略v2多库成员。v1历史归档可校验/读取但缺项必须明示，不能自动称完整恢复。
恢复前核验实际数据库服务器/cluster身份、database身份与名称、容器映射和桶endpoint+bucket，
不能只比较DSN字符串；容器目标须与完整DSN指向同一实例，否则拒绝。拒绝目标等于任何源资源，
拒绝非空/无明确本任务所有权的库或桶；默认使用新隔离资源，不让--clean覆盖已有业务对象。
路径/压缩包成员与认证校验保留，解密失败/错hash/缺成员立即停止，不吞异常重建空表。

恢复后必须验证：Alembic与checkpoint schema、角色/GRANT/FORCE RLS、全部对象hash、私有/公共权限，
Run/Turn/Flow/Invocation/Operation/Artifact身份，Timeline/Export版本和所有未决远端ID。
运行角色必须非owner/NOBYPASSRLS，pg_restore --no-owner不能把应用角色顺手变为全表owner。
以合成任务演练恢复队列、失去通知、Worker重启与未知提交；断言外部Create计数不增加。
真实库恢复/切换仍单独批准，隔离恢复成功不授权覆盖现有实例，也不授权抹掉备份后发生的已计费事实。

### 备份容量方案冻结：maintenance内restic（D7工程选择，未安装）

采用restic 0.19.1官方Linux amd64二进制，压缩发布件`restic_0.19.1_linux_amd64.bz2`的官方SHA-256为
`f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c`。
这是已读取的[官方发布资产元数据](https://github.com/restic/restic/releases/expanded_assets/v0.19.1)，
不是已下载验证；构建时还须对实际字节和签名校验并绑定镜像。目标架构不匹配时拒绝使用，不临时self-update。
工具只打入现有maintenance所用镜像/quality镜像，不全局安装、不加常驻服务、不改变业务数据库事实。
已有Fernet仅保留历史v1读取，正常新写只有一个restic路径，归档业务格式与restic repository版本分别标明。

参考已读取的官方[仓库准备](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)、
[格式与加密](https://restic.readthedocs.io/en/stable/100_references.html)、
[完整性检查](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)及
[恢复](https://restic.readthedocs.io/en/stable/050_restore.html)。只依赖其成熟存储/加密/快照机制，
DramaForge仍负责多库一致性、应用身份、权限和恢复目标校验，不能用工具名称代替这些验证。

v2包装流程：
1. 只支持显式挂载的本地repository目录；拒绝云端/SFTP/S3 repo URL、任意用户拼接restic参数及仓库嵌套源目录。
   输出介质独立于业务源卷，密码通过只读secret文件传入，值不进入CLI日志；实际介质与秘密保管由部署配置指定。
2. 按前述维护窗口，在0700的本任务staging逐流写主库/检查点/Proxy dump、对象和bundle.json清单。
   每个进程return code、对象数量/字节/hash核对通过后才封闭staging；不用会隐藏上游失败的stdin管道打包。
   备份不提供exclude/任意子集，所有必需component都在同一bundle中。磁盘预检/写入超限失败均不会标verified。
3. 从封闭目录执行一次restic backup并记录完整snapshot ID；仅exit0可继续。exit3的部分快照和其它失败
   一律不发布为可恢复点，即使库里出现snapshot也不算成功；保留受限失败证据，不自动forget/prune共享仓库。
4. 执行`check --read-data`并验证snapshot中清单/必需成员，不能只做默认元数据check或随机抽样替代全验。
   成功回执包含repository ID、snapshot ID、bundle hash、源部署/SHA/schema、组件数量和核验结果，不包含源内容。
5. 恢复明确指定完整snapshot ID（禁止latest），先校验备份回执与bundle，再restore到全新空staging，
   禁止--delete/原地覆盖。按业务清单逐文件hash/数量核对后，才进入已核实隔离数据库/桶的还原流程。

v2只在maintenance容器内用PG客户端按完整目标DSN连接，不启用当前DRAMAFORGE_PG_CONTAINER的“只取database名”分支。
真实源/目标身份核验仍必须执行；相同服务器/数据库的别名不能通过字符串不同伪装隔离。
原备份默认恢复会覆盖现有文件的行为不向用户裸露，由包装脚本强制新空目标且校验所有权。
restic仓库损坏、缺对象、密码错误、一个数据库dump失败、暂停窗口不成立、恢复目录非空、目标复用源等都必须失败关闭。

未来maintenance CLI目标为`backup --repository <local-dir> --password-file <secret-file> --report <owned-path>`及
`restore-verify --repository <local-dir> --snapshot <full-id> --password-file <secret-file> --target-config <file> --report <owned-path>`。
这是待实施合同，现有脚本尚不接受这些参数；实际调用仍须满足当时授权，本文不要求现在运行。
多库和完整对象staging仍需要磁盘容量，restic并不消除该要求；I0/I10以实际保护集验证空间与时长。
容量的架构选择已收敛，设备容量/真实恢复证据仍待实施，不把设计选择标成运维已通过。

### 目标机部署验收

I0/I10记录Windows版本、WSL发行版/版本、Docker/Compose、CPU/RAM/磁盘与可选GPU实际能力；不预填未知参数。
验证浏览器通过网关登录、三作品流程、资料格式/研究/共享隔离、语音默认、审片/导出、服务重启及备份恢复。
健康HTTP/Arq队列心跳只是存活证据，还需看实际已持久任务推进；同队列另一个Worker不能替本进程ready。
Provider未知提交/来源撤回/Proxy配置漂移/网络中断/进程中止用隔离合成任务验证，真实模型调用仍另行授权。
LAN开放、生产部署与发布仍受主合同独立硬门，N11统一工程不自动豁免；不能把原型预览或Full当目标机部署验收。
