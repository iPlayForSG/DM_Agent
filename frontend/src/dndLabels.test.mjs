import assert from "node:assert/strict";
import test from "node:test";
import {
  asMarkdownQuote,
  formatAbilityModifier,
  formatEquipmentLine,
  localizeClassName,
  localizeSceneText,
  mapMessages,
  resolveStarterPreviewItems,
} from "./dndLabels.js";

test("mapMessages filters tool_result entries and binds assistant turn status and roll records", () => {
  const history = [
    { role: "user", content: "我推开石门。" },
    { role: "tool", kind: "tool_result", content: "{}" },
    {
      role: "assistant",
      content: "门后是一座大厅。",
      narrative_mode: "combat",
      roll_records: [{ record_id: "r1", total: 15 }],
      roll_records_recorded: true,
    },
    { role: "system", content: "Scene changed to exploration" },
  ];
  const timeline = [{ type: "assistant_response", payload: { turn_status: "completed" } }];
  const mapped = mapMessages(history, timeline);

  assert.equal(mapped.length, 3);
  assert.equal(mapped[0].sender, "player");
  assert.equal(mapped[1].sender, "dm");
  assert.equal(mapped[1].turnStatus, "completed");
  assert.equal(mapped[1].narrativeMode, "combat");
  assert.equal(mapped[1].rollRecords.length, 1);
  assert.equal(mapped[1].rollRecordsRecorded, true);
  assert.equal(mapped[2].sender, "system");
  assert.match(mapped[2].text, /探索/);
});

test("formatAbilityModifier and localize helpers return canonical 2024 Chinese labels", () => {
  assert.equal(formatAbilityModifier(8), "-1");
  assert.equal(formatAbilityModifier(10), "+0");
  assert.equal(formatAbilityModifier(16), "+3");
  assert.equal(localizeClassName("Wizard"), "法师");
  assert.equal(localizeSceneText("entering combat phase"), "entering 战斗 phase");
});

test("formatEquipmentLine and resolveStarterPreviewItems preserve currency, weapon and scroll metadata", () => {
  assert.equal(
    formatEquipmentLine({
      type: "weapon",
      quantity: 1,
      damage_expression: "1d8+3",
      damage_type_display: "挥砍",
      is_equipped: true,
    }),
    "武器 · 伤害 1d8+3 · 挥砍 · 已装备",
  );
  assert.equal(
    formatEquipmentLine({
      type: "currency",
      quantity: 25,
    }),
    "数量 25 · 货币",
  );
  const resolved = resolveStarterPreviewItems(
    {
      items: [{ name: "法术书" }],
      choices: [{ id: "c1", options: [{ id: "o1", items: [{ name: "短杖" }] }] }],
    },
    { c1: "o1" },
  );
  assert.deepEqual(
    resolved.map((item) => item.name),
    ["法术书", "短杖"],
  );
  assert.equal(asMarkdownQuote("第一行\n第二行"), "> 第一行\n> 第二行");
});
