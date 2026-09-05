import test from "node:test";
import assert from "node:assert/strict";

import {
  isPlayerVisibleTimelineEvent,
  narrativeEmphasisClass,
} from "./narrativeRollUi.js";

test("公开普通骰点只识别带语义前缀的 Markdown 斜体", () => {
  assert.equal(narrativeEmphasisClass("em", "骰点｜沐瑞安 察觉检定 17 vs DC 15 -> 成功"), "narrative-roll-result");
  assert.equal(narrativeEmphasisClass("em", "普通强调"), "");
  assert.equal(narrativeEmphasisClass("strong", "骰点｜不应命中"), "");
});

test("攻击结算只识别带语义前缀的 Markdown 粗体", () => {
  assert.equal(narrativeEmphasisClass("strong", "战斗｜沐瑞安 攻击 持刀地精：24 vs AC 14 -> 命中"), "narrative-attack-result");
  assert.equal(narrativeEmphasisClass("strong", "普通粗体"), "");
  assert.equal(narrativeEmphasisClass("em", "战斗｜不应命中"), "");
});

test("玩家时间线隐藏暗骰但保留旧事件和公开骰点", () => {
  assert.equal(isPlayerVisibleTimelineEvent({ payload: { visibility: "hidden" } }), false);
  assert.equal(isPlayerVisibleTimelineEvent({ payload: { visibility: "public" } }), true);
  assert.equal(isPlayerVisibleTimelineEvent({ payload: {} }), true);
});
