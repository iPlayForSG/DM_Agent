# 攻击结算后错误规则反馈审计

Status: completed
Updated: 2026-09-07

## Goal

定位成功攻击、使用特性和结束遭遇后，错误进入规则反馈并回滚的原因。本次只做审计。

## Evidence scope

- 只读SQLite writes中的技术通道：node_traces、validation_status、validation_issues、validation_repair_tools、unresolved_operations、combat_flow、turn_status。
- 未读取GameState/聊天消息通道或完整会话，未重放玩家行动。

## Findings

- 攻击前两次失败是武器名称含附加的投掷描述，无法匹配角色卡。随后使用实际武器名，攻击成功；use_feature与end_encounter也成功。
- 最后一次验证是ok，当前repair_tools及unresolved_operations均为空，action_done为true。没有攻击成功后的重复攻击工具调用。
- dm_graph._validate_state累积validation_notes，在验证通过分支仍交给_build_validation_message发送全部历史提示。过期的未攻击/待修复指令被重新放入DM上下文。
- DM随后调用report_rule_conflict；其通用文字检查未识别本次内部修复误报。finalize_turn按rules_feedback恢复初始业务快照，却将依据暂存状态写出的死亡/战斗结束说明存成回复，造成骰点回滚与正文矛盾。
- attack_target当前按角色卡武器数值结算，没有独立临时投掷模式。本地手册的临时武器规则适用于投掷非投掷近战武器，不能无说明地沿用普通近战攻击数据。
- use_feature当前记录资源/动作消耗，没有吟游激励的目标骰子与到期状态；工具成功不等于目标效果已完整实现。

## Validation

- 核对实际技术记录与当前代码路径；没有修改产品代码或测试。

## Remaining work

- 后续修复应区分历史审计与当前修复问题，通过后明确撤销过期指令；内部修复误报不能伪装成玩家规则冲突。
- 回滚后反馈不得继续宣称本轮暂存死亡/效果已发生。
- 临时投掷模式和吟游激励目标状态需要单独补齐并回归。

## Resume instructions

- 以本报告和当前代码继续，不依赖历史工具失败仍待修复的假设；保留已有未提交修改。
