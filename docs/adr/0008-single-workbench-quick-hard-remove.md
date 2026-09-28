# ADR 0008：单一专业工作台，Quick 兼容入口硬删除

**状态：Accepted**
**日期：2026-09-22**
**决策人：项目 Owner（审查清单 §五.4 拍板确认）**

## 背景

ADR 0006 曾把专业工作台定为默认形态，同时保留「旧四阶段快速模式兼容入口」。
产品与代码随后确认：Quick / Creation Brief / 受控 Director 等旧表面已硬删除，
不存在第二产品入口。ADR 0006 中关于兼容入口的条款与当前事实冲突。

## 决策

1. DramaForge **只有一个产品工作台**：以 Scene / Shot / Asset / Production /
   Review / Edit 为核心的专业创作主链（canonical 定义见
   [CREATION_FLOW.md](../CREATION_FLOW.md)）。
2. Quick、四阶段向导、Creation Brief/Plan 等旧入口 **不再存在，也不恢复**；
   发布与安装操作不得重建它们。
3. Template Start / Free Start、AUTO / ASSIST / MANUAL 仅是初始化与 Director
   行为开关，**绝不形成快速版/专业版双产品**。
4. ADR 0006 的「快速模式兼容入口」条款 **superseded**；ADR 0005 中双模式共用
   契约的表述按其条款效力说明理解为「唯一工作台」。
5. ADR 编号自 0005 起；0001–0004 从未进入本树，缺口不补写历史正文。

## 影响

- 文档、API 与发布流程只描述单一主链。
- 任何“兼容 Quick / 双模式”新提案默认拒绝，除非 Owner 另立新 ADR。
