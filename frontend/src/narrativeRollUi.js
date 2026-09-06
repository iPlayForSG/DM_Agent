export const PUBLIC_ROLL_PREFIX = "骰点｜";
export const ATTACK_ROLL_PREFIX = "战斗｜";
export const INVENTORY_PREFIX = "物品｜";

export function narrativeEmphasisClass(tagName, text) {
  const normalizedTag = String(tagName || "").toLowerCase();
  const normalizedText = String(text || "").trim();
  if (normalizedTag === "em" && normalizedText.startsWith(PUBLIC_ROLL_PREFIX)) {
    return "narrative-roll-result";
  }
  if (normalizedTag === "strong" && normalizedText.startsWith(ATTACK_ROLL_PREFIX)) {
    return "narrative-attack-result";
  }
  if (normalizedTag === "strong" && normalizedText.startsWith(INVENTORY_PREFIX)) {
    return "narrative-inventory-change";
  }
  return "";
}

export function isPlayerVisibleTimelineEvent(event) {
  return String(event?.payload?.visibility || "public").toLowerCase() !== "hidden";
}
