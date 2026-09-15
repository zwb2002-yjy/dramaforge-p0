# DramaForge 开发入口

遵守 [AGENTS.md](AGENTS.md) 的项目权威、图像与证据边界。所有当前权威文档的入口是
[docs/CURRENT.md](docs/CURRENT.md)；不要从历史设计稿、Task Contract、Review 或执行记录开始。

- **只读问题或审计：** 读取回答问题所需的文件和权威章节，不启动实施/账本/全量 Gate。
- **实际修改：** 先读 [docs/CURRENT.md](docs/CURRENT.md) 找到对应领域的权威文档；行为变更
  以代码、迁移、测试为当前事实，文档描述预期行为，冲突时以代码为准并更新文档。
- **已授权连续 Goal：** 按同一执行入口恢复并推进，直到该 Goal 的完整完成条件或真实外部
  边界，不在首版或单个 Task 后无故等待。
- **历史材料：** 已删除的旧设计、Task Contract、Review、Execution Record 只存在于 Git
  历史，不构成当前实现依据，不为新任务授权。

付费调用只使用当前 Goal/Task 已明确给出的授权；已授权范围内无需逐次确认，读到旧授权不向
新任务授予权限。
