import React, { useState } from "react";
import DescriptionTooltip from "../DescriptionTooltip";
import { choiceClassName, formatShopItemMeta, localizeEquipmentType } from "../dndLabels";

export function ChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return (
    <button
      type="button"
      className={choiceClassName("class-card", selected, disabled, className)}
      aria-pressed={selected}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

export function SpellChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return (
    <button
      type="button"
      className={choiceClassName("spell-card", selected, disabled, className)}
      aria-pressed={selected}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

export default function ShopCarousel({ group, quantities, onQuantityChange }) {
  const pageSize = 3;
  const [page, setPage] = useState(0);
  const categoryLabel = group.items[0]?.type_display || localizeEquipmentType(group.type);
  const pageCount = Math.max(1, Math.ceil(group.items.length / pageSize));
  // 商品目录会随职业刷新；派生安全页码可避免保留的局部页码落到空页。
  const safePage = Math.min(page, pageCount - 1);
  const start = safePage * pageSize;
  const visibleItems = group.items.slice(start, start + pageSize);
  const end = start + visibleItems.length;
  const titleId = `shop-carousel-${group.type}`;

  return (
    <section className="builder-preview-card shop-section" aria-labelledby={titleId}>
      <div className="shop-carousel-header">
        <h3 id={titleId}>{categoryLabel}</h3>
        <div className="shop-carousel-controls">
          <span className="shop-carousel-range" aria-live="polite" aria-atomic="true">
            {pageCount > 1 ? `${start + 1}–${end} / ${group.items.length}` : `共 ${group.items.length} 项`}
          </span>
          {pageCount > 1 && (
            <>
              <button
                type="button"
                className="shop-carousel-button"
                aria-label={`查看${categoryLabel}的上一组商品`}
                title="上一组"
                disabled={safePage === 0}
                onClick={() => setPage(Math.max(0, safePage - 1))}
              >
                <span aria-hidden="true">‹</span>
              </button>
              <button
                type="button"
                className="shop-carousel-button"
                aria-label={`查看${categoryLabel}的下一组商品`}
                title="下一组"
                disabled={safePage === pageCount - 1}
                onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))}
              >
                <span aria-hidden="true">›</span>
              </button>
            </>
          )}
        </div>
      </div>
      <div className="timeline-list shop-carousel-page">
        {visibleItems.map((item) => {
          const itemName = item.name_display || item.name;
          const quantity = Number(quantities?.[item.id] || 0);
          return (
            <article key={item.id} className={`shop-card ${quantity > 0 ? "selected" : ""}`}>
              <div className="shop-card-copy">
                <div className="timeline-summary">
                  <DescriptionTooltip
                    label={itemName}
                    description={item.description_display || item.description || item.notes_display || item.notes}
                  />
                </div>
                <div className="timeline-content">{formatShopItemMeta(item)}</div>
              </div>
              <div className="quantity-stepper" aria-label={`${itemName}数量`}>
                <button
                  type="button"
                  aria-label={`减少${itemName}数量`}
                  disabled={quantity === 0}
                  onClick={() => onQuantityChange(item.id, quantity - 1)}
                >
                  −
                </button>
                <output aria-label={`${itemName}当前数量`}>{quantity}</output>
                <button
                  type="button"
                  aria-label={`增加${itemName}数量`}
                  onClick={() => onQuantityChange(item.id, quantity + 1)}
                >
                  +
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
