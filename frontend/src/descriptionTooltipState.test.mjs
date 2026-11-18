import assert from "node:assert/strict";
import test from "node:test";
import { createTooltipController } from "./descriptionTooltipState.js";

function fixture() {
  let time = 0, serial = 0;
  const tasks = new Map();
  const controller = createTooltipController({ now: () => time,
    schedule: (callback, delay) => { const id = ++serial; tasks.set(id, { callback, at: time + delay }); return id; },
    cancel: (id) => tasks.delete(id),
  });
  return { controller, advance(delta) {
    const until = time + delta;
    while (true) {
      const next = [...tasks].filter(([, task]) => task.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      time = next[1].at; tasks.delete(next[0]); next[1].callback();
    }
    time = until;
  } };
}

test("连续悬停恰好1500毫秒后固定", () => {
  const { controller: c, advance } = fixture();
  c.enter("a"); advance(1499);
  assert.equal(c.getSnapshot().phase, "preview");
  advance(1); assert.deepEqual(c.getSnapshot(), { id: "a", phase: "pinned" });
});
test("提前移开取消固定，预览延迟关闭", () => {
  const { controller: c, advance } = fixture();
  c.enter("a"); advance(1400); c.leave("a"); advance(100);
  assert.equal(c.getSnapshot().phase, "preview");
  advance(80); assert.equal(c.getSnapshot().phase, "closed");
  advance(3000); assert.equal(c.getSnapshot().phase, "closed");
});
test("穿过触发词与浮窗的间隙暂停计时后继续", () => {
  const { controller: c, advance } = fixture();
  c.enter("a"); advance(1200); c.leave("a"); advance(100); c.enter("a"); advance(299);
  assert.equal(c.getSnapshot().phase, "preview"); advance(1);
  assert.equal(c.getSnapshot().phase, "pinned");
});
test("切换预览时旧计时器不能改变新窗口", () => {
  const { controller: c, advance } = fixture();
  c.enter("a"); advance(1200); c.leave("a"); c.enter("b"); advance(300);
  assert.deepEqual(c.getSnapshot(), { id: "b", phase: "preview" });
  advance(1200); assert.deepEqual(c.getSnapshot(), { id: "b", phase: "pinned" });
  c.close("a"); assert.equal(c.getSnapshot().id, "b");
});
test("固定后移开、点击空白和悬停其它词条都保持唯一窗口", () => {
  const { controller: c, advance } = fixture();
  c.enter("a"); advance(1500); c.leave("a"); c.dismissPreview("a"); c.enter("b"); c.pin("b"); advance(2000);
  assert.deepEqual(c.getSnapshot(), { id: "a", phase: "pinned" });
  c.close("a"); c.enter("b"); assert.equal(c.getSnapshot().id, "b");
});
test("键盘焦点只预览，明确激活固定，关闭不被旧定时器复活", () => {
  const { controller: c, advance } = fixture();
  c.focus("a"); advance(2000); assert.equal(c.getSnapshot().phase, "preview");
  c.pin("a"); assert.equal(c.getSnapshot().phase, "pinned");
  c.close("a"); advance(3000); assert.equal(c.getSnapshot().phase, "closed");
});
