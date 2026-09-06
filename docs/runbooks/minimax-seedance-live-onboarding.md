# MiniMax 与 Seedance 真实账号接入

**状态：** LIVE / 账号接入与首个付费探测操作手册  
**版本：** 1.0  
**日期：** 2026-08-17

本手册用于把真实 MiniMax 与火山方舟账号接入 DramaForge，并完成一个受控的视频图生视频探测。它不构成费用授权；每次付费探测、试拍、生产或修复仍须分别填写正数预算并获得 Owner 明确批准。

## 已冻结的接入合同

| 供应商 | 插件 / Profile | 默认视频模型 | 创建与查询方式 | 当前产品范围 |
|---|---|---|---|---|
| MiniMax | `minimax/minimax_cn_v1` | `MiniMax-H3` | `POST /v2/video_generation`，异步查询并下载 | 一个公网 HTTPS 首帧，768P，5 秒，比例继承首帧，不声明原生音频 |
| 火山方舟 | `volcengine/ark_cn_v1` | `doubao-seedance-2-0-260128` | `POST /contents/generations/tasks`，按任务 ID 查询 | 一个公网 HTTPS 首帧；音频、时长、多参考和可信素材能力尚未进入产品合同 |

Seedance 1.0 Pro 的旧目录项继续保留，避免既有绑定失效；新连接应优先选择 Seedance 2.0。模型 ID 是否对账号可见必须以当天账号探测结果为准。

## 凭证准备

1. MiniMax 准备按量付费 API Key，并确认账号可调用 `MiniMax-H3`。
2. 火山方舟准备北京区域的 Ark API Key，并确认账号已开通 Seedance 2.0、可见完整模型 ID `doubao-seedance-2-0-260128`。
3. 不要把 Key 发到聊天、截图、Git、Issue、命令历史或证据目录。优先在 DramaForge 首页的“模型供应商插件”面板输入；系统只写入加密凭据，界面不会回读。
4. `.env` 变量只作为单机运维备用。使用 Workspace BYOK 时保持 `MINIMAX_ENABLED=false`、`VOLCENGINE_ENABLED=false` 也不影响加密连接覆盖；不要把真实 Key 写入 `.env.example`。

## 明日操作顺序

### 1. MiniMax

1. 回到 DramaForge 首页 `/`，选择当前 Workspace。
2. 在“模型供应商插件”选择 `MiniMax · minimax_cn_v1`，确认 Base URL 为 `https://api.minimaxi.com`。
3. 输入真实 API Key，点击“保存加密 Key”。
4. 先运行不付费的“认证 / 模型目录”。如果返回 401/403 或目录中没有 H3，停止，不创建付费任务。
5. 在“视频模型”选择 `MiniMax H3 · MiniMax-H3`，创建视频绑定。
6. 按供应商当天价格填写“单次调用保守估算上限”，选择币种，确认后保存价格快照。
7. 准备一个已在 DramaForge 中可用的图像 Artifact ID。选择“视频图生视频”，填写该 ID 和仅覆盖一次探测的正数预算，获得 Owner 明确授权后再点击“授权并运行付费探测”。

### 2. 火山方舟 Seedance

1. 切换到 `火山方舟 · ark_cn_v1`，确认 Base URL 为 `https://ark.cn-beijing.volces.com/api/v3`。
2. 输入 Ark API Key，点击“保存加密 Key”。
3. 运行“认证 / 模型目录”。必须确认凭证有效，并在账号侧确认完整模型 ID `doubao-seedance-2-0-260128` 可调用；账号目录与静态目录不一致时，以账号实际可见完整 ID 为准并停止付费探测，先更新目录合同。
4. 在“视频模型”选择 `Seedance 2.0 · doubao-seedance-2-0-260128`，创建视频绑定。
5. 写入由账号账单/官方定价得到的单次保守价格快照。
6. 使用同一个已验证图像 Artifact ID 运行一次“视频图生视频”探测。只授权一次调用的预算，不从整片或修复预算中借用额度。

## 通过标准

- 连接显示已验证，凭证只显示“已配置”和密钥版本，不显示 Key 内容。
- 精确的视频模型绑定变为 `account_verified`，不是同供应商其他模型被连带验证。
- ProviderOperation 记录实际 provider、完整模型 ID、Profile、引用 Artifact ID/哈希、提交状态和远端任务 ID，不含 Key、签名 URL或原始私密素材。
- 任务成功后，视频被下载并物化为 DramaForge Artifact；只拿到供应商短期 URL 不算完成。
- 实际费用不超过本次授权，且价格/币种与账单口径一致。
- 代表性试拍通过人工时序/人物复核后，再记录质量证据并绑定到项目；能力探测成功本身不等于质量合格。

## 立即停止的情况

- 模型 ID 不可见、401/403、地区或账号权限不符。
- 供应商提交结果为 `unknown_submission`。先在供应商控制台按任务/账单对账，未经新授权不要重发。
- 价格未知、币种不一致、参考 Artifact 不可读取，或需要超出当前合同的音频、多参考、首尾帧、时长/分辨率参数。
- 任何页面、日志或证据文件出现 Key 或可复用下载凭证。

真实证据留存与 Gate 更新继续按 [`real-provider-evidence-preflight.md`](real-provider-evidence-preflight.md) 执行。
