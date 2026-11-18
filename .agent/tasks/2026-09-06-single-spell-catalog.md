# 单一法术目录

Status: completed
Updated: 2026-09-06

## Goal

合并两份已中文化法术表，仅以 `backend/data/spell_catalog_2024.json` 作为运行时法术资料源。

## Scope

- 合并旧ID、名称别名和来源元数据；读取器与生成工具使用单一目录。
- 旧 `spells.json` 备份移出data；不修改玩家存档或法术结算规则。

## Progress

- [x] 核对读取器、生成器及两表差异：391个法术/987个职业条目一致，差异限于别名、ID和元数据。
- [x] 合并目录并移除运行时双表逻辑。
- [x] 调整生成工具、回归与实际API验收。

## Decisions

- 保留已纳入版本管理路径的 `spell_catalog_2024.json`；`spell_effect_rules.json` 继续只负责可执行规则，职责不同。
- 合并保留字段、联合别名，重复合并应幂等；环级和已有ID冲突时明确失败。

## Validation

- 两表全部字段与别名已逐项核对无丢失；合并幂等，391个法术/987个职业条目，中文覆盖不变。
- 新增单一文件加载、缺文件不回退、失败实例不缓存、离线合并冲突与旧提取器测试。
- 完整unittest440项：439通过、1项可选CLI测试跳过。Windows测试包装器仅调整工作区合成目录的权限继承与目录占用有限重试，不替换业务逻辑或测试断言。
- 8个文件与隔离测试副本一致后同步；旧spells.json已备份并移出backend/data目录。
- 实际23334服务已重载；API核对低环旧ID、历史名称与高环中文描述均保留，data中不再有旧表。
- git diff --check通过；修改的Markdown链接均能解析。

## Remaining work

- 本任务范围已完成；本次未调用真实模型或重放玩家回合。

## Resume instructions

- 基线为 `output/single-spell-catalog-baseline`，隔离副本为 `output/combat-control-fix`；保留原有未提交修改。
