import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function DescriptionTooltip({ label, description, metadata = [], extra = "" }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const popupRef = useRef(null);
  const closeTimer = useRef(null);
  const tooltipId = useId();
  const hasDescription = Boolean(String(description || "").trim());
  const keepOpen = () => clearTimeout(closeTimer.current);
  const show = () => { keepOpen(); setOpen(true); };
  const hide = () => { keepOpen(); setOpen(false); };
  const scheduleHide = () => {
    keepOpen();
    // 给鼠标跨越名称与浮层之间的间隙留出时间，长说明可停留阅读和滚动。
    closeTimer.current = setTimeout(() => setOpen(false), 180);
  };

  useEffect(() => () => clearTimeout(closeTimer.current), []);
  useLayoutEffect(() => {
    if (!open || !hasDescription) return undefined;
    const place = () => {
      const anchor = triggerRef.current;
      const popup = popupRef.current;
      if (!anchor || !popup) return;
      const rect = anchor.getBoundingClientRect();
      const width = popup.offsetWidth;
      const height = popup.offsetHeight;
      const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
      const below = rect.bottom + 8;
      const top = below + height <= window.innerHeight - 12 ? below : Math.max(12, rect.top - height - 8);
      Object.assign(popup.style, { left: `${left}px`, top: `${top}px` });
    };
    const dismissOutside = (event) => {
      if (!triggerRef.current?.contains(event.target) && !popupRef.current?.contains(event.target)) setOpen(false);
    };
    const dismissEscape = (event) => { if (event.key === "Escape") setOpen(false); };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("keydown", dismissEscape);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("keydown", dismissEscape);
    };
  }, [open, hasDescription, description, extra]);

  if (!hasDescription) return <span>{label}</span>;
  return (
    <>
      <button type="button" className="description-trigger" ref={triggerRef}
        aria-describedby={open ? tooltipId : undefined}
        onMouseEnter={show} onMouseLeave={scheduleHide} onFocus={show} onBlur={hide} onClick={show}>
        {label}
      </button>
      {open && createPortal(
        <div className="description-tooltip" id={tooltipId} role="tooltip" ref={popupRef}
          onMouseEnter={keepOpen} onMouseLeave={scheduleHide}>
          <strong className="description-tooltip-title">{label}</strong>
          {metadata.length > 0 && <div className="description-tooltip-meta">{metadata.filter(Boolean).join(" · ")}</div>}
          <div className="description-tooltip-body">{description}</div>
          {extra && <div className="description-tooltip-extra"><strong>升环施法</strong><div>{extra}</div></div>}
        </div>, document.body,
      )}
    </>
  );
}
