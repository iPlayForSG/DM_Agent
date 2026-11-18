import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { descriptionTooltipController as controller } from "./descriptionTooltipState";
import { normalizeDescriptionMarkdown } from "./descriptionMarkdown";

export default function DescriptionTooltip({ label, description, metadata = [], extra = "" }) {
  const tooltipId = useId();
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  const open = state.id === tooltipId;
  const pinned = open && state.phase === "pinned";
  const triggerRef = useRef(null);
  const popupRef = useRef(null);
  const closeRef = useRef(null);
  const positionRef = useRef(null);
  const ignoreFocusRef = useRef(false);
  const keyboardPinRef = useRef(false);
  const pointerTypeRef = useRef("mouse");
  const [pointer, setPointer] = useState(null);
  const hasDescription = Boolean(String(description || "").trim());
  const renderedDescription = useMemo(() => normalizeDescriptionMarkdown(description), [description]);
  const scalingLabel = /^\*\*戏法强化/.test(extra) ? "戏法强化" : "升环施法";
  const scalingDescription = useMemo(() => normalizeDescriptionMarkdown(String(extra).replace(/^\*\*(?:升环施法|戏法强化)[。:：]?\*\*[。:：]?\s*/u, "")), [extra]);
  // 鼠标进度圈移动不应重新解析长规则原文。
  const body = useMemo(() => <ReactMarkdown remarkPlugins={[remarkGfm]}>{renderedDescription}</ReactMarkdown>, [renderedDescription]);
  const scaling = useMemo(() => <ReactMarkdown remarkPlugins={[remarkGfm]}>{scalingDescription}</ReactMarkdown>, [scalingDescription]);

  const updatePointer = (event) => {
    if (event.pointerType === "touch") return;
    controller.enter(tooltipId);
    const active = controller.getSnapshot();
    if (active.id !== tooltipId || active.phase !== "preview") return;
    setPointer({ x: Math.min(event.clientX + 14, window.innerWidth - 20), y: Math.min(event.clientY + 16, window.innerHeight - 20) });
  };
  const enter = (event) => {
    if (event.pointerType === "touch") return;
    keyboardPinRef.current = false;
    controller.enter(tooltipId);
    updatePointer(event);
  };
  const leave = () => { setPointer(null); controller.leave(tooltipId); };
  const close = () => {
    setPointer(null);
    controller.close(tooltipId);
    // 返回触发词的键盘焦点不能立即重新打开刚关闭的窗口。
    ignoreFocusRef.current = true;
    triggerRef.current?.focus({ preventScroll: true });
    queueMicrotask(() => { ignoreFocusRef.current = false; });
  };

  useEffect(() => {
    if (!hasDescription) controller.close(tooltipId);
    return () => controller.close(tooltipId);
  }, [tooltipId, hasDescription]);
  useLayoutEffect(() => {
    if (!open || !hasDescription) return undefined;
    const place = () => {
      const anchor = triggerRef.current;
      const popup = popupRef.current;
      if (!anchor || !popup) return;
      const rect = anchor.getBoundingClientRect();
      const width = popup.offsetWidth;
      const height = popup.offsetHeight;
      let left, top;
      if (pinned && positionRef.current) {
        ({ left, top } = positionRef.current);
      } else {
        left = rect.left;
        const below = rect.bottom + 8;
        top = below + height <= window.innerHeight - 12 ? below : rect.top - height - 8;
      }
      left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
      top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
      positionRef.current = { left, top };
      Object.assign(popup.style, { left: `${left}px`, top: `${top}px` });
    };
    place();
    if (pinned && keyboardPinRef.current) { keyboardPinRef.current = false; closeRef.current?.focus(); }
    const observer = new ResizeObserver(place);
    observer.observe(popupRef.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, pinned, hasDescription, description, extra]);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event) => {
      if (!triggerRef.current?.contains(event.target) && !popupRef.current?.contains(event.target)) controller.dismissPreview(tooltipId);
    };
    const escape = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation();
      setPointer(null);
      controller.close(tooltipId);
      ignoreFocusRef.current = true;
      triggerRef.current?.focus({ preventScroll: true });
      queueMicrotask(() => { ignoreFocusRef.current = false; });
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape, true); };
  }, [open, tooltipId]);

  if (!hasDescription) return <span>{label}</span>;
  return <>
    <button type="button" className="description-trigger" ref={triggerRef}
      aria-describedby={open && !pinned ? tooltipId : undefined} aria-controls={open ? tooltipId : undefined}
      aria-expanded={open} aria-haspopup="dialog"
      onPointerEnter={enter} onPointerMove={updatePointer} onPointerLeave={leave}
      onPointerDown={(event) => { pointerTypeRef.current = event.pointerType; }}
      onFocus={() => {
        if (!ignoreFocusRef.current) {
          if (controller.getSnapshot().id !== tooltipId) setPointer(null);
          controller.focus(tooltipId);
        }
      }}
      onBlur={(event) => { if (!popupRef.current?.contains(event.relatedTarget) && !pointer) controller.dismissPreview(tooltipId); }}
      onClick={(event) => {
        event.stopPropagation();
        if (event.detail === 0 || pointerTypeRef.current === "touch") { keyboardPinRef.current = event.detail === 0; controller.pin(tooltipId); }
        else controller.enter(tooltipId);
      }}>{label}</button>
    {open && createPortal(<>
      <div className={`description-tooltip ${pinned ? "is-pinned" : "is-preview"}`} id={tooltipId}
        role={pinned ? "dialog" : "tooltip"} aria-label={pinned ? `${label}说明` : undefined} ref={popupRef}
        onPointerEnter={enter} onPointerMove={updatePointer} onPointerLeave={leave} onClick={(event) => event.stopPropagation()}>
        <div className="description-tooltip-header">
          <div><strong className="description-tooltip-title">{label}</strong><span className="description-tooltip-mode">{pinned ? "已固定" : pointer ? "悬停 1.5 秒固定" : "按回车固定"}</span></div>
          <button type="button" className="description-tooltip-close" ref={closeRef} aria-label="关闭说明" onClick={(event) => { event.stopPropagation(); close(); }}>×</button>
        </div>
        <div className="description-tooltip-scroll">
          {metadata.length > 0 && <div className="description-tooltip-meta">{metadata.filter(Boolean).join(" · ")}</div>}
          <div className="description-tooltip-body">{body}</div>
          {extra && <div className="description-tooltip-extra"><strong>{scalingLabel}</strong>{scaling}</div>}
        </div>
      </div>
      {!pinned && pointer && <span className="description-cursor-spinner" aria-hidden="true" style={{ left: pointer.x, top: pointer.y }} />}
    </>, document.body)}
  </>;
}
