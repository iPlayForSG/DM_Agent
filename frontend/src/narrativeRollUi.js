export const PUBLIC_ROLL_PREFIX = "骰点｜";
export const ATTACK_ROLL_PREFIX = "战斗｜";

export function narrativeEmphasisClass(tagName, text) {
  const normalizedTag = String(tagName || "").toLowerCase();
  const normalizedText = String(text || "").trim();
  if (normalizedTag === "em" && normalizedText.startsWith(PUBLIC_ROLL_PREFIX)) {
    return "narrative-roll-result";
  }
  if (normalizedTag === "strong" && normalizedText.startsWith(ATTACK_ROLL_PREFIX)) {
    return "narrative-attack-result";
  }
  return "";
}

export function isPlayerVisibleTimelineEvent(event) {
  return String(event?.payload?.visibility || "public").toLowerCase() !== "hidden";
}
