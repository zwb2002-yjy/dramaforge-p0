# V1_STATUS — 当前 V1 / 发布状态

Status: current  
Date: 2026-09-16  
Branch: `dev` = `d2c7655b452714c540aaea36cf08de285e5df824`

## 当前结论

第一版创作主链和发布打包修复已经进入 `dev`，但**当前不能标记为正式发布完成**。

当前发布 PR 为 **#90：`dev -> main`**，HEAD 为 `d2c7655b`，GitHub 返回
`mergeable=true`；`main` 基线仍为 `c12c3dfb`。Owner 仍是唯一合并人。

## 还差什么

### 1. GitHub required checks 需要真正跑起来

`d2c7655b` 上最新 CI 与 Security workflow 都以 failure 结束，而且所有实际 job
都没有执行 step。当前问题发生在 hosted runner 分配/账号层，而不是某个测试命令失败。

本地 Docker 质量门仍可用于开发验证，但不能把“本地通过”写成“GitHub required checks
已通过”。如果改用其他 runner，需在单独变更中明确 runner 环境和发布适配边界。

### 2. REL-01 需要在正式 8080 入口闭合

此前真实 Provider 验收在隔离候选栈完成了主要阶段，但验收 driver 没有形成最终
`complete=true`：16 条必需断言中记录了 10 条，另外 6 条外部/跨阶段断言未导入。

当前 `dev` 已修正两个会阻止闭合的问题：

- migration head 从候选仓库自身推导，不再写死旧 revision；
- 验收入口端口可配置，默认正式入口为 **8080**。

发布验收应以 8080 为正式入口；8088 只适合作为隔离候选/测试端口，5173 只用于前端
开发。最终需要在同一候选 SHA 上完成浏览器、runtime、recovery 等外部证明并执行
`collect`，直到 required assertions 全部满足。

### 3. 发布物还需要最终安装验证

Release workflow 已包含以下修复：打包前回收 runner 磁盘、离线包扁平化、
`images.tar.gz` 单趟压缩，以及 `worker-director` 的生产必需环境变量。

这些改动仍需在可运行的 release workflow 上重新生成正式制品，并用生成出来的
online/offline bundle 做一次干净目录安装验证。只有源码测试通过不能替代发布物验证。

## 发布完成条件

V1 发布完成至少同时满足：

1. 当前候选的 CI / Security required checks 真实执行并通过；
2. 同一候选在正式 8080 入口完成 REL-01，最终 `complete=true`；
3. Owner 审阅并合并 `dev -> main`；
4. Release workflow 成功生成并发布版本化制品；
5. 对实际生成的安装包完成在线/离线安装、启动与健康检查验证。

## 证据和历史记录放哪里

当前树只保留可重复执行的验证逻辑，例如 CI、单测、E2E、release contract 和
`scripts/prove_v1_r7_acceptance.py`。真实 Provider 调用明细、阶段报告、旧候选审计和
一次性修复过程不再写入长期文档；需要追溯时查看 Git 历史，临时运行证据写入 `tmp/`。
