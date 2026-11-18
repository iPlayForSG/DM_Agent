export const TOOLTIP_PIN_DELAY = 1500;
export const TOOLTIP_HIDE_DELAY = 180;

export function createTooltipController({ now = Date.now, schedule = setTimeout, cancel = clearTimeout } = {}) {
  let snapshot = { id: null, phase: "closed" };
  const listeners = new Set();
  let pinTimer, closeTimer, enteredAt = null, elapsed = 0;
  const publish = (next) => { snapshot = next; listeners.forEach((listener) => listener()); };
  const cancelTimers = () => { cancel(pinTimer); cancel(closeTimer); pinTimer = closeTimer = undefined; };
  const permitted = (id) => snapshot.phase !== "pinned" || snapshot.id === id;
  const open = (id) => {
    if (!permitted(id)) return false;
    if (snapshot.id !== id) {
      cancelTimers(); elapsed = 0; enteredAt = null;
      publish({ id, phase: "preview" });
    }
    cancel(closeTimer);
    return true;
  };
  const close = (id) => {
    if (snapshot.id !== id) return;
    cancelTimers(); elapsed = 0; enteredAt = null;
    publish({ id: null, phase: "closed" });
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    focus: open,
    enter(id) {
      if (!open(id) || snapshot.phase === "pinned" || enteredAt !== null) return;
      enteredAt = now();
      pinTimer = schedule(() => {
        // 旧词条的延迟回调不能固定或关闭新词条的窗口。
        if (snapshot.id === id && snapshot.phase === "preview" && enteredAt !== null) {
          cancelTimers(); enteredAt = null;
          publish({ id, phase: "pinned" });
        }
      }, Math.max(0, TOOLTIP_PIN_DELAY - elapsed));
    },
    leave(id) {
      if (snapshot.id !== id || snapshot.phase === "pinned") return;
      if (enteredAt !== null) elapsed += Math.max(0, now() - enteredAt);
      enteredAt = null; cancel(pinTimer); cancel(closeTimer);
      // 穿过触发词与浮窗间的小间隙时暂停计时；真正离开则关闭预览。
      closeTimer = schedule(() => {
        if (snapshot.id === id && snapshot.phase === "preview") close(id);
      }, TOOLTIP_HIDE_DELAY);
    },
    pin(id) {
      if (!open(id)) return;
      cancelTimers(); enteredAt = null;
      publish({ id, phase: "pinned" });
    },
    dismissPreview(id) { if (snapshot.phase === "preview") close(id); },
    close,
  };
}

export const descriptionTooltipController = createTooltipController();
