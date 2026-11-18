import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { normalizeDescriptionMarkdown } from "./descriptionMarkdown.js";

const data = JSON.parse(readFileSync(new URL("../../backend/data/spell_catalog_2024.json", import.meta.url), "utf8"));
const spells = new Map(Object.values(data.SPELL_DATABASE).flat().map((spell) => [spell.nameEN, spell]));
const render = (text) => renderToStaticMarkup(React.createElement(ReactMarkdown, { remarkPlugins: [remarkGfm] }, normalizeDescriptionMarkdown(text)));
const words = (text) => text.replace(/[\s*]/g, "");

test("命令术的五条命令渲染为五个同级列表项", () => {
  const html = render(spells.get("Command").desc);
  assert.equal((html.match(/<ul>/g) || []).length, 1);
  assert.equal((html.match(/<li>/g) || []).length, 5);
  for (const name of ["过来", "放下", "走开", "趴下", "立定"]) assert.ok(html.includes(`<strong>${name}</strong>`));
});
test("全目录的11个阶梯列表得到修复且所有原文字词与数字保留", () => {
  const repaired = [];
  for (const spell of spells.values()) {
    for (const field of ["desc", "higherLevels"]) {
      const original = spell[field] || "", normalized = normalizeDescriptionMarkdown(original);
      assert.equal(words(normalized), words(original), `${spell.name} ${field}`);
      const before = [...original.matchAll(/^( *)\*\s+/gm)].map((match) => match[1].length);
      const after = [...normalized.matchAll(/^( *)\*\s+/gm)].map((match) => match[1].length);
      if (before.some((indent, index) => indent !== after[index])) repaired.push(spell.nameEN);
    }
  }
  assert.equal(repaired.length, 11);
  assert.ok(repaired.includes("Greater Restoration"));
  assert.ok(repaired.includes("Bigby's Hand"));
});
test("真实父子列表与没有空行的层级链保持不变", () => {
  for (const text of ["* 父项\n  * 子项一\n  * 子项二\n* 另一父项", "* 一层\n  * 二层\n    * 三层"]) {
    assert.equal(normalizeDescriptionMarkdown(text), text);
    assert.ok((render(text).match(/<ul>/g) || []).length > 1);
  }
});
test("围栏代码及行内代码保持字面内容", () => {
  const text = "```text\n* 一\n\n  * 二\n\n    * 三\n**原文。**\n```\n`**代码。**`";
  assert.equal(normalizeDescriptionMarkdown(text), text);
});
test("跨行中文强调段落和表格正常渲染", () => {
  const html = render("**更高等级At Higher\nLevels。**你的骰子提升。\n\n| 骰式 | 数值 |\n| --- | --- |\n| 1d6 | 6 |");
  assert.ok(!html.includes("**"));
  assert.ok(html.includes("<table>"));
  assert.ok(html.includes("1d6"));
});
