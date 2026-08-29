# 规则书本地文档规范

本规范服务于 DM_Agent 的本地规则检索。原始规则书放在被 Git 忽略的 `backend/Documents/DND5e 2024/`；规范化副本生成到同样被忽略的 `backend/Knowledge/grep_corpus/`。不要把受版权保护的规则书正文提交到仓库。

## 文件与编码

- 使用 UTF-8 文本，文件后缀为 `.md` 或 `.txt`。
- 一个文件聚焦一本规则书、一个章节或一个稳定主题；文件名应包含可搜索的正式名称。
- 标题层级使用标准 Markdown `#` 到 `######`，不要用字号、全角空格或连续符号模拟标题。
- 列表使用 `-` 或数字列表；表格优先使用 Markdown 表格。
- 规则术语、动作名称、法术名、状态名和英文原名应保持一致，不为排版随意拆词。

## 搜索友好性

- 每个主题使用唯一、描述性的标题；标题中写出玩家最可能搜索的规则名。
- 不同目录存在同名文件时，规范化器会在生成标题前补入最短必要的父目录上下文，避免 heading 权重把不同规则混为一谈；显式 `title` override 始终优先。
- 同义词、旧译名和常用缩写写入 `backend/rule_document_overrides.json` 的 `aliases`，不要在正文中机械堆词。`directories` 中的 aliases 会由其下所有文档继承，书名与 PHB/DMG/MM 等全书缩写优先放在这里；单篇特有别名放在 `documents`。词法索引会把文档 aliases 应用于该文档的每个 heading chunk，而不只作用于文件开头。
- 长章节应按规则概念拆成二级或三级标题；每节应能脱离上下文理解适用条件、结果和例外。
- 页眉、页脚、页码、OCR 重复段落和断行连字符应在原始资料允许的情况下人工清理。
- 表格转录后必须保留列名；只留下数值而丢失列含义会让词法检索和模型都无法可靠引用。

覆盖配置示例：

```json
{
  "directories": {
    "Players Handbook": {
      "aliases": ["PHB 2024", "Player's Handbook 2024"]
    }
  },
  "documents": {
    "Players Handbook/Combat.md": {
      "title": "Player's Handbook 2024 — Combat",
      "aliases": ["PHB combat", "战斗规则", "擒抱"]
    }
  }
}
```

## 生成与验证

在仓库根目录运行：

```sh
python backend/utils/normalize_rule_documents.py
```

脚本统一 Unicode、换行、Markdown 标题空格、项目符号和连续空行，消歧重复标题，并在表头列数明确时修复不匹配的 Markdown 表格分隔行。它会把误粘在标题后的长表格移出 heading，并在 manifest 的 `quality_warning_counts` / `quality_warnings` 中标记仍需人工整理的超长折叠表格和过短来源。它只清理由上一版 manifest 声明且现在已失去来源的生成文件。随后 RAG 会优先使用向量库；向量库、嵌入模型或 llama.cpp 服务不可用时，自动查询规范化词法语料。规范化目录不存在时会直接读取原始 `.md`/`.txt`，但检索质量可能较低。
