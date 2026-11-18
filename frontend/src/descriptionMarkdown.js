// 只改排版，不改规则文字；代码片段不参与Markdown纠错。
function normalizeProse(text) {
  const lines = text.split("\n");
  const items = lines.flatMap((line, index) => {
    const match = /^( *)(?:[-+*]|\d+[.)])\s+/.exec(line);
    return match ? [{ index, indent: match[1].length }] : [];
  });
  for (let first = 0; first < items.length; first += 1) {
    if (items[first].indent !== 0) continue;
    let end = first + 1;
    while (end < items.length && items[end].indent === items[end - 1].indent + 2) {
      const between = lines.slice(items[end - 1].index + 1, items[end].index);
      if (!between.some((line) => !line.trim()) || between.some((line) => /^#{1,6}\s|^\|/.test(line))) break;
      end += 1;
    }
    // 只修复从顶层开始、每项多缩进两格的完整阶梯。普通父子列表会回到同级，不满足此形状。
    if (end - first < 3 || (end < items.length && items[end].indent > 0)) continue;
    for (let cursor = first; cursor < end; cursor += 1) {
      const item = items[cursor];
      const until = items[cursor + 1]?.index ?? lines.length;
      for (let row = item.index; row < until; row += 1) {
        const spaces = /^ */.exec(lines[row])[0].length;
        if (spaces >= item.indent) lines[row] = lines[row].slice(item.indent);
      }
    }
    first = end - 1;
  }
  return lines.join("\n")
    .replace(/(\*{1,2})([^*]+?)([。:：，；]+)\1/g, "$1$2$1$3")
    .replace(/(\*\*)\n(?=[\u4e00-\u9fff])/g, "$1\n\n");
}

export function normalizeDescriptionMarkdown(value) {
  const text = String(value || "").replace(/\r\n?/g, "\n");
  // 保留围栏代码和行内代码的字面内容，包括其中的星号与缩进。
  return text.split(/(^[ \t]*```[^\n]*\n[\s\S]*?^[ \t]*```[^\n]*(?:\n|$)|^[ \t]*~~~[^\n]*\n[\s\S]*?^[ \t]*~~~[^\n]*(?:\n|$)|`[^`\n]+`)/gm)
    .map((part, index) => index % 2 ? part : normalizeProse(part)).join("");
}
