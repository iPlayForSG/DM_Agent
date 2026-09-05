import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import DescriptionTooltip from "./DescriptionTooltip";
import { isPlayerVisibleTimelineEvent, narrativeEmphasisClass } from "./narrativeRollUi";
import { mergeRollRecords, rollSettlementLabel } from "./rollUi";
import {
  createEmptyDmThinking,
  prepareDmRetryUiRollback,
  preparePlayerRewriteUiRollback,
} from "./retryUi";
import {
  addEncounterEnemy,
  advanceTurn,
  attackAction,
  castSpellAction,
  createGame,
  deleteCharacter,
  deleteCharacters,
  deleteGame,
  deleteGames,
  deleteGameMessage,
  endEncounter,
  generateAbilityScores,
  loadActionOptions,
  loadActionSuggestions,
  loadCharacter,
  loadCharacterBuilder,
  loadGame,
  loadLobby,
  loadModelConfig,
  loadModelHealth,
  loadMonsterTemplate,
  loadSpells,
  saveCharacter,
  saveMonsterTemplate,
  savingThrowAction,
  selectModelConfig,
  selectAdventure,
  skillCheckAction,
  removeEncounterCombatant,
  retryGameMessage,
  rollEncounterInitiative,
  rewriteGameMessage,
  spawnEncounterTemplate,
  startEncounter,
  setEncounterInitiative,
  streamTurn,
  updateReplyLength,
  updateModelConfig,
  useItemAction as itemActionRequest,
} from "./api";
import "./index.css";

const STATS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];

function formatLlmHealthMessage(health) {
  if (!health || health.ready) return "";
  if (health.reason === "cli_not_found") return "模型连接失败：未找到所选 Coding Agent CLI，请检查命令或 PATH。";
  if (health.reason === "cli_probe_failed") return "模型连接失败：CLI 无法正常启动，请检查本机安装。";
  if (!health.configured) return "模型档案尚未完整配置，请补全 Base URL、模型名称和 API Key。";
  if (Number(health.status_code) === 401) return "模型连接失败：API Key 无效或已被服务拒绝。";
  if (health.status_code) return `模型连接失败（HTTP ${health.status_code}），请检查服务地址和模型档案。`;
  return "暂时无法验证模型连接，请检查模型服务是否可访问。";
}

const MODEL_PROVIDER_LABELS = {
  "openai-compatible": "API（OpenAI-compatible）",
  "claude-code": "Claude Code CLI",
  "codex-cli": "Codex CLI",
};

const CODEX_DEFAULT_MODEL = "gpt-5.6-terra";
const CODEX_DEFAULT_REASONING_EFFORT = "high";
const CODEX_REASONING_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"];

const EMPTY_LLM_DRAFT = {
  profile_id: "",
  profile_label: "",
  provider: "codex-cli",
  model_name: CODEX_DEFAULT_MODEL,
  reasoning_effort: CODEX_DEFAULT_REASONING_EFFORT,
  base_url: "",
  api_key: "",
  cli_command: "codex",
  cli_timeout_s: 300,
};

const STAT_LABELS = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};
const SKILL_LABELS = {
  acrobatics: "杂技",
  animal_handling: "驯兽",
  arcana: "奥秘",
  athletics: "运动",
  deception: "欺瞒",
  history: "历史",
  insight: "洞悉",
  intimidation: "威吓",
  investigation: "调查",
  medicine: "医药",
  nature: "自然",
  perception: "察觉",
  performance: "表演",
  persuasion: "游说",
  religion: "宗教",
  sleight_of_hand: "巧手",
  stealth: "隐匿",
  survival: "求生",
};
const SIDE_LABELS = { party: "队伍", enemy: "敌方", ally: "友方" };
const AI_GENERATED_ADVENTURE_ID = "adv-ai-generated";
const CLASS_RESOURCE_NAME_LABELS = {
  "Wild Shape": "野性变身",
  "Second Wind": "二次呼吸",
  "Lay on Hands": "圣疗之手",
  "Channel Divinity": "引导神力",
  "Rage": "狂暴",
  "Sorcery Points": "法术点",
  "Ki Points": "气力点",
  "Bardic Inspiration": "吟游激励",
};
const CLASS_NAME_LABELS = {
  Artificer: "奇械师",
  Barbarian: "野蛮人",
  Bard: "吟游诗人",
  Cleric: "牧师",
  Druid: "德鲁伊",
  Fighter: "战士",
  Monk: "武僧",
  Paladin: "圣武士",
  Ranger: "游侠",
  Rogue: "游荡者",
  Sorcerer: "术士",
  Warlock: "邪术师",
  Wizard: "法师",
};
const SPECIES_NAME_LABELS = {
  Human: "人类",
  Elf: "精灵",
  Dwarf: "矮人",
  Halfling: "半身人",
  Aasimar: "神裔",
  Dragonborn: "龙裔",
  Gnome: "侏儒",
  Goliath: "歌利亚",
  Orc: "兽人",
  Tiefling: "提夫林",
};
const BACKGROUND_NAME_LABELS = {
  Acolyte: "侍祭",
  Criminal: "罪犯",
  Entertainer: "艺人",
  Farmer: "农夫",
  Sage: "贤者",
  Soldier: "士兵",
  Wayfarer: "浪人",
  Artisan: "工匠",
  Charlatan: "骗子",
  Guard: "守卫",
  Guide: "向导",
  Hermit: "隐士",
  Merchant: "商人",
  Noble: "贵族",
  Sailor: "水手",
  Scribe: "抄写员",
};
const ORIGIN_FEAT_LABELS = {
  Alert: "警觉",
  Crafter: "工匠",
  Lucky: "幸运",
  Musician: "音乐家",
  "Magic Initiate (Cleric)": "魔法学徒（牧师）",
  "Magic Initiate (Druid)": "魔法学徒（德鲁伊）",
  "Magic Initiate (Wizard)": "魔法学徒（法师）",
  "Savage Attacker": "狂野攻击手",
  Skilled: "技艺娴熟",
  Tough: "坚韧",
  Healer: "医者",
  "Magic Initiate": "魔法学徒",
  "Tavern Brawler": "酒馆斗殴者",
};
const STAT_ABBREVIATION_TO_KEY = {
  str: "strength",
  dex: "dexterity",
  con: "constitution",
  int: "intelligence",
  wis: "wisdom",
  cha: "charisma",
};
const SCENE_LABELS = {
  adventure_selection: "冒险选择",
  setup: "准备",
  preparation: "准备",
  exploration: "探索",
  social: "社交",
  combat: "战斗",
  encounter: "遭遇",
};
const SIZE_LABELS = { tiny: "微型", small: "小型", medium: "中型", large: "大型", huge: "超大型", gargantuan: "巨型" };
const CREATURE_TYPE_LABELS = {
  aberration: "异怪",
  beast: "野兽",
  celestial: "天界生物",
  construct: "构装体",
  dragon: "龙类",
  elemental: "元素生物",
  fey: "妖精",
  fiend: "邪魔",
  giant: "巨人",
  humanoid: "人型生物",
  monstrosity: "怪异生物",
  ooze: "软泥怪",
  plant: "植物",
  undead: "不死生物",
};
const ALIGNMENT_LABELS = {
  unaligned: "无阵营",
  lawful_good: "守序善良",
  lawful_neutral: "守序中立",
  lawful_evil: "守序邪恶",
  neutral_good: "中立善良",
  neutral: "绝对中立",
  neutral_evil: "中立邪恶",
  chaotic_good: "混乱善良",
  chaotic_neutral: "混乱中立",
  chaotic_evil: "混乱邪恶",
};
const ATTACK_RESOLUTION_OPTIONS = [
  { value: "normal", label: "普通伤害" },
  { value: "nonlethal", label: "非致命" },
  { value: "capture", label: "俘获" },
];
const POINT_BUY_COSTS = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
const DEFAULT_STATS = { strength: 15, dexterity: 14, constitution: 13, intelligence: 12, wisdom: 10, charisma: 8 };
const ABILITY_METHOD_LABELS = {
  point_buy: "27 点购点",
  standard_array: "标准数组",
  rolled: "4d6 去最低",
};
const DEFEAT_STATE_LABELS = {
  active: "正常",
  unconscious: "昏迷",
  captured: "被俘",
  dead: "死亡",
};
const CLASS_RECOMMENDED_STAT_ORDER = {
  Artificer: ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],
  Barbarian: ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
  Bard: ["charisma", "dexterity", "constitution", "wisdom", "intelligence", "strength"],
  Cleric: ["wisdom", "constitution", "strength", "dexterity", "charisma", "intelligence"],
  Druid: ["wisdom", "constitution", "dexterity", "intelligence", "charisma", "strength"],
  Fighter: ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
  Monk: ["dexterity", "wisdom", "constitution", "strength", "charisma", "intelligence"],
  Paladin: ["strength", "charisma", "constitution", "wisdom", "dexterity", "intelligence"],
  Ranger: ["dexterity", "wisdom", "constitution", "strength", "charisma", "intelligence"],
  Rogue: ["dexterity", "constitution", "wisdom", "charisma", "intelligence", "strength"],
  Sorcerer: ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],
  Warlock: ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],
  Wizard: ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],
};
const recommendedStatsForClass = (className) => {
  const order = CLASS_RECOMMENDED_STAT_ORDER[className];
  if (!order) return { ...DEFAULT_STATS };
  return Object.fromEntries(order.map((stat, index) => [stat, [15, 14, 13, 12, 10, 8][index]]));
};
const CREATOR_STEPS = [
  { id: "identity", label: "基础" },
  { id: "build", label: "构筑" },
  { id: "equipment", label: "装备" },
  { id: "spells", label: "法术" },
  { id: "review", label: "总览" },
];
const EQUIPMENT_TYPE_LABELS = {
  armor: "防具",
  ammo: "弹药",
  book: "书籍",
  clothing: "服饰",
  focus: "法器",
  gear: "装备",
  misc: "杂项",
  pack: "套组",
  tool: "工具",
  weapon: "武器",
};
const EMPTY_PENDING_ITEM = { name: "", quantity: 1, reserved_cost_gp: 0, notes: "" };
const EMPTY_CHAR = {
  name: "",
  species: "Human",
  background_name: "",
  origin_feat: "",
  class_name: "",
  starter_option_id: "",
  starter_choice_ids: {},
  equipment_mode: "starter_package",
  custom_purchase_items: {},
  custom_pending_item: { ...EMPTY_PENDING_ITEM },
  hp_max: 10,
  stats: { ...DEFAULT_STATS },
  ability_generation_method: "point_buy",
  ability_rolls: [],
  ability_pool: [],
  ability_assignments: {},
  skill_proficiencies: {},
  selectedCantrips: [],
  selectedSpells: [],
};
const EMPTY_MON = { monster_id: "", name: "", size: "中型", creature_type: "野兽", alignment: "无阵营", challenge_rating: "1", ac: 10, hp_max: 10, initiative_bonus: 0, speed: 30, notes: "", traitsText: "", actionsText: "", reactionsText: "", bonusActionsText: "" };
const EMPTY_ACTIONS = { attack: { attacker_ref: "", attack_name: "", target_ref: "", attack_bonus: 0, damage_expression: "1d6", damage_type: "", resolution_mode: "normal" }, spell: { caster_ref: "", spell_name: "", slot_level: 1 }, skill: { actor_ref: "", skill_name: "", dc: 10, modifier: "" }, save: { target_ref: "", save_name: "", dc: 10, modifier: "" }, item: { user_ref: "", item_name: "", quantity: 1 } };
const EMPTY_ENCOUNTER_DRAFT = { enemy_names: "", enemy_hp: 10, enemy_ac: 10, monster_id: "", quantity: 1, custom_name: "", template_side: "enemy", hp_override: "", quick_enemy_name: "", quick_enemy_hp: 10, quick_enemy_ac: 10, quick_enemy_initiative_bonus: 0, quick_enemy_side: "enemy" };

const parseEntries = (text, prefix) => text.split("\n").map((x) => x.trim()).filter(Boolean).map((description, i) => ({ name: `${prefix} ${i + 1}`, description }));
const entriesToText = (entries = []) => entries.map((x) => x.description).join("\n");
const localizeSceneText = (text = "") => text.replace(/\b(adventure_selection|preparation|setup|exploration|social|combat|encounter)\b/g, (value) => SCENE_LABELS[value] || value);
const mapMessages = (history = [], timeline = []) => {
  const assistantEvents = timeline.filter((event) => event?.type === "assistant_response");
  let assistantEventIndex = 0;
  return history.reduce((items, m, chatIndex) => {
    if (m.kind === "tool_result") return items;
    const assistantEvent = m.role === "assistant" ? assistantEvents[assistantEventIndex++] : null;
    items.push({
      index: items.length,
      chatIndex,
      role: m.role,
      sender: m.role === "assistant" ? "dm" : m.role === "user" ? "player" : "system",
      text: m.role === "system" ? localizeSceneText(m.content) : m.content,
      turnStatus: String(assistantEvent?.payload?.turn_status || ""),
      rollRecords: m.roll_records || [],
      rollRecordsRecorded: Boolean(m.roll_records_recorded),
    });
    return items;
  }, []);
};
const EVENT_LABELS = {
  player_action: "玩家",
  assistant_response: "主持",
  scene_changed: "场景",
  chapter_recorded: "章节",
  dice_result: "骰点",
  hp_changed: "生命",
  attack_resolved: "攻击",
  skill_check: "技能",
  saving_throw: "豁免",
  spell_cast: "施法",
  item_used: "物品",
  turn_advanced: "回合",
  encounter_started: "遭遇",
  monster_template_saved: "模板记录",
  monster_spawned: "遭遇生成",
};
const SHOW_DM_ENCOUNTER_TEMPLATE_TOOLS = false;
const SHOW_DM_CONTROLS_IN_PLAYER_SESSION = false;
const SHOW_WORKFLOW_TRACE_IN_PLAYER_SESSION = false;
const EVENT_SUMMARY_LABELS = {
  "Player action": "玩家行动",
  "DM response": "主持人叙事",
  SCENE_CHANGED: "场景切换",
  CHAPTER_RECORDED: "章节记录",
};
const eventLabel = (t) => EVENT_LABELS[t] || "记录";
const eventSummary = (event) => {
  const summary = EVENT_SUMMARY_LABELS[event?.summary] || event?.summary || eventLabel(event?.type);
  return event?.type === "scene_changed" ? localizeSceneText(summary) : summary;
};
const eventContent = (event) => {
  const content = event?.content || "";
  return event?.type === "scene_changed" ? localizeSceneText(content) : content;
};
const WORKFLOW_NODE_LABELS = {
  turn_started: "启动",
  prepare_turn: "准备",
  input_gate: "输入检查",
  plan_turn: "回合规划",
  route_phase: "路由",
  retrieve_rules: "规则检索",
  prepare_context: "上下文",
  draft_response: "草稿",
  execute_tools: "工具",
  validate_state: "校验",
  enforce_reply_length: "篇幅校正",
  finalize_turn: "收尾",
  rag_completed: "规则检索",
  tool_completed: "工具结果",
  validation_note: "校验备注",
  "agent.dm.entered": "主持接手",
  "agent.dm.tool_batch_serialized": "行动排队",
};
const WORKFLOW_STATUS_LABELS = { started: "开始", completed: "完成", skipped: "跳过", blocked: "暂停", success: "成功", noted: "已记录", warning: "提醒", failed: "失败", error: "错误" };
const workflowNodeLabel = (nodeName) => WORKFLOW_NODE_LABELS[nodeName] || nodeName || "节点";
const workflowStatusLabel = (status) => WORKFLOW_STATUS_LABELS[status] || status || "完成";
const compactWorkflowMetadata = (metadata = {}) => {
  const fields = [];
  if (metadata.mode) fields.push(`模式: ${metadata.mode}`);
  if (metadata.turn_type) fields.push(`意图: ${metadata.turn_type}`);
  if (metadata.rag_intent) fields.push(`RAG: ${metadata.rag_intent}`);
  if (metadata.intent) fields.push(`意图: ${metadata.intent}`);
  if (metadata.rag_used !== undefined) fields.push(`RAG: ${metadata.rag_used ? "使用" : "未用"}`);
  if (metadata.query_count !== undefined) fields.push(`查询: ${metadata.query_count}`);
  if (metadata.snippet_count !== undefined) fields.push(`片段: ${metadata.snippet_count}`);
  if (metadata.source_count !== undefined) fields.push(`来源: ${metadata.source_count}`);
  if (metadata.tool_name) fields.push(`工具: ${metadata.tool_name}`);
  if (metadata.validator) fields.push(`校验: ${metadata.validator}`);
  if (metadata.severity) fields.push(`级别: ${metadata.severity}`);
  if (metadata.action) fields.push(`动作: ${metadata.action}`);
  if (metadata.allowed_tools_count !== undefined) fields.push(`工具: ${metadata.allowed_tools_count}`);
  if (metadata.tool_results_count !== undefined) fields.push(`结果: ${metadata.tool_results_count}`);
  if (metadata.note_index !== undefined) fields.push(`备注: ${Number(metadata.note_index) + 1}`);
  return fields.join(" · ");
};
const getSpellLevel = (spell) => Number(spell?.level ?? 0);
const localizeStat = (stat) => {
  if (!stat) return stat;
  const lower = String(stat).trim().toLowerCase();
  const key = STAT_ABBREVIATION_TO_KEY[lower] || lower;
  return STAT_LABELS[key] || stat;
};
const localizeSkill = (skill) => {
  if (!skill) return skill;
  const key = String(skill).trim().toLowerCase().replace(/[\s-]+/g, "_").replace(/'/g, "");
  return SKILL_LABELS[key] || skill;
};
const localizeClassResource = (name) => CLASS_RESOURCE_NAME_LABELS[name] || name;
const localizeClassName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return CLASS_NAME_LABELS[trimmed] || value;
};
const localizeSpeciesName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return SPECIES_NAME_LABELS[trimmed] || value;
};
const localizeBackgroundName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return BACKGROUND_NAME_LABELS[trimmed] || value;
};
const localizeOriginFeat = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return ORIGIN_FEAT_LABELS[trimmed] || value;
};
const localizeSide = (side) => SIDE_LABELS[side] || side || "未知";
const localizeScene = (scene) => SCENE_LABELS[scene] || scene || "准备";
const normalizeLookupKey = (value) => String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
const localizeSize = (size) => SIZE_LABELS[normalizeLookupKey(size)] || size || "未知体型";
const localizeCreatureType = (type) => CREATURE_TYPE_LABELS[normalizeLookupKey(type)] || type || "未知类型";
const localizeAlignment = (alignment) => ALIGNMENT_LABELS[normalizeLookupKey(alignment)] || alignment || "未知阵营";
const localizeName = (entry) => typeof entry === "string" ? entry : entry?.name_display || entry?.name || "";
const localizeSpellcastingMode = (mode) => mode === "prepared" ? "预备施法" : mode === "known" ? "已知施法" : mode || "未说明";
const formatActorLabel = (actor) => actor.side ? `${actor.name}（${localizeSide(actor.side)}）` : actor.name;
const localizeEquipmentType = (type) => EQUIPMENT_TYPE_LABELS[type] || type || "物品";
const localizeDefeatState = (state) => DEFEAT_STATE_LABELS[state] || state || "正常";
const formatEquipmentLine = (item) => {
  const details = [];
  if (item.quantity && item.quantity > 1) details.push(`数量 ${item.quantity}`);
  if (item.type_display || item.type) details.push(item.type_display || localizeEquipmentType(item.type));
  if (item.damage_expression) details.push(item.damage_expression);
  if (item.damage_type_display || item.damage_type) details.push(item.damage_type_display || item.damage_type);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  if (item.is_equipped) details.push("已装备");
  return details.join(" · ");
};
const formatShopItemMeta = (item) => {
  const details = [formatGoldLine(item.cost_gp)];
  if (Number(item.bundle_size || 1) > 1) details.push(`每份 ${item.bundle_size}`);
  if (item.damage_die) details.push(item.damage_die);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  details.push(item.type_display || localizeEquipmentType(item.type));
  return details.join(" · ");
};
const formatResourceRecovery = (resource) => resource.recovery_display || (resource.recovery === "short_rest" ? "短休" : resource.recovery === "long_rest" ? "长休" : resource.recovery);
const formatSpellSlotLine = ([level, total]) => `${level}环法术位 · ${total}`;
const formatGoldLine = (goldGp) => `${Number(goldGp || 0)} 金币`;
const localizeEquipmentMode = (mode) => mode === "starter_package" ? "标准套装" : mode === "custom_purchase" ? "自定义购买" : "未记录";
const formatAttackSource = (source) => source === "monster_action" ? "怪物动作" : source === "inventory" ? "装备" : source || "攻击";
const formatMonsterSummary = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating}`;
const formatMonsterPreviewLine = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating} · 护甲 ${monster.ac} · 生命 ${monster.hp_max}`;
const formatCombatantStateLine = (combatant) => `生命 ${combatant.hp_current}/${combatant.hp_max} · 护甲 ${combatant.ac} · 先攻 ${combatant.initiative ?? "?"}`;
const formatHpBarLabel = (current, max) => `${current}/${max} 生命`;
const formatSigned = (value) => `${Number(value || 0) >= 0 ? "+" : ""}${Number(value || 0)}`;
const formatAbilityModifier = (score) => formatSigned(Math.floor((Number(score || 10) - 10) / 2));
const formatSpellSlotStatus = ([level, slot]) => {
  const total = Number(slot?.total ?? slot ?? 0);
  const used = Number(slot?.used || 0);
  return `${level}环 ${Math.max(0, total - used)}/${total}`;
};
const formatAttackSummary = (attack) => {
  const details = [];
  if (attack?.attack_bonus !== undefined && attack?.attack_bonus !== "") details.push(`命中 ${formatSigned(attack.attack_bonus)}`);
  if (attack?.damage_expression) details.push(attack.damage_expression);
  if (attack?.damage_type_display || attack?.damage_type) details.push(attack.damage_type_display || attack.damage_type);
  return [localizeName(attack), details.join(" · ")].filter(Boolean).join(" · ");
};
const choiceClassName = (base, selected, disabled, extra = "") => [base, selected ? "selected" : "", disabled ? "is-disabled" : "", extra].filter(Boolean).join(" ");
function ChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return <button type="button" className={choiceClassName("class-card", selected, disabled, className)} aria-pressed={selected} disabled={disabled} {...props}>{children}</button>;
}
function SpellChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return <button type="button" className={choiceClassName("spell-card", selected, disabled, className)} aria-pressed={selected} disabled={disabled} {...props}>{children}</button>;
}
function ShopCarousel({ group, quantities, onQuantityChange }) {
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
                <div className="timeline-summary">{itemName}</div>
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
const QUOTE_PAIRS = new Map([
  ['"', '"'],
  ["'", "'"],
  ["“", "”"],
  ["‘", "’"],
  ["「", "」"],
  ["『", "』"],
  ["《", "》"],
  ["〈", "〉"],
]);

function findClosingQuote(text, openingIndex, openingQuote, closingQuote) {
  for (let index = openingIndex + 1; index < text.length; index += 1) {
    if (text[index] !== closingQuote || text[index - 1] === "\\") continue;
    // 英文缩写中的撇号不是引语边界；中文直引号不受这一限制。
    if (openingQuote === "'" && /[A-Za-z0-9]/.test(text[index + 1] || "")) continue;
    return index;
  }
  return -1;
}

function highlightQuotedText(text) {
  const source = String(text || "");
  const parts = [];
  let plainStart = 0;

  for (let index = 0; index < source.length; index += 1) {
    const openingQuote = source[index];
    const closingQuote = QUOTE_PAIRS.get(openingQuote);
    if (!closingQuote) continue;
    if (openingQuote === "'" && /[A-Za-z0-9]/.test(source[index - 1] || "")) continue;

    const closingIndex = findClosingQuote(source, index, openingQuote, closingQuote);
    if (closingIndex <= index + 1) continue;
    if (plainStart < index) parts.push(source.slice(plainStart, index));
    parts.push(
      <span className="quoted-phrase" key={`quote-${index}`}>
        {source.slice(index, closingIndex + 1)}
      </span>,
    );
    index = closingIndex;
    plainStart = closingIndex + 1;
  }

  if (plainStart < source.length) parts.push(source.slice(plainStart));
  return parts.length ? parts : source;
}

function highlightQuotedChildren(children) {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") return highlightQuotedText(child);
    if (!React.isValidElement(child) || child.type === "code" || child.type === "pre") return child;
    return React.cloneElement(child, {
      children: highlightQuotedChildren(child.props.children),
    });
  });
}

const HIGHLIGHTED_MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p>{highlightQuotedChildren(children)}</p>,
  li: ({ children }) => <li>{highlightQuotedChildren(children)}</li>,
  blockquote: ({ children }) => <blockquote>{highlightQuotedChildren(children)}</blockquote>,
  h1: ({ children }) => <h1>{highlightQuotedChildren(children)}</h1>,
  h2: ({ children }) => <h2>{highlightQuotedChildren(children)}</h2>,
  h3: ({ children }) => <h3>{highlightQuotedChildren(children)}</h3>,
  h4: ({ children }) => <h4>{highlightQuotedChildren(children)}</h4>,
  h5: ({ children }) => <h5>{highlightQuotedChildren(children)}</h5>,
  h6: ({ children }) => <h6>{highlightQuotedChildren(children)}</h6>,
  th: ({ children }) => <th>{highlightQuotedChildren(children)}</th>,
  td: ({ children }) => <td>{highlightQuotedChildren(children)}</td>,
};

function markdownInlineText(children) {
  return React.Children.toArray(children).map((child) => {
    if (typeof child === "string" || typeof child === "number") return String(child);
    if (React.isValidElement(child)) return markdownInlineText(child.props.children);
    return "";
  }).join("");
}

const NARRATIVE_MARKDOWN_COMPONENTS = {
  ...HIGHLIGHTED_MARKDOWN_COMPONENTS,
  em: ({ children }) => {
    const className = narrativeEmphasisClass("em", markdownInlineText(children));
    return <em className={className || undefined}>{children}</em>;
  },
  strong: ({ children }) => {
    const className = narrativeEmphasisClass("strong", markdownInlineText(children));
    return <strong className={className || undefined}>{children}</strong>;
  },
};

function MarkdownBlock({ children, highlightQuotes = false, highlightNarrativeRolls = false }) {
  const components = highlightNarrativeRolls
    ? NARRATIVE_MARKDOWN_COMPONENTS
    : highlightQuotes
      ? HIGHLIGHTED_MARKDOWN_COMPONENTS
      : undefined;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={components}
    >
      {String(children || "")}
    </ReactMarkdown>
  );
}

const asMarkdownQuote = (text) => String(text || "")
  .split("\n")
  .map((line) => `> ${line}`)
  .join("\n");

function RollLedger({ records = [], recorded = true }) {
  const hidden = records.filter((record) => record.visibility === "hidden").length;
  const labels = { dice: "掷骰", attack: "攻击检定", damage: "伤害", skill: "技能检定", save: "豁免", initiative: "先攻", ability: "属性骰" };
  return (
    <details className="turn-roll-ledger">
      <summary>
        <span>本轮骰点</span>
        <small>{recorded ? `${records.length} 次${hidden ? ` · 含 ${hidden} 次暗骰` : ""}` : "未记录"}</small>
      </summary>
      {records.length === 0 ? <p className="roll-empty">{recorded ? "本轮没有执行掷骰。" : "此回合没有保存逐次骰点记录。"}</p> : (
        <ol className="roll-record-list">
          {records.map((record) => (
            <li key={record.record_id} className="roll-record">
              <div className="roll-record-heading">
                <strong>{record.actor ? `${record.actor} · ` : ""}{record.kind === "skill" ? localizeSkill(record.label) : record.kind === "save" ? `${localizeStat(record.label)}豁免` : record.label || labels[record.kind] || "掷骰"}</strong>
                <span className={`roll-visibility ${record.visibility}`}>{record.visibility === "hidden" ? "暗骰" : "明骰"}</span>
              </div>
              {record.target && <div className="roll-record-context">目标：{record.target}</div>}
              <div className="roll-equation"><code>{record.expression}</code><span>{record.detail || `[${record.dice.join(", ")}]`}</span><strong>= {record.total}</strong></div>
              <div className="roll-record-context">
                {record.roll_mode === "advantage" ? "优势 · " : record.roll_mode === "disadvantage" ? "劣势 · " : ""}
                {record.dc != null ? `目标值 ${record.dc} · ` : ""}
                {record.success != null ? `${record.success ? "成功" : "失败"} · ` : ""}
                {rollSettlementLabel(record)}
              </div>
              {record.reason && <p className="roll-reason">{record.reason}</p>}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

function DmThinkingPanel({ thinking, onToggle }) {
  const isRunning = thinking?.status === "running";
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!isRunning) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isRunning]);
  if (!thinking || thinking.status === "idle") return null;
  const isError = thinking.status === "error";
  const isWaiting = thinking.status === "waiting";
  const title = isRunning ? "主持人处理中…" : isError ? "主持过程已中断" : isWaiting ? "等待你的选择" : "主持过程";
  const elapsed = thinking.startedAt ? Math.max(0, Math.floor((now - thinking.startedAt) / 1000)) : 0;
  const statusLabel = isRunning ? `${elapsed} 秒` : isError ? "已中断" : isWaiting ? "待继续" : "已完成";
  const activity = thinking.waitingForModel
    ? `正在等待主持模型${thinking.segmentCount > 1 ? `的第 ${thinking.segmentCount} 次响应` : "响应"}，继续判断和组织剧情。`
    : "正在处理行动和规则结算。";
  const body = thinking.output || (isRunning ? "模型尚未输出公开的过程说明或剧情文本。" : "本轮没有额外的公开过程文本。");

  return (
    <section className={`dm-thinking-panel thinking-${thinking.status}`} aria-label="主持人的思考过程">
      <button
        type="button"
        className="dm-thinking-toggle"
        aria-expanded={thinking.expanded}
        aria-controls="dm-thinking-output"
        onClick={onToggle}
      >
        <span className={`dm-thinking-chevron ${thinking.expanded ? "expanded" : ""}`} aria-hidden="true">›</span>
        <span className="dm-thinking-title">{title}</span>
        <span className="dm-thinking-status" role="status" aria-live="polite">{statusLabel}</span>
      </button>
      {thinking.expanded && (
        <div id="dm-thinking-output" className="dm-thinking-output markdown-body" data-streamed-chars={thinking.output.length}>
          {isRunning && <p className="dm-current-activity" role="status">{activity}{elapsed >= 45 ? " 等待较久，连接仍由心跳检查；请勿重复发送。" : ""}</p>}
          <MarkdownBlock>{asMarkdownQuote(body)}</MarkdownBlock>
        </div>
      )}
    </section>
  );
}

function TimelinePanel({ timeline, title = "时间线", emptyText = "还没有记录。" }) {
  return (
    <section className="panel-card timeline-panel">
      <h3>{title}</h3>
      <div className="timeline-list">
        {timeline.length === 0 && <p className="empty-text">{emptyText}</p>}
        {timeline.map((event) => {
          const content = eventContent(event);
          return (
            <div key={event.event_id} className="timeline-item">
              <div className="timeline-type">{eventLabel(event.type)}</div>
              <div className="timeline-summary">{eventSummary(event)}</div>
              {content && <div className="timeline-content markdown-body"><MarkdownBlock>{content}</MarkdownBlock></div>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
function EvidencePanel({ evidence = [] }) {
  return (
    <section className="panel-card timeline-panel">
      <h3>线索与证据</h3>
      <div className="timeline-list">
        {evidence.length === 0 && <p className="empty-text">DM 尚未确认需要长期保留的线索。</p>}
        {evidence.map((item) => {
          const provenance = [item.source_ref, item.location].filter(Boolean).join(" · ");
          return (
            <div key={item.evidence_id} className="timeline-item">
              <div className="timeline-summary">{item.title}</div>
              {item.summary && <div className="timeline-content">{item.summary}</div>}
              {provenance && <div className="timeline-type">{provenance}</div>}
              {item.tags?.length > 0 && <div className="timeline-content">标签：{item.tags.join("、")}</div>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
function CombatantPanel({ encounter, combatants, initiativeDrafts, setInitiativeDrafts, saveEncounterInitiative, rerollEncounterInitiative, dropEncounterCombatant, localActionsLocked = false }) {
  const nextActorId = encounter?.active && encounter?.turn_order_started ? encounter.current_combatant_id : null;
  return (
    <section className="side-section combat-panel">
      <h3>场上形势</h3>
      {!encounter ? (
        <p className="empty-text">当前没有战斗。</p>
      ) : (
        <div className="combatant-list" aria-label="先攻行动顺序">
          <p className="combat-order-hint">{!encounter.active ? "本次战斗已结束" : encounter.turn_order_started ? `第 ${encounter.round_number} 轮 · 按先攻顺序` : "等待先攻确定"}</p>
          {combatants.map((combatant, index) => (
            <div
              key={combatant.combatant_id}
              className={`combatant-item ${nextActorId === combatant.combatant_id ? "combatant-active" : ""}`}
              aria-current={nextActorId === combatant.combatant_id ? "step" : undefined}
            >
              <div className="timeline-summary combatant-heading">
                <span><span className="combat-order-number">{index + 1}</span>{combatant.name} · {localizeSide(combatant.side)}</span>
                {nextActorId === combatant.combatant_id && <span className="combatant-turn-badge" title="下一次对话从该行动者继续">接下来行动</span>}
              </div>
              <div className="timeline-content">{formatCombatantStateLine(combatant)}</div>
              {SHOW_DM_CONTROLS_IN_PLAYER_SESSION && (
                <fieldset className="pending-action-scope" disabled={localActionsLocked} aria-label="先攻和战斗单位操作">
                  <div className="action-grid" style={{ marginTop: 10 }}>
                    <input value={initiativeDrafts[combatant.combatant_id] ?? ""} onChange={(e) => setInitiativeDrafts((prev) => ({ ...prev, [combatant.combatant_id]: e.target.value }))} placeholder="先攻" />
                    <button className="btn-secondary" onClick={() => saveEncounterInitiative(combatant.combatant_id)}>设置先攻</button>
                    <button className="btn-secondary" onClick={() => rerollEncounterInitiative(combatant.combatant_id)}>重掷先攻</button>
                  </div>
                  {!combatant.linked_character_id && (
                    <div className="btn-row" style={{ marginTop: 10 }}>
                      <button className="btn-danger" onClick={() => dropEncounterCombatant(combatant.combatant_id)}>移除</button>
                    </div>
                  )}
                </fieldset>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
function SpellNames({ names, options = [] }) {
  return names.map((name, index) => {
    const spell = options.find((option) => [option.name, option.nameEN, option.name_display].includes(name)) || {};
    const metadata = [
      spell.level === 0 ? "戏法" : spell.level != null ? `${spell.level} 环` : "",
      spell.school_display || spell.school,
      spell.casting_time && `施法时间：${spell.casting_time}`,
      spell.range && `距离：${spell.range}`,
      spell.duration && `持续：${spell.duration}`,
      spell.components && `成分：${spell.components}`,
      spell.concentration && "需要专注", spell.ritual && "仪式",
    ];
    return (
      <React.Fragment key={name}>
        {index > 0 && "、"}
        <DescriptionTooltip label={localizeName(name)} description={spell.description_display || spell.description}
          metadata={metadata} extra={spell.higher_levels} />
      </React.Fragment>
    );
  });
}

function TurnActionResources({ character, actor, encounter }) {
  const inCombat = Boolean(encounter?.active);
  const combatant = Object.values(encounter?.combatants || {}).find((entry) => entry.linked_character_id === character.character_id);
  const ownTurn = Boolean(combatant && encounter?.current_combatant_id === combatant.combatant_id);
  const slots = [
    { label: "动作", used: encounter?.turn_action_used },
    { label: "附赠动作", used: encounter?.turn_bonus_action_used },
    { label: "反应", used: combatant && encounter?.reactions_used?.[combatant.combatant_id], reaction: true },
  ];
  return (
    <section className="sheet-section turn-resources" aria-label="行动额度">
      <h4>行动额度 <span>{inCombat ? "剩余 / 基础额度" : "战斗中的基础额度"}</span></h4>
      <div className="turn-resource-grid">
        {slots.map((slot) => {
          let value = "1 次", note = "每次自己的回合";
          if (inCombat) {
            value = "— / 1";
            if (!encounter.turn_order_started) note = "等待先攻";
            else if (!combatant || !actor) note = "等待状态";
            else if (!actor.can_act) { value = "0 / 1"; note = "无法行动"; }
            // turn_* 是当前行动者的槽位，不能当作非当前角色的剩余量。
            else if (!ownTurn && !slot.reaction) note = "等待回合";
            else { value = slot.used ? "0 / 1" : "1 / 1"; note = slot.used ? "已使用" : slot.reaction ? "需满足触发条件" : "可用"; }
          }
          return <div className="turn-resource" key={slot.label}><span>{slot.label}</span><strong>{value}</strong><small>{note}</small></div>;
        })}
      </div>
      <p className="turn-resource-note">在自己回合开始时恢复。附赠动作与反应需有对应能力或触发条件。</p>
    </section>
  );
}

function CharacterStatusCard({ character, actor, encounter, primary = false }) {
  const [isOpen, setIsOpen] = useState(primary);
  const [inventoryOpen, setInventoryOpen] = useState(true);
  const stats = character?.stats || {};
  const resources = Object.entries(actor?.resources || character?.resources || {});
  const inventory = actor?.items?.length ? actor.items : character?.inventory || [];
  const spells = actor?.spells || character?.spells || {};
  const cantrips = spells.cantrips || [];
  const prepared = spells.prepared || [];
  const slots = Object.entries(spells.slots || {}).filter(([, slot]) => Number(slot?.total ?? slot ?? 0) > 0);
  const skills = actor?.skills || Object.keys(character?.skill_proficiencies || {});
  const saves = actor?.saves || Object.keys(character?.save_proficiencies || {});
  const attacks = actor?.attacks || [];
  const statuses = character?.status_effects || [];
  const defeatState = character?.defeat_state || "active";

  return (
    <details className={`party-card ${primary ? "party-card-primary" : ""}`} open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary>
        <span className="avatar">{primary ? "主" : "伴"}</span>
        <span className="party-card-title">
          <strong>{character.name}</strong>
          <span>{character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</span>
        </span>
        <span className="party-card-hp">{formatHpBarLabel(character.hp_current, character.hp_max)}</span>
      </summary>
      <div className="party-card-body">
        <div className="hp-bar">
          <div className="fill" style={{ width: `${character.hp_max > 0 ? (character.hp_current / character.hp_max) * 100 : 0}%` }} />
          <span className="text">{formatHpBarLabel(character.hp_current, character.hp_max)}</span>
        </div>
        <div className="party-vitals">
          <span>护甲 {character.ac}</span>
          <span>速度 {character.speed}</span>
          <span>先攻 {formatSigned(character.initiative_bonus)}</span>
          <span>{formatGoldLine(character.gold_gp)}</span>
        </div>
        <div className="stats-hex compact">
          {STATS.map((stat) => (
            <div key={stat} className="stat-point">
              <span className="label">{localizeStat(stat)}</span>
              <span className="val">{stats[stat] ?? 10}</span>
              <span className="mod">{formatAbilityModifier(stats[stat])}</span>
            </div>
          ))}
        </div>
        {(statuses.length > 0 || defeatState !== "active" || character.inspiration) && (
          <div className="tags">
            {character.inspiration && <span className="tag">激励</span>}
            {defeatState !== "active" && <span className="tag">{localizeDefeatState(defeatState)}</span>}
            {statuses.map((status) => <span key={status} className="tag">{status}</span>)}
          </div>
        )}
        <TurnActionResources character={character} actor={actor} encounter={encounter} />
        {resources.length > 0 && (
          <section className="sheet-section">
            <h4>资源</h4>
            {resources.map(([name, resource]) => <div key={name} className="sheet-row"><span>{localizeClassResource(name)}</span><strong>{resource.current_value}/{resource.max_value}</strong></div>)}
          </section>
        )}
        {(cantrips.length > 0 || prepared.length > 0 || slots.length > 0) && (
          <section className="sheet-section">
            <h4>法术</h4>
            {slots.length > 0 && <div className="tags">{slots.map((slot) => <span key={slot[0]} className="tag">{formatSpellSlotStatus(slot)}</span>)}</div>}
            {cantrips.length > 0 && <div className="timeline-content">戏法：<SpellNames names={cantrips} options={spells.options} /></div>}
            {prepared.length > 0 && <div className="timeline-content">准备：<SpellNames names={prepared} options={spells.options} /></div>}
          </section>
        )}
        {attacks.length > 0 && (
          <section className="sheet-section">
            <h4>攻击</h4>
            {attacks.slice(0, 5).map((attack) => <div key={`${character.character_id}-${localizeName(attack)}`} className="sheet-row"><span>{formatAttackSummary(attack)}</span></div>)}
          </section>
        )}
        {(skills.length > 0 || saves.length > 0) && (
          <section className="sheet-section">
            <h4>熟练</h4>
            {skills.length > 0 && <div className="timeline-content">技能：{skills.map(localizeSkill).join("、")}</div>}
            {saves.length > 0 && <div className="timeline-content">豁免：{saves.map(localizeStat).join("、")}</div>}
          </section>
        )}
        <details className="sheet-section inventory-disclosure" open={inventoryOpen} onToggle={(event) => setInventoryOpen(event.currentTarget.open)}>
          <summary><h4>物品栏</h4><span>{inventory.length} 项</span></summary>
          {inventory.length === 0 ? <p className="empty-text">没有记录物品。</p> : inventory.map((item, index) => (
            <div key={`${character.character_id}-item-${item.name}-${index}`} className="inventory-row">
              <DescriptionTooltip label={item.name_display || item.name}
                description={item.description_display || item.description || item.notes_display || item.notes}
                metadata={[item.type_display || localizeEquipmentType(item.type)]} />
              <small>{formatEquipmentLine(item) || item.type_display || localizeEquipmentType(item.type)}</small>
            </div>
          ))}
        </details>
      </div>
    </details>
  );
}
function CharacterSheetDetail({ character }) {
  if (!character) {
    return (
      <div className="character-sheet-empty">
        <h2>选择一张角色卡</h2>
        <p className="info-text">从左侧模板列表选择角色，查看完整角色卡。</p>
      </div>
    );
  }

  const stats = character.stats || {};
  const resources = Object.entries(character.resources || {});
  const inventory = character.inventory || [];
  const attacks = inventory.filter((item) => item.damage_expression || (item.attack_bonus !== null && item.attack_bonus !== undefined));
  const spells = character.spells || {};
  const cantrips = spells.cantrips_display || spells.cantrips || [];
  const prepared = spells.prepared_display || spells.prepared || [];
  const slots = Object.entries(spells.slots || {}).filter(([, slot]) => Number(slot?.total ?? slot ?? 0) > 0);
  const skills = Object.entries(character.skill_proficiencies || {}).filter(([, rank]) => Number(rank) > 0);
  const saves = Object.entries(character.save_proficiencies || {}).filter(([, proficient]) => Boolean(proficient));
  const statuses = character.status_effects_display || character.status_effects || [];
  const experiences = character.major_experiences || [];
  const starterChoices = Object.entries(character.starter_choice_ids || {});

  return (
    <article className="character-sheet">
      <header className="character-sheet-hero">
        <div className="sheet-sigil">角</div>
        <div>
          <p className="eyebrow">角色卡模板</p>
          <h1>{character.name}</h1>
          <p>{localizeSpeciesName(character.species || character.race)} · {localizeBackgroundName(character.background_name || character.background)} · {character.class_name_display || localizeClassName(character.class_name)} {character.level}级</p>
        </div>
      </header>

      <section className="sheet-vital-strip">
        <div><span>生命</span><strong>{character.hp_current}/{character.hp_max}</strong></div>
        <div><span>临时生命</span><strong>{character.temp_hp || 0}</strong></div>
        <div><span>护甲</span><strong>{character.ac}</strong></div>
        <div><span>速度</span><strong>{character.speed}</strong></div>
        <div><span>先攻</span><strong>{formatSigned(character.initiative_bonus)}</strong></div>
        <div><span>财富</span><strong>{formatGoldLine(character.gold_gp)}</strong></div>
      </section>

      <div className="character-sheet-grid">
        <section className="sheet-panel ability-panel">
          <h3>属性</h3>
          <div className="ability-score-grid">
            {STATS.map((stat) => (
              <div key={stat} className="ability-score">
                <span>{localizeStat(stat)}</span>
                <strong>{stats[stat] ?? 10}</strong>
                <em>{formatAbilityModifier(stats[stat])}</em>
              </div>
            ))}
          </div>
          <p className="sheet-panel-note">生成方式：{ABILITY_METHOD_LABELS[character.ability_generation_method || "point_buy"] || character.ability_generation_method}</p>
        </section>

        <section className="sheet-panel identity-panel">
          <h3>身份</h3>
          <div className="sheet-data-grid">
            <div><span>等级</span><strong>{character.level || 1}级</strong></div>
            <div><span>阵营</span><strong>{character.alignment_display || localizeAlignment(character.alignment) || "未说明"}</strong></div>
            <div><span>起源专长</span><strong>{localizeOriginFeat(character.origin_feat) || "未记录"}</strong></div>
            <div><span>经验值</span><strong>{character.experience_points || 0}</strong></div>
            <div><span>激励</span><strong>{character.inspiration ? "有" : "无"}</strong></div>
            <div><span>状态</span><strong>{localizeDefeatState(character.defeat_state)}</strong></div>
          </div>
          {statuses.length > 0 && <div className="tags sheet-tags">{statuses.map((status) => <span key={status} className="tag">{status}</span>)}</div>}
        </section>

        <section className="sheet-panel">
          <h3>熟练</h3>
          {skills.length === 0 && saves.length === 0 ? <p className="empty-text">没有记录熟练项。</p> : (
            <>
              {skills.length > 0 && <p className="timeline-content">技能：{skills.map(([skill]) => localizeSkill(skill)).join("、")}</p>}
              {saves.length > 0 && <p className="timeline-content">豁免：{saves.map(([save]) => localizeStat(save)).join("、")}</p>}
            </>
          )}
        </section>

        <section className="sheet-panel">
          <h3>职业资源</h3>
          {resources.length === 0 ? <p className="empty-text">没有可追踪资源。</p> : resources.map(([name, resource]) => (
            <div key={name} className="sheet-row">
              <span>{localizeClassResource(name)}</span>
              <strong>{resource.current_value}/{resource.max_value}</strong>
            </div>
          ))}
        </section>

        <section className="sheet-panel">
          <h3>攻击</h3>
          {attacks.length === 0 ? <p className="empty-text">没有记录武器或攻击项。</p> : attacks.map((attack, index) => (
            <div key={`${attack.name}-${index}`} className="attack-card">
              <strong>{attack.name_display || attack.name}</strong>
              <span>{formatAttackSummary(attack) || "攻击资料未完整记录"}</span>
              {(attack.properties_display || attack.properties)?.length > 0 && <small>{(attack.properties_display || attack.properties).join("、")}</small>}
            </div>
          ))}
        </section>

        <section className="sheet-panel">
          <h3>法术</h3>
          {(cantrips.length === 0 && prepared.length === 0 && slots.length === 0) ? <p className="empty-text">该角色没有记录法术。</p> : (
            <>
              <div className="sheet-data-grid compact">
                <div><span>施法属性</span><strong>{localizeStat(spells.ability)}</strong></div>
                <div><span>施法方式</span><strong>{localizeSpellcastingMode(spells.casting_mode)}</strong></div>
              </div>
              {slots.length > 0 && <div className="tags sheet-tags">{slots.map((slot) => <span key={slot[0]} className="tag">{formatSpellSlotStatus(slot)}</span>)}</div>}
              {cantrips.length > 0 && <p className="timeline-content">戏法：{cantrips.map(localizeName).join("、")}</p>}
              {prepared.length > 0 && <p className="timeline-content">准备：{prepared.map(localizeName).join("、")}</p>}
            </>
          )}
        </section>

        <section className="sheet-panel inventory-panel">
          <h3>物品栏</h3>
          {inventory.length === 0 ? <p className="empty-text">没有记录物品。</p> : inventory.map((item, index) => (
            <div key={`${item.name}-${index}`} className="inventory-card">
              <div>
                <strong>{item.name_display || item.name}</strong>
                <span>{formatEquipmentLine(item) || item.type_display || localizeEquipmentType(item.type)}</span>
              </div>
              <em>x{item.quantity || 1}</em>
              {item.notes && <p>{item.notes}</p>}
              {(item.tags_display || item.tags)?.length > 0 && <small>{(item.tags_display || item.tags).join("、")}</small>}
            </div>
          ))}
        </section>

        <section className="sheet-panel">
          <h3>起始装备</h3>
          <div className="sheet-data-grid">
            <div><span>职业套装</span><strong>{character.starter_option_id ? "已选择" : "未记录"}</strong></div>
            <div><span>装备方式</span><strong>{localizeEquipmentMode(character.equipment_mode)}</strong></div>
          </div>
          {starterChoices.length > 0 && <p className="timeline-content">套装选择：已记录 {starterChoices.length} 项</p>}
          {character.custom_purchase_items?.length > 0 && <p className="timeline-content">自定义购买：已记录 {character.custom_purchase_items.length} 项</p>}
          {character.custom_pending_item?.name && <p className="timeline-content">待定装备：{character.custom_pending_item.name}</p>}
        </section>

        <section className="sheet-panel experiences-panel">
          <h3>经历</h3>
          {experiences.length === 0 ? <p className="empty-text">还没有记录重要经历。</p> : experiences.map((entry, index) => <p key={`${entry}-${index}`} className="timeline-content">{entry}</p>)}
        </section>
      </div>
    </article>
  );
}
const resolveStarterPreviewItems = (starterOption, starterChoiceIds = {}) => {
  if (!starterOption) return [];
  const resolved = [...(starterOption.items || [])];
  for (const choiceGroup of starterOption.choices || []) {
    const selectedId = starterChoiceIds[choiceGroup.id];
    const selectedOption = (choiceGroup.options || []).find((option) => option.id === selectedId);
    if (selectedOption) resolved.push(...(selectedOption.items || []));
  }
  return resolved;
};

export default function App() {
  const [view, setView] = useState("home");
  const [games, setGames] = useState([]), [characters, setCharacters] = useState([]), [monsters, setMonsters] = useState([]);
  const [builder, setBuilder] = useState({ ability_generation: {}, species: [], backgrounds: [], origin_feats: [], classes: [], equipment_shop_items: [] }), [spellList, setSpellList] = useState([]);
  const [charDraft, setCharDraft] = useState({ ...EMPTY_CHAR }), [monsterDraft, setMonsterDraft] = useState({ ...EMPTY_MON });
  const [encounterDraft, setEncounterDraft] = useState({ ...EMPTY_ENCOUNTER_DRAFT });
  const [encounterMonsterPreview, setEncounterMonsterPreview] = useState(null);
  const [initiativeDrafts, setInitiativeDrafts] = useState({});
  const [selectedGameChars, setSelectedGameChars] = useState([]), [newGameId, setNewGameId] = useState("");
  const [activeGameId, setActiveGameId] = useState(null), [gameState, setGameState] = useState(null), [actionOptions, setActionOptions] = useState({ actors: [] });
  const [actionDraft, setActionDraft] = useState({ ...EMPTY_ACTIONS }), [messages, setMessages] = useState([]);
  const [actionSuggestions, setActionSuggestions] = useState([]);
  const [isActionSuggestionsLoading, setIsActionSuggestionsLoading] = useState(false);
  const [workflowEvents, setWorkflowEvents] = useState([]);
  const [dmThinking, setDmThinking] = useState(createEmptyDmThinking);
  const [input, setInput] = useState(""), [isLoading, setIsLoading] = useState(false), [error, setError] = useState("");
  const [replyLengthDraft, setReplyLengthDraft] = useState({ min_chars: "", max_chars: "" });
  const [isReplyLengthSaving, setIsReplyLengthSaving] = useState(false);
  const [replyLengthMessage, setReplyLengthMessage] = useState("");
  const [llmConfig, setLlmConfig] = useState(null);
  const [llmHealth, setLlmHealth] = useState(null);
  const [llmDraft, setLlmDraft] = useState({ ...EMPTY_LLM_DRAFT });
  const [isLlmSaving, setIsLlmSaving] = useState(false);
  const [llmStatusMessage, setLlmStatusMessage] = useState("");
  const [pendingAdventureId, setPendingAdventureId] = useState(null);
  const [isBuilderLoading, setIsBuilderLoading] = useState(false);
  const [isAbilityGenerating, setIsAbilityGenerating] = useState(false);
  const [isLobbyLoading, setIsLobbyLoading] = useState(true);
  const [creatorStep, setCreatorStep] = useState(0);
  const [selectedCharacter, setSelectedCharacter] = useState(null);
  const [isCharacterLoading, setIsCharacterLoading] = useState(false);
  const [rewriteTarget, setRewriteTarget] = useState(null);
  const [retryingMessageIndex, setRetryingMessageIndex] = useState(null);
  const [deleteRequest, setDeleteRequest] = useState(null);
  const [gameDeleteMode, setGameDeleteMode] = useState(false);
  const [selectedGameDeleteIds, setSelectedGameDeleteIds] = useState([]);
  const [characterDeleteMode, setCharacterDeleteMode] = useState(false);
  const [selectedCharacterDeleteIds, setSelectedCharacterDeleteIds] = useState([]);
  const messagesEndRef = useRef(null);
  const chatInputRef = useRef(null);
  const activeGameIdRef = useRef(null);
  const latestTurnNumberRef = useRef(0);
  const actionSuggestionRequestRef = useRef(0);
  const gameLifecycleRef = useRef(0);
  const gameSyncRequestRef = useRef(0);
  const optimisticMessageIdRef = useRef(0);

  useEffect(() => { refreshLobby(); }, []);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: isLoading ? "auto" : "smooth" });
  }, [messages, workflowEvents, isLoading, dmThinking.output]);
  useEffect(() => {
    const nextDrafts = {};
    for (const combatant of gameState?.encounter?.initiative_order?.map((id) => gameState?.encounter?.combatants?.[id]).filter(Boolean) || []) {
      nextDrafts[combatant.combatant_id] = combatant.initiative ?? "";
    }
    setInitiativeDrafts(nextDrafts);
  }, [gameState?.encounter]);

  const classDef = builder.classes.find((c) => c.name === charDraft.class_name);
  const background = builder.backgrounds.find((b) => b.name === charDraft.background_name);
  const backgroundSkills = new Set(background?.skill_proficiencies || []);
  const builderReady = builder.species.length > 0 && builder.backgrounds.length > 0 && builder.classes.length > 0;
  const pointBuyRules = builder.ability_generation?.point_buy || { budget: 27, minimum: 8, maximum: 15 };
  const starterOptions = classDef?.starter_equipment_options || [];
  const selectedStarterOption = starterOptions.find((option) => option.id === charDraft.starter_option_id) || starterOptions[0] || null;
  const starterChoiceGroups = selectedStarterOption?.choices || [];
  const starterChoicesComplete = starterChoiceGroups.every((group) => Boolean(charDraft.starter_choice_ids[group.id]));
  const starterEquipment = resolveStarterPreviewItems(selectedStarterOption, charDraft.starter_choice_ids);
  const starterGoldGp = Number(selectedStarterOption?.gold_gp || 0);
  const equipmentShopItems = builder.equipment_shop_items || [];
  const equipmentShopById = Object.fromEntries(equipmentShopItems.map((item) => [item.id, item]));
  const shopTypeOrder = ["armor", "weapon", "focus", "tool", "pack", "book", "clothing", "gear", "ammo"];
  const groupedShopItems = shopTypeOrder
    .map((type) => ({ type, items: equipmentShopItems.filter((item) => item.type === type) }))
    .filter((group) => group.items.length > 0);
  const starterResources = Object.entries(classDef?.resources || {});
  const startingSpellSlots = Object.entries(classDef?.starting_spell_slots || {});
  const cantripOptions = spellList.filter((spell) => getSpellLevel(spell) === 0);
  const levelOnePreparedSpells = spellList.filter((spell) => getSpellLevel(spell) > 0);
  const startingCantripCount = Number(classDef?.starting_cantrips || 0);
  const startingPreparedSpellCount = Number(classDef?.starting_prepared_spells || 0);
  const hasCantripSelection = Boolean(classDef?.spellcasting_ability) && startingCantripCount > 0;
  const hasLevelOneSpellcasting = Boolean(classDef?.spellcasting_ability) && startingSpellSlots.some(([, total]) => Number(total) > 0);
  const cantripSelectionComplete = !hasCantripSelection || charDraft.selectedCantrips.length === startingCantripCount;
  const spellSelectionComplete = !hasLevelOneSpellcasting || startingPreparedSpellCount === 0 || charDraft.selectedSpells.length === startingPreparedSpellCount;
  const classSkillTarget = Number(classDef?.skills_to_choose || 0);
  const selectedClassSkillCount = Object.entries(charDraft.skill_proficiencies || {}).filter(([skill, rank]) => Number(rank) > 0 && !backgroundSkills.has(skill)).length;
  const pointBuySpent = STATS.reduce((total, stat) => total + (POINT_BUY_COSTS[Number(charDraft.stats?.[stat] || 0)] ?? 0), 0);
  const pointBuyRemaining = Number(pointBuyRules.budget || 27) - pointBuySpent;
  const abilityGenerationMethod = charDraft.ability_generation_method || "point_buy";
  const abilityPool = charDraft.ability_pool || [];
  const abilityAssignments = charDraft.ability_assignments || {};
  const abilityAssignmentComplete = abilityGenerationMethod === "point_buy"
    || (abilityPool.length === STATS.length && STATS.every((stat) => abilityAssignments[stat]));
  const computedHpMax = classDef ? Math.max(1, Number(classDef.hit_die || 8) + Math.floor((Number(charDraft.stats?.constitution || 10) - 10) / 2)) : Number(charDraft.hp_max || 10);
  const customPurchaseBudgetGp = Number(classDef?.custom_purchase_budget_gp || 0);
  const customPurchaseEntries = Object.entries(charDraft.custom_purchase_items || {}).filter(([, quantity]) => Number(quantity) > 0);
  const customPurchaseSpentGp = customPurchaseEntries.reduce((total, [itemId, quantity]) => total + Number(equipmentShopById[itemId]?.cost_gp || 0) * Number(quantity || 0), 0);
  const hasPendingCustomItem = Boolean(charDraft.custom_pending_item?.name?.trim());
  const pendingCustomCostGp = hasPendingCustomItem ? Number(charDraft.custom_pending_item?.reserved_cost_gp || 0) : 0;
  const equipmentBudgetGp = charDraft.equipment_mode === "custom_purchase" ? customPurchaseBudgetGp : starterGoldGp;
  const equipmentSpentGp = (charDraft.equipment_mode === "custom_purchase" ? customPurchaseSpentGp : 0) + pendingCustomCostGp;
  const equipmentRemainingGp = equipmentBudgetGp - equipmentSpentGp;
  const pendingCustomTouched = Boolean(charDraft.custom_pending_item?.notes?.trim())
    || Number(charDraft.custom_pending_item?.reserved_cost_gp || 0) !== 0
    || Number(charDraft.custom_pending_item?.quantity || 1) !== 1;
  const customPurchasePreviewItems = customPurchaseEntries
    .map(([itemId, quantity]) => ({ ...equipmentShopById[itemId], purchase_quantity: Number(quantity || 0) }))
    .filter((item) => item?.id);
  const pendingCustomPreviewItem = hasPendingCustomItem ? {
    name: charDraft.custom_pending_item.name.trim(),
    quantity: Number(charDraft.custom_pending_item.quantity || 1),
    type: "gear",
    notes: charDraft.custom_pending_item.notes?.trim() || "由主持人在角色创建后补充具体属性",
  } : null;
  const finalEquipmentPreview = [
    ...(charDraft.equipment_mode === "custom_purchase" ? customPurchasePreviewItems.map((item) => ({
      name: item.name_display || item.name,
      quantity: Number(item.bundle_size || 1) * Number(item.purchase_quantity || 1),
      type: item.type_display || localizeEquipmentType(item.type),
      damage_expression: item.damage_die || "",
      armor_class_bonus: Number(item.armor_class_bonus || 0),
    })) : starterEquipment),
    ...(pendingCustomPreviewItem ? [pendingCustomPreviewItem] : []),
  ];
  const actorList = (actionOptions.actors || []).map((a) => ({ value: a.ref, label: formatActorLabel(a) }));
  // 只接受同版本的动作选项，避免取消暂停后的新快照被迟到的旧选项继续锁住。
  const localActionsLocked = Boolean(gameState?.pending_turn) || Boolean(gameState
    && actionOptions.state_version === gameState.state_version && actionOptions.local_actions_allowed === false);
  const localActionBlockMessage = actionOptions.local_actions_block_reason || "请先完成或取消当前剧情选择，再执行本地动作或修改本局设置。";
  const charActors = (actionOptions.actors || []).filter((a) => a.type === "character");
  const encounterSummary = actionOptions.encounter || { active: false };
  const currentActorEntry = (actionOptions.actors || []).find((actor) => actor.is_current_actor);
  const attackActor = (actionOptions.actors || []).find((a) => a.ref === actionDraft.attack.attacker_ref);
  const attackChoices = attackActor?.attacks || [];
  const spellActor = charActors.find((a) => a.ref === actionDraft.spell.caster_ref);
  const spellOptionEntries = spellActor?.spells?.options || [];
  const spellOptions = spellOptionEntries.map((spell) => ({
    name: spell.name,
    label: spell.requires_slot
      ? `${spell.name}（${spell.level}环${spell.available ? "" : " · 无法术位"}）`
      : `${spell.name}（戏法）`,
  }));
  const selectedSpellOption = spellOptionEntries.find((spell) => spell.name === actionDraft.spell.spell_name);
  const itemActor = charActors.find((a) => a.ref === actionDraft.item.user_ref);
  const selectedItemOption = (itemActor?.items || []).find((item) => item.name === actionDraft.item.item_name);
  const skillActor = (actionOptions.actors || []).find((a) => a.ref === actionDraft.skill.actor_ref);
  const saveTargetActor = (actionOptions.actors || []).find((a) => a.ref === actionDraft.save.target_ref);
  const attackTurnLocked = Boolean(encounterSummary.active && attackActor && !attackActor.is_current_actor);
  const spellTurnLocked = Boolean(encounterSummary.active && spellActor && !spellActor.is_current_actor && selectedSpellOption?.action_cost !== "reaction");
  const skillTurnLocked = Boolean(encounterSummary.active && skillActor && !skillActor.is_current_actor);
  const itemTurnLocked = Boolean(encounterSummary.active && itemActor && !itemActor.is_current_actor);
  const attackMetadataLocked = attackChoices.length > 0 && Boolean(actionDraft.attack.attack_name);
  const attackButtonDisabled = !actionDraft.attack.attacker_ref
    || !actionDraft.attack.target_ref
    || attackTurnLocked
    || (attackChoices.length > 0 && !actionDraft.attack.attack_name)
    || (attackChoices.length === 0 && !String(actionDraft.attack.damage_expression || "").trim());
  const advanceTurnDisabled = !encounterSummary.active;
  const castButtonDisabled = !selectedSpellOption
    || spellTurnLocked
    || spellActor?.can_act === false
    || selectedSpellOption?.available === false
    || (selectedSpellOption?.action_cost === "reaction" && spellActor?.reaction_available === false)
    || (selectedSpellOption?.requires_attack_target && !actionDraft.spell.target_ref)
    || ((selectedSpellOption?.damage_types || []).length > 1 && !actionDraft.spell.damage_type)
    || (selectedSpellOption.requires_slot && !selectedSpellOption.available_slot_levels.includes(Number(actionDraft.spell.slot_level || 0)));
  const useItemDisabled = !selectedItemOption
    || itemTurnLocked
    || Number(actionDraft.item.quantity || 1) <= 0
    || Number(actionDraft.item.quantity || 1) > Number(selectedItemOption.quantity || 0);
  const isRewriteInFlight = Boolean(rewriteTarget && isLoading);
  // 重写提交后，旧分支里的 interrupt 选择也属于待回退投影，不能在新快照返回前继续显示。
  const pendingTurn = isRewriteInFlight ? null : gameState?.pending_turn || null;
  const isPlayerChoicePending = pendingTurn?.kind === "player_choice";
  const isLegacyConfirmationPending = pendingTurn?.kind === "tool_confirmation";
  const playerChoiceOptions = isPlayerChoicePending && Array.isArray(pendingTurn?.details?.options)
    ? pendingTurn.details.options.map((option) => String(option || "").trim()).filter(Boolean)
    : [];
  const pendingOriginalInput = String(pendingTurn?.original_input || "").trim();
  const lastAuthoritativeMessage = messages.reduce((last, item) => item.optimistic ? last : item, null);
  const pendingInputAlreadyRecorded = pendingOriginalInput
    && lastAuthoritativeMessage?.sender === "player"
    && String(lastAuthoritativeMessage.text || "").trim() === pendingOriginalInput;
  let visibleMessages = messages;
  if (pendingOriginalInput && !pendingInputAlreadyRecorded) {
    const firstOptimisticIndex = messages.findIndex((item) => item.optimistic);
    const insertionIndex = firstOptimisticIndex < 0 ? messages.length : firstOptimisticIndex;
    const pendingContextMessage = {
      index: insertionIndex,
      chatIndex: null,
      role: "user",
      sender: "player",
      text: pendingOriginalInput,
      pendingContext: true,
      renderKey: `pending-player-${activeGameId}-${pendingOriginalInput}`,
    };
    visibleMessages = [
      ...messages.slice(0, insertionIndex),
      pendingContextMessage,
      ...messages.slice(insertionIndex),
    ];
  }
  const chatComposerDisabled = gameState?.campaign?.phase === "adventure_selection";
  const isGameMutationBusy = isLoading || isReplyLengthSaving;
  const chatSubmitDisabled = chatComposerDisabled || isGameMutationBusy;
  const selectedGameDeleteSet = new Set(selectedGameDeleteIds);
  const selectedCharacterDeleteSet = new Set(selectedCharacterDeleteIds);
  const selectedGameDeleteCount = selectedGameDeleteIds.length;
  const selectedCharacterDeleteCount = selectedCharacterDeleteIds.length;
  const llmProfiles = llmConfig?.profiles || [];
  const activeLlmProfile = llmProfiles.find((profile) => profile.profile_id === llmConfig?.active_profile_id) || null;
  const editingLlmProfile = llmProfiles.find((profile) => profile.profile_id === llmDraft.profile_id) || null;
  const llmHealthMessage = formatLlmHealthMessage(llmHealth);
  const llmConnectionLabel = isLobbyLoading
    ? "读取中"
    : llmHealth?.ready
      ? llmConfig?.provider === "openai-compatible" ? "可用" : "CLI 已安装"
      : llmConfig?.configured
        ? "连接失败"
        : "未完整配置";
  const llmAuthorizationFailed = Number(llmHealth?.status_code) === 401;

  useEffect(() => {
    if (!encounterDraft.monster_id) {
      setEncounterMonsterPreview(null);
      return;
    }

    let cancelled = false;
    loadMonsterTemplate(encounterDraft.monster_id)
      .then((monster) => {
        if (!cancelled) setEncounterMonsterPreview(monster);
      })
      .catch(() => {
        if (!cancelled) setEncounterMonsterPreview(null);
      });

    return () => {
      cancelled = true;
    };
  }, [encounterDraft.monster_id]);

  function freshCharacterDraft() {
    return {
      ...EMPTY_CHAR,
      stats: { ...DEFAULT_STATS },
      ability_generation_method: "point_buy",
      ability_rolls: [],
      ability_pool: [],
      ability_assignments: {},
      starter_choice_ids: {},
      custom_purchase_items: {},
      custom_pending_item: { ...EMPTY_PENDING_ITEM },
      skill_proficiencies: {},
      selectedCantrips: [],
      selectedSpells: [],
    };
  }

  function applyBuilderCatalog(rules) {
    setBuilder({
      ability_generation: rules.ability_generation || {},
      species: rules.species || [],
      backgrounds: rules.backgrounds || [],
      origin_feats: rules.origin_feats || [],
      classes: rules.classes || [],
      equipment_shop_items: rules.equipment_shop_items || [],
    });
  }

  async function loadBuilderCatalog(clearError = true) {
    try {
      setIsBuilderLoading(true);
      if (clearError) setError("");
      const rules = await loadCharacterBuilder();
      applyBuilderCatalog(rules);
      return true;
    } catch (err) {
      setError(err.message || "加载角色构筑规则失败。");
      return false;
    } finally {
      setIsBuilderLoading(false);
    }
  }

  function applyLlmConfig(payload) {
    const nextConfig = payload || {};
    const nextProfiles = nextConfig.profiles || [];
    const activeProfile = nextProfiles.find((profile) => profile.profile_id === nextConfig.active_profile_id) || nextProfiles[0] || {};
    const provider = activeProfile.provider || nextConfig.provider || "codex-cli";
    setLlmConfig(nextConfig);
    setLlmDraft({
      profile_id: activeProfile.profile_id || "",
      profile_label: activeProfile.label || "",
      provider,
      model_name: activeProfile.model_name || nextConfig.model_name || (provider === "codex-cli" ? CODEX_DEFAULT_MODEL : ""),
      reasoning_effort: activeProfile.reasoning_effort || nextConfig.reasoning_effort || (provider === "codex-cli" ? CODEX_DEFAULT_REASONING_EFFORT : ""),
      base_url: activeProfile.raw_base_url || nextConfig.raw_base_url || nextConfig.base_url || "",
      api_key: "",
      cli_command: activeProfile.cli_command || nextConfig.cli_command || (provider === "codex-cli" ? "codex" : provider === "claude-code" ? "claude" : ""),
      cli_timeout_s: activeProfile.cli_timeout_s || nextConfig.cli_timeout_s || 300,
    });
  }

  async function refreshLobby() {
    setIsBuilderLoading(true);
    setError("");
    const [lobbyResult, rulesResult, llmResult, llmHealthResult] = await Promise.allSettled([
      loadLobby(),
      loadCharacterBuilder(),
      loadModelConfig(),
      loadModelHealth(),
    ]);
    let nextError = "";

    if (lobbyResult.status === "fulfilled") {
      setGames(lobbyResult.value.games || []);
      setCharacters(lobbyResult.value.characters || []);
      setMonsters(lobbyResult.value.monsters || []);
    } else {
      nextError = lobbyResult.reason?.message || "加载大厅失败。";
    }

    if (rulesResult.status === "fulfilled") {
      applyBuilderCatalog(rulesResult.value);
    } else if (!nextError) {
      nextError = rulesResult.reason?.message || "加载角色构筑规则失败。";
    }

    if (llmResult.status === "fulfilled") {
      applyLlmConfig(llmResult.value);
    } else if (!nextError) {
      nextError = llmResult.reason?.message || "加载模型配置失败。";
    }

    if (llmHealthResult.status === "fulfilled") {
      setLlmHealth(llmHealthResult.value);
    } else {
      setLlmHealth({ ready: false, reason: "health_check_failed" });
    }

    setIsBuilderLoading(false);
    setIsLobbyLoading(false);
    if (nextError) setError(nextError);
  }

  async function saveLlmConfig(event) {
    event.preventDefault();
    const profileLabel = llmDraft.profile_label.trim();
    const provider = llmDraft.provider || "openai-compatible";
    const modelName = llmDraft.model_name.trim();
    const baseUrl = llmDraft.base_url.trim();
    if (!profileLabel) return setLlmStatusMessage("请填写条目名称。");
    if (provider === "openai-compatible" && !modelName) return setLlmStatusMessage("请填写模型名称。");
    if (provider === "openai-compatible" && !baseUrl) return setLlmStatusMessage("请填写 Base URL。");

    setIsLlmSaving(true);
    setLlmStatusMessage("");
    setError("");
    try {
      const payload = {
        profile_id: llmDraft.profile_id,
        profile_label: profileLabel,
        provider,
        model_name: modelName,
        reasoning_effort: llmDraft.reasoning_effort || "",
        base_url: baseUrl,
        cli_command: llmDraft.cli_command.trim(),
        cli_timeout_s: Number(llmDraft.cli_timeout_s) || 300,
        activate: true,
      };
      const nextKey = llmDraft.api_key.trim();
      if (nextKey) payload.api_key = nextKey;
      const result = await updateModelConfig(payload);
      applyLlmConfig(result.llm || result);
      const health = await loadModelHealth();
      setLlmHealth(health);
      setLlmStatusMessage(health.ready
        ? provider === "openai-compatible" ? "模型档案已保存并启用，连接验证成功。" : "模型档案已保存并启用，CLI 安装检查成功；登录态将在首次调用时验证。"
        : `模型档案已保存，但${formatLlmHealthMessage(health)}`);
    } catch (err) {
      setLlmStatusMessage(err.message || "保存模型配置失败。");
    } finally {
      setIsLlmSaving(false);
    }
  }

  async function chooseLlmProfile(profileId) {
    if (!profileId || isLlmSaving) return;
    setIsLlmSaving(true);
    setLlmStatusMessage("");
    setError("");
    try {
      const result = await selectModelConfig(profileId);
      applyLlmConfig(result.llm || result);
      const health = await loadModelHealth();
      setLlmHealth(health);
      setLlmStatusMessage(health.ready
        ? (health.provider === "openai-compatible" ? "模型档案已切换，连接验证成功。" : "模型档案已切换，CLI 安装检查成功；登录态将在首次调用时验证。")
        : `模型档案已切换，但${formatLlmHealthMessage(health)}`);
    } catch (err) {
      setLlmStatusMessage(err.message || "切换模型档案失败。");
    } finally {
      setIsLlmSaving(false);
    }
  }

  function beginNewLlmProfile() {
    setLlmDraft({ ...EMPTY_LLM_DRAFT });
    setLlmStatusMessage("正在创建新模型档案。");
  }

  async function openCreator() {
    setCharDraft(freshCharacterDraft());
    setCreatorStep(0);
    setSpellList([]);
    setView("creator");
    if (!builderReady) {
      await loadBuilderCatalog(false);
    }
  }

  function openCharacterLibrary() {
    setError("");
    setSelectedCharacter(null);
    setView("characters");
  }

  async function openCharacterSheet(identifier) {
    if (!identifier) return;
    try {
      setError("");
      setIsCharacterLoading(true);
      setView("characters");
      const character = await loadCharacter(identifier);
      setSelectedCharacter(character);
    } catch (err) {
      setError(err.message || "读取角色卡失败。");
    } finally {
      setIsCharacterLoading(false);
    }
  }

  function beginDeleteRequest(kind, entries) {
    const ids = [...new Set(entries.map((entry) => entry.id).filter(Boolean))];
    if (ids.length === 0) return;
    setError("");
    const targetLabel = ids.length === 1
      ? entries.find((entry) => entry.id === ids[0])?.label || ids[0]
      : `${ids.length} ${kind === "game" ? "个已保存游戏" : "张角色卡模板"}`;
    setDeleteRequest({
      kind,
      ids,
      label: targetLabel,
      count: ids.length,
      step: 1,
      busy: false,
    });
  }

  function requestGameDeletion(game) {
    beginDeleteRequest("game", [{ id: game.game_id, label: game.title || game.game_id }]);
  }

  function requestCharacterDeletion(character) {
    beginDeleteRequest("character", [{ id: character.character_id, label: character.name || character.character_id }]);
  }

  function toggleGameDeleteMode() {
    const nextMode = !gameDeleteMode;
    setGameDeleteMode(nextMode);
    if (!nextMode) setSelectedGameDeleteIds([]);
  }

  function toggleCharacterDeleteMode() {
    const nextMode = !characterDeleteMode;
    setCharacterDeleteMode(nextMode);
    if (!nextMode) setSelectedCharacterDeleteIds([]);
  }

  function toggleGameDeleteSelection(gameId) {
    setSelectedGameDeleteIds((prev) => (
      prev.includes(gameId) ? prev.filter((item) => item !== gameId) : [...prev, gameId]
    ));
  }

  function toggleCharacterDeleteSelection(characterId) {
    setSelectedCharacterDeleteIds((prev) => (
      prev.includes(characterId) ? prev.filter((item) => item !== characterId) : [...prev, characterId]
    ));
  }

  function requestSelectedGameDeletion() {
    const entries = games
      .filter((game) => selectedGameDeleteSet.has(game.game_id))
      .map((game) => ({ id: game.game_id, label: game.title || game.game_id }));
    beginDeleteRequest("game", entries);
  }

  function requestSelectedCharacterDeletion() {
    const entries = characters
      .filter((character) => selectedCharacterDeleteSet.has(character.character_id))
      .map((character) => ({ id: character.character_id, label: character.name || character.character_id }));
    beginDeleteRequest("character", entries);
  }

  function selectAllGameDeletes() {
    setSelectedGameDeleteIds(games.map((game) => game.game_id));
  }

  function selectAllCharacterDeletes() {
    setSelectedCharacterDeleteIds(characters.map((character) => character.character_id));
  }

  function clearGameDeleteSelection() {
    setSelectedGameDeleteIds([]);
  }

  function clearCharacterDeleteSelection() {
    setSelectedCharacterDeleteIds([]);
  }

  async function confirmDeleteRequest() {
    if (!deleteRequest || deleteRequest.busy) return;
    if (deleteRequest.step < 2) {
      setDeleteRequest((current) => current ? { ...current, step: current.step + 1 } : current);
      return;
    }

    const current = deleteRequest;
    const targetIds = current.ids || [];
    try {
      setError("");
      setDeleteRequest({ ...current, busy: true });
      if (current.kind === "game") {
        if (targetIds.length === 1) {
          await deleteGame(targetIds[0]);
        } else {
          await deleteGames(targetIds);
        }
        setSelectedGameDeleteIds((prev) => prev.filter((item) => !targetIds.includes(item)));
        setGameDeleteMode(false);
        if (targetIds.includes(activeGameIdRef.current)) leaveGame();
      } else {
        if (targetIds.length === 1) {
          await deleteCharacter(targetIds[0]);
        } else {
          await deleteCharacters(targetIds);
        }
        setSelectedCharacterDeleteIds((prev) => prev.filter((item) => !targetIds.includes(item)));
        setCharacterDeleteMode(false);
        setSelectedGameChars((prev) => prev.filter((item) => !targetIds.includes(item)));
        if (targetIds.includes(selectedCharacter?.character_id)) {
          setSelectedCharacter(null);
        }
      }
      setDeleteRequest(null);
      await refreshLobby();
    } catch (err) {
      setDeleteRequest((latest) => latest ? { ...latest, busy: false } : latest);
      const message = err.message || "删除失败。";
      setError(message.includes("Method Not Allowed") || message.includes("405")
        ? "当前后端进程尚未加载删除接口。请重新运行 start.cmd 后再试。"
        : message);
    }
  }

  function cancelDeleteRequest() {
    if (!deleteRequest?.busy) setDeleteRequest(null);
  }

  function renderBuilderLoadState(title) {
    if (isBuilderLoading) {
      return <p className="info-text">角色构筑规则加载中...</p>;
    }

    return (
      <div className="timeline-item">
        <div className="timeline-summary">{title}暂未载入</div>
        <div className="timeline-content">请点击下方按钮重新加载角色构筑规则。</div>
        <div className="btn-row" style={{ marginTop: 12 }}>
          <button className="btn-secondary" onClick={() => loadBuilderCatalog()}>重新加载规则目录</button>
        </div>
      </div>
    );
  }

  function replyLengthDraftFromState(state) {
    const campaign = state?.campaign || {};
    return {
      min_chars: campaign.reply_min_chars ? String(campaign.reply_min_chars) : "",
      max_chars: campaign.reply_max_chars ? String(campaign.reply_max_chars) : "",
    };
  }

  function applyGameSnapshot(state, options, { preserveRewrite = false } = {}) {
    latestTurnNumberRef.current = Number(state?.turn_number || 0);
    setGameState(state);
    setMessages(mapMessages(state.chat_history || [], state.timeline || []));
    if (options) setActionOptions(options);
    setReplyLengthDraft(replyLengthDraftFromState(state));
    if (!preserveRewrite) setRewriteTarget(null);
  }

  function normalizeActionSuggestions(items) {
    return (items || [])
      .filter((item) => item?.label && item?.action)
      .slice(0, 3);
  }

  function storedActionSuggestionProjection(state) {
    const latestAssistantMessage = [...(state?.chat_history || [])]
      .reverse()
      .find((message) => message?.kind !== "tool_result" && message?.role === "assistant");
    return {
      suggestions: normalizeActionSuggestions(latestAssistantMessage?.action_suggestions),
      generated: Boolean(latestAssistantMessage?.action_suggestions_generated),
    };
  }

  function invalidateActionSuggestionProjection() {
    actionSuggestionRequestRef.current += 1;
    setIsActionSuggestionsLoading(false);
  }

  function beginGameLifecycle(gameId) {
    const lifecycleToken = gameLifecycleRef.current + 1;
    gameLifecycleRef.current = lifecycleToken;
    gameSyncRequestRef.current += 1;
    activeGameIdRef.current = gameId;
    setActiveGameId(gameId);
    setRetryingMessageIndex(null);
    return lifecycleToken;
  }

  function isCurrentGameLifecycle(gameId, lifecycleToken) {
    return activeGameIdRef.current === gameId && gameLifecycleRef.current === lifecycleToken;
  }

  function leaveGame() {
    gameLifecycleRef.current += 1;
    gameSyncRequestRef.current += 1;
    activeGameIdRef.current = null;
    latestTurnNumberRef.current = 0;
    invalidateActionSuggestionProjection();
    setActiveGameId(null);
    setGameState(null);
    setActionOptions({ actors: [] });
    setActionDraft({ ...EMPTY_ACTIONS });
    setActionSuggestions([]);
    setMessages([]);
    setWorkflowEvents([]);
    setDmThinking(createEmptyDmThinking());
    setRewriteTarget(null);
    setRetryingMessageIndex(null);
    setInput("");
    setReplyLengthDraft({ min_chars: "", max_chars: "" });
    setReplyLengthMessage("");
    setIsReplyLengthSaving(false);
    setIsLoading(false);
    setPendingAdventureId(null);
    setError("");
    setView("home");
  }

  function requestActionSuggestionProjection(gameId, turnNumber, lifecycleToken = gameLifecycleRef.current) {
    if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
    const requestId = actionSuggestionRequestRef.current + 1;
    actionSuggestionRequestRef.current = requestId;
    setIsActionSuggestionsLoading(true);
    void loadActionSuggestions(gameId)
      .then((payload) => {
        if (
          actionSuggestionRequestRef.current === requestId
          && isCurrentGameLifecycle(gameId, lifecycleToken)
          && latestTurnNumberRef.current === Number(turnNumber || 0)
          && Number(payload.turn_number || 0) === Number(turnNumber || 0)
        ) {
          setActionSuggestions(normalizeActionSuggestions(payload.action_suggestions));
        }
      })
      .catch(() => {})
      .finally(() => {
        if (actionSuggestionRequestRef.current === requestId && isCurrentGameLifecycle(gameId, lifecycleToken)) {
          setIsActionSuggestionsLoading(false);
        }
      });
  }

  async function syncGame(gameId, state, options = {}) {
    const lifecycleToken = options.lifecycleToken ?? gameLifecycleRef.current;
    if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return { suggestions: [], generated: false };

    const storedProjection = storedActionSuggestionProjection(state);
    const hasExplicitSuggestions = Object.prototype.hasOwnProperty.call(options, "actionSuggestions");
    const normalizedSuggestions = normalizeActionSuggestions(
      hasExplicitSuggestions ? options.actionSuggestions : storedProjection.suggestions,
    );
    const suggestionsGenerated = hasExplicitSuggestions
      ? normalizedSuggestions.length === 3
        || Boolean(options.actionSuggestionsGenerated)
        || storedProjection.generated
      : storedProjection.generated;
    const syncRequestId = gameSyncRequestRef.current + 1;
    gameSyncRequestRef.current = syncRequestId;
    applyGameSnapshot(state, options.actionOptions, { preserveRewrite: options.preserveRewrite });
    setActionSuggestions(normalizedSuggestions);
    const expectedTurnNumber = Number(state?.turn_number || 0);
    void loadActionOptions(gameId)
      .then((nextActionOptions) => {
        if (
          isCurrentGameLifecycle(gameId, lifecycleToken)
          && gameSyncRequestRef.current === syncRequestId
          && latestTurnNumberRef.current === expectedTurnNumber
        ) {
          setActionOptions(nextActionOptions || { actors: [] });
        }
      })
      .catch(() => {
        // The authoritative game snapshot remains usable when this optional projection fails.
      });
    return { suggestions: normalizedSuggestions, generated: suggestionsGenerated };
  }

  async function saveReplyLengthSettings() {
    if (localActionsLocked) { setReplyLengthMessage(localActionBlockMessage); return; }
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (!gameId || isReplyLengthSaving || isLoading || !isCurrentGameLifecycle(gameId, lifecycleToken)) return;
    const minChars = normalizeReplyLengthValue(replyLengthDraft.min_chars);
    const maxChars = normalizeReplyLengthValue(replyLengthDraft.max_chars);
    if (minChars && maxChars && minChars > maxChars) {
      setReplyLengthMessage("最小字数不能大于最大字数。");
      return;
    }

    setIsReplyLengthSaving(true);
    setReplyLengthMessage("");
    try {
      const result = await updateReplyLength(gameId, { min_chars: minChars, max_chars: maxChars });
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      await syncGame(gameId, result.game_state, { actionSuggestions, preserveRewrite: true, lifecycleToken });
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setReplyLengthMessage("已应用。");
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setReplyLengthMessage(err.message || "保存失败。");
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setIsReplyLengthSaving(false);
    }
  }

  function normalizeReplyLengthValue(value) {
    const trimmed = String(value || "").trim();
    if (!trimmed) return 0;
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
  }

  function replyLengthSummary() {
    const minChars = normalizeReplyLengthValue(replyLengthDraft.min_chars);
    const maxChars = normalizeReplyLengthValue(replyLengthDraft.max_chars);
    if (!minChars && !maxChars) return "不限制";
    if (minChars && maxChars) return `${minChars}-${maxChars} 字`;
    if (minChars) return `至少 ${minChars} 字`;
    return `至多 ${maxChars} 字`;
  }

  function fillActionSuggestion(suggestion) {
    const action = String(suggestion?.action || "").trim();
    if (!action) return;
    setRewriteTarget(null);
    setInput(action);
    window.requestAnimationFrame(() => chatInputRef.current?.focus());
  }

  function buildAttackDraft(attackerRef, attackName, currentAttack) {
    if (!attackerRef) {
      return { ...EMPTY_ACTIONS.attack, target_ref: currentAttack.target_ref };
    }

    const actor = (actionOptions.actors || []).find((entry) => entry.ref === attackerRef);
    const attacks = actor?.attacks || [];
    const selectedAttack = attacks.find((entry) => entry.name === attackName) || attacks[0];

    return {
      ...currentAttack,
      attacker_ref: attackerRef,
      attack_name: selectedAttack?.name || "",
      attack_bonus: selectedAttack?.attack_bonus ?? 0,
      damage_expression: selectedAttack?.damage_expression || EMPTY_ACTIONS.attack.damage_expression,
      damage_type: selectedAttack?.damage_type || "",
    };
  }

  function formatAttackOption(attack) {
    const attackBonus = attack.attack_bonus >= 0 ? `+${attack.attack_bonus}` : `${attack.attack_bonus}`;
    const details = [attackBonus, attack.damage_expression];
    if (attack.damage_type_display || attack.damage_type) details.push(attack.damage_type_display || attack.damage_type);
    return `${localizeName(attack)}（${details.join(" / ")}）`;
  }

  function handleAttackActorChange(attackerRef) {
    setActionDraft((prev) => ({ ...prev, attack: buildAttackDraft(attackerRef, "", prev.attack) }));
  }

  function handleCurrentActorAttackLoad() {
    if (!currentActorEntry?.ref) return;
    setActionDraft((prev) => ({
      ...prev,
      attack: buildAttackDraft(currentActorEntry.ref, "", prev.attack),
      skill: { ...prev.skill, actor_ref: currentActorEntry.ref, skill_name: "" },
      spell: currentActorEntry.type === "character" ? buildSpellDraft(currentActorEntry.ref, "", prev.spell) : prev.spell,
      item: currentActorEntry.type === "character" ? { ...prev.item, user_ref: currentActorEntry.ref, item_name: "" } : prev.item,
    }));
  }

  function handleAttackOptionChange(attackName) {
    setActionDraft((prev) => ({ ...prev, attack: buildAttackDraft(prev.attack.attacker_ref, attackName, prev.attack) }));
  }

  function buildSpellDraft(casterRef, spellName, currentSpell) {
    const actor = charActors.find((entry) => entry.ref === casterRef);
    const options = actor?.spells?.options || [];
    const selectedSpell = options.find((entry) => entry.name === spellName) || options[0];

    return {
      ...currentSpell,
      caster_ref: casterRef,
      spell_name: selectedSpell?.name || "",
      target_ref: "",
      damage_type: selectedSpell?.damage_types?.length === 1 ? selectedSpell.damage_types[0] : "",
      slot_level: selectedSpell ? (selectedSpell.requires_slot ? (selectedSpell.available_slot_levels[0] ?? 0) : 0) : 0,
    };
  }

  function handleSpellCasterChange(casterRef) {
    setActionDraft((prev) => ({ ...prev, spell: buildSpellDraft(casterRef, "", prev.spell) }));
  }

  function handleSpellOptionChange(spellName) {
    setActionDraft((prev) => ({ ...prev, spell: buildSpellDraft(prev.spell.caster_ref, spellName, prev.spell) }));
  }

  function handleItemUserChange(userRef) {
    setActionDraft((prev) => ({ ...prev, item: { ...prev.item, user_ref: userRef, item_name: "" } }));
  }

  // Pull the latest attack metadata from action-options after every game refresh.
  useEffect(() => {
    if (!actionDraft.attack.attacker_ref) return;

    const nextAttack = buildAttackDraft(
      actionDraft.attack.attacker_ref,
      actionDraft.attack.attack_name,
      actionDraft.attack,
    );

    if (
      nextAttack.attack_name === actionDraft.attack.attack_name
      && nextAttack.attack_bonus === actionDraft.attack.attack_bonus
      && nextAttack.damage_expression === actionDraft.attack.damage_expression
      && nextAttack.damage_type === actionDraft.attack.damage_type
    ) {
      return;
    }

    setActionDraft((prev) => ({ ...prev, attack: nextAttack }));
  }, [actionOptions]);

  async function enterGame(gameId) {
    invalidateActionSuggestionProjection();
    const lifecycleToken = beginGameLifecycle(gameId);
    setIsLoading(true);
    setError("");
    setGameState(null);
    setMessages([]);
    setWorkflowEvents([]);
    setDmThinking(createEmptyDmThinking());
    setActionOptions({ actors: [] });
    setActionSuggestions([]);
    setRewriteTarget(null);
    setInput("");
    setReplyLengthMessage("");
    setView("chat");
    try {
      const state = await loadGame(gameId);
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, state, { lifecycleToken });
      if (
        isCurrentGameLifecycle(gameId, lifecycleToken)
        && state?.campaign?.phase !== "adventure_selection"
        && !suggestionProjection.generated
      ) {
        requestActionSuggestionProjection(gameId, state.turn_number, lifecycleToken);
      }
    } catch (err) {
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      leaveGame();
      setError(err.message || "读取游戏存档失败。");
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setIsLoading(false);
    }
  }
  function adjustStat(stat, delta) {
    const currentValue = Number(charDraft.stats?.[stat] || 0);
    const nextValue = currentValue + delta;
    const minimum = Number(pointBuyRules.minimum || 8);
    const maximum = Number(pointBuyRules.maximum || 15);
    if (nextValue < minimum || nextValue > maximum) return;

    const currentCost = POINT_BUY_COSTS[currentValue];
    const nextCost = POINT_BUY_COSTS[nextValue];
    if (Number.isFinite(currentCost) && Number.isFinite(nextCost) && delta > 0 && (nextCost - currentCost) > pointBuyRemaining) return;

    setError("");
    setCharDraft((prev) => ({ ...prev, stats: { ...prev.stats, [stat]: nextValue } }));
  }

  function applyAbilityPool(method, pool, rolls = []) {
    const normalizedPool = [...(pool || [])].sort((left, right) => Number(right.score) - Number(left.score));
    const preferredOrder = CLASS_RECOMMENDED_STAT_ORDER[charDraft.class_name] || STATS;
    const assignments = {};
    const stats = {};
    preferredOrder.forEach((stat, index) => {
      const slot = normalizedPool[index];
      if (!slot) return;
      assignments[stat] = slot.slot_id;
      stats[stat] = Number(slot.score);
    });
    setCharDraft((prev) => ({
      ...prev,
      ability_generation_method: method,
      ability_rolls: method === "rolled" ? rolls : [],
      ability_pool: normalizedPool,
      ability_assignments: assignments,
      stats: { ...prev.stats, ...stats },
    }));
  }

  async function setAbilityGenerationMethod(method) {
    setError("");
    if (method === "point_buy") {
      setCharDraft((prev) => ({
        ...prev,
        ability_generation_method: "point_buy",
        ability_rolls: [],
        ability_pool: [],
        ability_assignments: {},
        stats: recommendedStatsForClass(prev.class_name),
      }));
      return;
    }

    try {
      setIsAbilityGenerating(true);
      const result = await generateAbilityScores({ method });
      applyAbilityPool(method, result.pool || [], result.rolls || []);
    } catch (err) {
      setError(err.message || "无法生成属性值，请稍后重试。");
    } finally {
      setIsAbilityGenerating(false);
    }
  }

  function assignAbilitySlot(stat, slotId) {
    setError("");
    setCharDraft((prev) => {
      const assignments = { ...(prev.ability_assignments || {}) };
      const previousSlotId = assignments[stat];
      const previousOwner = STATS.find((candidate) => candidate !== stat && assignments[candidate] === slotId);
      assignments[stat] = slotId;
      if (previousOwner && previousSlotId) assignments[previousOwner] = previousSlotId;
      const poolById = Object.fromEntries((prev.ability_pool || []).map((slot) => [slot.slot_id, slot]));
      const stats = Object.fromEntries(STATS.map((name) => [name, Number(poolById[assignments[name]]?.score || 0)]));
      return { ...prev, ability_assignments: assignments, stats };
    });
  }

  function setEquipmentMode(mode) {
    setError("");
    setCharDraft((prev) => ({
      ...prev,
      equipment_mode: mode,
      custom_purchase_items: mode === "custom_purchase" ? prev.custom_purchase_items : {},
    }));
  }

  function setCustomPurchaseQuantity(itemId, quantity) {
    const nextQuantity = Math.max(0, Number(quantity || 0));
    setError("");
    setCharDraft((prev) => {
      const nextItems = { ...(prev.custom_purchase_items || {}) };
      if (nextQuantity <= 0) delete nextItems[itemId];
      else nextItems[itemId] = nextQuantity;
      return { ...prev, custom_purchase_items: nextItems };
    });
  }

  function updatePendingCustomItem(field, value) {
    setError("");
    setCharDraft((prev) => ({
      ...prev,
      custom_pending_item: {
        ...(prev.custom_pending_item || EMPTY_PENDING_ITEM),
        [field]: value,
      },
    }));
  }
  async function chooseClass(c) {
    setError("");
    const baseSkills = Object.fromEntries((background?.skill_proficiencies || []).map((skill) => [skill, 1]));
    setCharDraft((p) => ({
      ...p,
      class_name: c.name,
      starter_option_id: c.starter_equipment_options?.[0]?.id || "",
      starter_choice_ids: {},
      equipment_mode: "starter_package",
      custom_purchase_items: {},
      custom_pending_item: { ...EMPTY_PENDING_ITEM },
      stats: recommendedStatsForClass(c.name),
      ability_generation_method: "point_buy",
      ability_rolls: [],
      ability_pool: [],
      ability_assignments: {},
      skill_proficiencies: baseSkills,
      selectedCantrips: [],
      selectedSpells: [],
    }));
    const hasBuilderSpellOptions = Boolean(c.spellcasting_ability) && (
      Number(c.starting_cantrips || 0) > 0
      || Object.values(c.starting_spell_slots || {}).some((total) => Number(total) > 0)
    );
    if (!hasBuilderSpellOptions) {
      setSpellList([]);
      return;
    }
    try { setSpellList(await loadSpells(c.name)); } catch { setSpellList([]); }
  }
  function chooseBackground(name) {
    const bg = builder.backgrounds.find((x) => x.name === name);
    const nextSkills = Object.fromEntries(
      (classDef?.skill_choices || [])
        .filter((skill) => Number(charDraft.skill_proficiencies?.[skill] || 0) > 0)
        .map((skill) => [skill, 1]),
    );
    for (const skill of bg?.skill_proficiencies || []) nextSkills[skill] = 1;
    setError("");
    setCharDraft((p) => ({ ...p, background_name: name, origin_feat: bg?.origin_feat || "", skill_proficiencies: nextSkills }));
  }
  function toggleSkill(skill) {
    if (backgroundSkills.has(skill)) return;
    const selected = Number(charDraft.skill_proficiencies?.[skill] || 0) > 0;
    const picked = Object.entries(charDraft.skill_proficiencies || {}).filter(([name, rank]) => !backgroundSkills.has(name) && Number(rank) > 0 && name !== skill);
    if (!selected && picked.length >= classSkillTarget) return setError(`该职业最多只能额外选择 ${classSkillTarget} 项技能。`);
    setError("");
    setCharDraft((p) => ({ ...p, skill_proficiencies: { ...p.skill_proficiencies, [skill]: selected ? 0 : 1 } }));
  }
  function chooseStarterOption(optionId) { setError(""); setCharDraft((p) => ({ ...p, starter_option_id: optionId, starter_choice_ids: {} })); }
  function chooseStarterChoice(groupId, optionId) { setError(""); setCharDraft((p) => ({ ...p, starter_choice_ids: { ...p.starter_choice_ids, [groupId]: optionId } })); }
  function togglePreparedSpell(spellName) {
    if (!hasLevelOneSpellcasting) {
      setError("当前职业在 1 级时没有可准备的法术位。");
      return;
    }

    const selected = charDraft.selectedSpells.includes(spellName);
    if (!selected && startingPreparedSpellCount > 0 && charDraft.selectedSpells.length >= startingPreparedSpellCount) {
      setError(`${classDef?.name_display || localizeClassName(classDef?.name)} 需要准确选择 ${startingPreparedSpellCount} 个 1 环及以上法术。`);
      return;
    }

    setError("");
    setCharDraft((p) => ({
      ...p,
      selectedSpells: selected ? p.selectedSpells.filter((x) => x !== spellName) : [...p.selectedSpells, spellName],
    }));
  }

  function toggleCantrip(spellName) {
    if (!hasCantripSelection) {
      setError("当前职业在此构筑中不获得戏法。");
      return;
    }

    const selected = charDraft.selectedCantrips.includes(spellName);
    if (!selected && charDraft.selectedCantrips.length >= startingCantripCount) {
      setError(`${classDef?.name_display || localizeClassName(classDef?.name)} 需要准确选择 ${startingCantripCount} 个戏法。`);
      return;
    }

    setError("");
    setCharDraft((p) => ({
      ...p,
      selectedCantrips: selected ? p.selectedCantrips.filter((x) => x !== spellName) : [...p.selectedCantrips, spellName],
    }));
  }

  function validateCreatorStep(stepIndex) {
    if (!builderReady) return "角色构筑规则尚未加载完成。";

    if (stepIndex === 0) {
      if (!charDraft.name.trim()) return "请先填写角色名称。";
      if (!charDraft.species) return "请先选择种族。";
      if (!charDraft.background_name) return "请先选择背景。";
    }

    if (stepIndex === 1) {
      if (!charDraft.class_name) return "请先选择职业。";
      if (abilityGenerationMethod === "point_buy" && pointBuyRemaining < 0) return "属性购点超出预算，请调低属性。";
      if (!abilityAssignmentComplete) return "请先为六项属性分配完整的属性值。";
      if (selectedClassSkillCount !== classSkillTarget) return `请准确选择 ${classSkillTarget} 项职业技能。`;
    }

    if (stepIndex === 2) {
      if (!classDef) return "请先完成职业选择。";
      if (charDraft.equipment_mode === "starter_package") {
        if (starterOptions.length > 0 && !selectedStarterOption) return "请选择一个起始装备方案。";
        if (!starterChoicesComplete) return "起始装备的子选项还没有选完。";
      }
      if (charDraft.equipment_mode === "custom_purchase" && customPurchaseBudgetGp <= 0) return "当前职业没有可用的自定义购买预算。";
      if (!hasPendingCustomItem && pendingCustomTouched) return "自定义待定装备需要先填写名称。";
      if (hasPendingCustomItem && Number(charDraft.custom_pending_item?.quantity || 0) <= 0) return "自定义待定装备的数量必须大于 0。";
      if (equipmentRemainingGp < 0) return `装备花费超出预算 ${Math.abs(equipmentRemainingGp)} 金币，请减少购买或降低预留预算。`;
    }

    if (stepIndex === 3) {
      if (hasCantripSelection && cantripOptions.length === 0) return "戏法目录还没加载出来，请重新选择职业后再试。";
      if (hasLevelOneSpellcasting && startingPreparedSpellCount > 0 && levelOnePreparedSpells.length === 0) return "已准备法术目录还没加载出来，请重新选择职业后再试。";
      if (!cantripSelectionComplete) return `请准确选择 ${startingCantripCount} 个戏法。`;
      if (!spellSelectionComplete) return `请准确选择 ${startingPreparedSpellCount} 个已准备法术。`;
    }

    return "";
  }

  function goToCreatorStep(nextStep) {
    const clampedStep = Math.max(0, Math.min(CREATOR_STEPS.length - 1, nextStep));
    if (clampedStep > creatorStep) {
      const stepError = validateCreatorStep(creatorStep);
      if (stepError) {
        setError(stepError);
        return;
      }
    }
    setError("");
    setCreatorStep(clampedStep);
  }

  async function saveChar() {
    try {
      for (let stepIndex = 0; stepIndex < CREATOR_STEPS.length - 1; stepIndex += 1) {
        const stepError = validateCreatorStep(stepIndex);
        if (stepError) {
          setError(stepError);
          setCreatorStep(stepIndex);
          return;
        }
      }
      setError("");
      await saveCharacter({
        name: charDraft.name.trim(),
        species: charDraft.species,
        background_name: charDraft.background_name,
        origin_feat: charDraft.origin_feat,
        class_name: charDraft.class_name,
        starter_option_id: charDraft.starter_option_id,
        starter_choice_ids: charDraft.starter_choice_ids,
        equipment_mode: charDraft.equipment_mode,
        custom_purchase_items: charDraft.custom_purchase_items,
        custom_pending_item: charDraft.custom_pending_item,
        hp_current: computedHpMax,
        hp_max: computedHpMax,
        stats: charDraft.stats,
        ability_generation_method: abilityGenerationMethod,
        ability_rolls: charDraft.ability_rolls,
        skill_proficiencies: charDraft.skill_proficiencies,
        spells: { cantrips: charDraft.selectedCantrips, prepared: charDraft.selectedSpells },
        inventory: [],
      });
      setCharDraft(freshCharacterDraft());
      setCreatorStep(0);
      setSpellList([]);
      setView("home");
      await refreshLobby();
    } catch (err) { setError(err.message || "保存角色失败。"); }
  }

  async function saveMonster() {
    try {
      setError("");
      await saveMonsterTemplate({ monster_id: monsterDraft.monster_id || undefined, name: monsterDraft.name, size: monsterDraft.size, creature_type: monsterDraft.creature_type, alignment: monsterDraft.alignment, challenge_rating: monsterDraft.challenge_rating, ac: monsterDraft.ac, hp_max: monsterDraft.hp_max, initiative_bonus: monsterDraft.initiative_bonus, speed: monsterDraft.speed, notes: monsterDraft.notes, traits: parseEntries(monsterDraft.traitsText, "特性"), actions: parseEntries(monsterDraft.actionsText, "动作"), reactions: parseEntries(monsterDraft.reactionsText, "反应"), bonus_actions: parseEntries(monsterDraft.bonusActionsText, "附赠动作") });
      setMonsterDraft({ ...EMPTY_MON }); await refreshLobby();
    } catch (err) { setError(err.message || "保存怪物模板失败。"); }
  }

  async function openMonster(monsterId) {
    try {
      const m = await loadMonsterTemplate(monsterId);
      setMonsterDraft({ monster_id: m.monster_id, name: m.name, size: m.size || "中型", creature_type: m.creature_type || "野兽", alignment: m.alignment || "无阵营", challenge_rating: m.challenge_rating || "1", ac: m.ac ?? 10, hp_max: m.hp_max ?? 10, initiative_bonus: m.initiative_bonus ?? 0, speed: m.speed ?? 30, notes: m.notes || "", traitsText: entriesToText(m.traits), actionsText: entriesToText(m.actions), reactionsText: entriesToText(m.reactions), bonusActionsText: entriesToText(m.bonus_actions) });
      setView("monsters");
    } catch (err) { setError(err.message || "读取怪物模板失败。"); }
  }

  async function makeGame() {
    const gameId = newGameId.trim();
    if (!gameId) return setError("请输入游戏存档 ID。");
    if (selectedGameChars.length === 0) return setError("请至少选择一名队伍角色。");
    try {
      setError("");
      const result = await createGame({ game_id: gameId, title: gameId, character_ids: selectedGameChars });
      invalidateActionSuggestionProjection();
      const lifecycleToken = beginGameLifecycle(gameId);
      setWorkflowEvents([]);
      setActionSuggestions([]);
      setRewriteTarget(null);
      setReplyLengthMessage("");
      setView("chat");
      applyGameSnapshot(result.game_state, result.action_options);
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setInput("");
      await refreshLobby().catch(() => {});
    } catch (err) { setError(err.message || "创建游戏失败。"); }
  }
  async function chooseAdventure(adventureId) {
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (!gameId || isGameMutationBusy || localActionsLocked || !isCurrentGameLifecycle(gameId, lifecycleToken)) return;
    setIsLoading(true);
    setPendingAdventureId(adventureId);
    setError("");
    invalidateActionSuggestionProjection();
    setActionSuggestions([]);
    try {
      const result = await selectAdventure(gameId, adventureId);
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, result.game_state, { actionSuggestions: result.action_suggestions, lifecycleToken });
      if (isCurrentGameLifecycle(gameId, lifecycleToken) && !suggestionProjection.generated) {
        requestActionSuggestionProjection(gameId, result.game_state?.turn_number, lifecycleToken);
      }
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setError(err.message || "选择冒险失败。");
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        setPendingAdventureId(null);
        setIsLoading(false);
      }
    }
  }
  function createTurnStreamHandlers(gameId, lifecycleToken) {
    const pushWorkflowEvent = (event) => {
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      setWorkflowEvents((prev) => [...prev.slice(-29), event]);
      setDmThinking((current) => {
        const previous = current.events[current.events.length - 1];
        if (
          previous?.node_name === event?.node_name
          && previous?.status === event?.status
          && previous?.summary === event?.summary
        ) return current;
        return { ...current, events: [...current.events.slice(-11), event] };
      });
    };
    return {
      onEvent: (eventName, data) => {
        if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
        if (eventName === "turn.started") {
          setDmThinking((current) => ({ ...current, startedAt: Date.now(), rollRecords: mergeRollRecords(current.rollRecords, data?.roll_records || []) }));
          setMessages((current) => current.map((message) => message.optimistic && message.deliveryState === "sending"
            ? { ...message, deliveryState: "processing", deliveryLabel: "主持处理中…" } : message));
          pushWorkflowEvent({
            node_name: "turn_started",
            status: "started",
            summary: data?.mode === "resume" ? "恢复暂停回合" : "启动新回合",
            metadata: { mode: data?.mode, checkpoint_backend: data?.checkpoint_backend },
          });
        }
        if (eventName === "turn.error") {
          setDmThinking((current) => ({ ...current, status: "error", expanded: false }));
        }
        if (eventName === "turn.finished") {
          setDmThinking((current) => ({
            ...current,
            status: ["error", "failed"].includes(data?.status) ? "error" : data?.status === "input_required" ? "waiting" : "completed",
            expanded: false,
          }));
        }
      },
      onAgentOutput: (data, phase) => {
        if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
        setDmThinking((current) => {
          if (phase === "started") {
            const needsSeparator = current.segmentCount > 0
              && current.output
              && !current.output.endsWith("\n\n");
            return {
              ...current,
              output: needsSeparator ? `${current.output}\n\n` : current.output,
              segmentCount: current.segmentCount + 1,
              waitingForModel: true,
            };
          }
          if (phase === "delta" && data?.text) {
            return { ...current, output: `${current.output}${data.text}` };
          }
          if (phase === "completed") return { ...current, waitingForModel: false };
          return current;
        });
      },
      onRoll: (records) => {
        if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
        setDmThinking((current) => ({ ...current, rollRecords: mergeRollRecords(current.rollRecords, records) }));
      },
      onResult: (data) => {
        if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
        setDmThinking((current) => ({ ...current, waitingForModel: false,
          status: data?.turn_status === "input_required" ? "waiting" : data?.turn_status === "failed" ? "error" : "completed",
          expanded: false, rollRecords: data?.roll_records || [] }));
      },
      onNode: (node) => {
        pushWorkflowEvent(node);
      },
      onRag: (data) => {
        const snippetCount = Number(data?.snippet_count || 0);
        pushWorkflowEvent({
          node_name: "rag_completed",
          status: "completed",
          summary: snippetCount > 0 ? `检索到 ${snippetCount} 条规则片段。` : data?.reason || "未触发规则检索。",
          metadata: {
            intent: data?.intent,
            query_count: data?.query_count,
            snippet_count: data?.snippet_count,
            source_count: data?.source_count,
          },
        });
      },
      onTool: (data) => {
        const rawStatus = data?.status || "completed";
        const status = rawStatus === "success" ? "success" : rawStatus === "failed" ? "error" : rawStatus;
        pushWorkflowEvent({
          node_name: "tool_completed",
          status,
          summary: data?.summary || `${data?.tool_name || "tool"} completed.`,
          metadata: { tool_name: data?.tool_name },
        });
      },
      onValidation: (data) => {
        pushWorkflowEvent({
          node_name: "validation_note",
          status: "noted",
          summary: data?.note || "状态校验记录。",
          metadata: {
            note_index: data?.index,
            validator: data?.validator,
            severity: data?.severity,
            action: data?.action,
          },
        });
      },
    };
  }

  async function submitChatMessage(rawMessage, options = {}) {
    const message = String(rawMessage || "").trim();
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (!message || !gameId || isGameMutationBusy || !isCurrentGameLifecycle(gameId, lifecycleToken)) return;
    if (gameState?.campaign?.phase === "adventure_selection") return setError("请先选择冒险。");

    const optimisticMessageId = `${gameId}-${++optimisticMessageIdRef.current}`;
    // 玩家需要在网络回合开始前确认自己的发言已经进入对话；权威快照返回后会替换这条临时消息。
    setMessages((current) => {
      const settledMessages = current.filter((item) => !item.optimistic);
      return [
        ...settledMessages,
        {
          index: settledMessages.length,
          chatIndex: null,
          role: "user",
          sender: "player",
          text: message,
          optimistic: true,
          optimisticMessageId,
          renderKey: `pending-player-${gameId}-${message}`,
          deliveryState: "sending",
        },
      ];
    });
    setIsLoading(true);
    setError("");
    setWorkflowEvents([]);
    setDmThinking({
      ...createEmptyDmThinking(),
      status: "running",
      expanded: true,
      rollRecords: gameState?.pending_turn?.roll_records || [],
    });
    invalidateActionSuggestionProjection();
    setActionSuggestions([]);
    if (options.clearInput) setInput("");
    try {
      const result = await streamTurn(gameId, message, createTurnStreamHandlers(gameId, lifecycleToken));
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, result.game_state, { actionSuggestions: result.action_suggestions, lifecycleToken });
      if (
        isCurrentGameLifecycle(gameId, lifecycleToken)
        && result.turn_status === "completed"
        && !suggestionProjection.generated
      ) {
        requestActionSuggestionProjection(gameId, result.game_state?.turn_number, lifecycleToken);
      }
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        setDmThinking((current) => ({ ...current, status: "error", expanded: false,
          rollRecords: current.rollRecords.map((record) => ({ ...record, settlement: "unknown" })) }));
        setError(err.message || "发送消息失败。");
        setMessages((current) => current.map((item) => item.optimisticMessageId === optimisticMessageId
          ? { ...item, deliveryState: "failed" }
          : item));
        setInput((current) => current.trim() ? current : message);
      }
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        setDmThinking((current) => current.status === "running"
          ? { ...current, status: "completed", expanded: false }
          : current);
        setIsLoading(false);
      }
    }
  }

  async function retryDmMessage(message) {
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (
      message?.sender !== "dm"
      || !Number.isInteger(message.index)
      || !gameId
      || rewriteTarget
      || isGameMutationBusy
      || !isCurrentGameLifecycle(gameId, lifecycleToken)
    ) return;

    const hasLaterMessages = messages.some((item) => (
      !item.optimistic && Number.isInteger(item.index) && item.index > message.index
    ));
    if (
      hasLaterMessages
      && !window.confirm("重试会回到这条主持回复之前，并移除之后的剧情、状态变化和时间线记录。继续？")
    ) return;

    const retryUiRollback = prepareDmRetryUiRollback({
      messages,
      actionSuggestions,
      workflowEvents,
      dmThinking,
      actionSuggestionsLoading: isActionSuggestionsLoading,
    }, message.index);
    const retryUiSnapshot = retryUiRollback.snapshot;
    setRetryingMessageIndex(message.index);
    setIsLoading(true);
    setError("");
    // 重试在服务端会回到该主持回复之前；前端同步先移除同一回复及其后续展示，避免旧内容和新请求并存。
    setMessages(retryUiRollback.next.messages);
    setWorkflowEvents(retryUiRollback.next.workflowEvents);
    setDmThinking({ ...retryUiRollback.next.dmThinking, status: "running", expanded: true });
    invalidateActionSuggestionProjection();
    setActionSuggestions(retryUiRollback.next.actionSuggestions);
    try {
      const result = await retryGameMessage(gameId, message.index, createTurnStreamHandlers(gameId, lifecycleToken));
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, result.game_state, {
        actionSuggestions: result.action_suggestions,
        lifecycleToken,
      });
      if (
        isCurrentGameLifecycle(gameId, lifecycleToken)
        && result.turn_status === "completed"
        && !suggestionProjection.generated
      ) {
        requestActionSuggestionProjection(gameId, result.game_state?.turn_number, lifecycleToken);
      }
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        // HTTP/网络层失败表示服务端没有返回新的权威快照；恢复被乐观移除的整组回复投影。
        setMessages(retryUiSnapshot.messages);
        setActionSuggestions(retryUiSnapshot.actionSuggestions);
        setWorkflowEvents(retryUiSnapshot.workflowEvents);
        setDmThinking((current) => ({ ...current, status: "error", expanded: false, rollRecords: current.rollRecords.map((record) => ({ ...record, settlement: "unknown" })) }));
        if (retryUiSnapshot.actionSuggestionsLoading) {
          requestActionSuggestionProjection(gameId, gameState?.turn_number, lifecycleToken);
        }
        setError(err.message || "重试本回合失败。请稍后再试。");
      }
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        setIsLoading(false);
        setRetryingMessageIndex(null);
      }
    }
  }

  async function deleteMessageFromHere(message) {
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (!gameId || isGameMutationBusy || !isCurrentGameLifecycle(gameId, lifecycleToken)) return;
    const confirmed = window.confirm("删除会回到这条消息出现之前，并移除后续剧情、状态变化和时间线记录。继续？");
    if (!confirmed) return;

    setIsLoading(true);
    setError("");
    setWorkflowEvents([]);
    invalidateActionSuggestionProjection();
    try {
      const result = await deleteGameMessage(gameId, message.index);
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, result.game_state, { actionSuggestions: result.action_suggestions, lifecycleToken });
      if (
        isCurrentGameLifecycle(gameId, lifecycleToken)
        && !suggestionProjection.generated
        && result.game_state?.campaign?.phase !== "adventure_selection"
      ) {
        requestActionSuggestionProjection(gameId, result.game_state?.turn_number, lifecycleToken);
      }
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setInput("");
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setError(err.message || "删除消息失败。");
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setIsLoading(false);
    }
  }

  function startRewriteFromMessage(message) {
    if (message.sender !== "player" || isGameMutationBusy) return;
    setError("");
    setRewriteTarget({ index: message.index, text: message.text, previousInput: input });
    setInput(message.text);
    window.requestAnimationFrame(() => chatInputRef.current?.focus());
  }

  function cancelRewrite() {
    setInput(rewriteTarget?.previousInput || "");
    setRewriteTarget(null);
  }

  async function submitRewriteMessage(rawMessage) {
    const message = String(rawMessage || "").trim();
    const gameId = activeGameId;
    const lifecycleToken = gameLifecycleRef.current;
    if (!message || !gameId || !rewriteTarget || isGameMutationBusy || !isCurrentGameLifecycle(gameId, lifecycleToken)) return;

    const targetMessageIndex = rewriteTarget.index;
    const optimisticMessageId = `${gameId}-rewrite-${++optimisticMessageIdRef.current}`;
    const rewriteUiRollback = preparePlayerRewriteUiRollback({
      messages,
      actionSuggestions,
      workflowEvents,
      dmThinking,
      actionSuggestionsLoading: isActionSuggestionsLoading,
    }, targetMessageIndex, message, optimisticMessageId);
    const rewriteUiSnapshot = rewriteUiRollback.snapshot;
    setIsLoading(true);
    setError("");
    // “重写”确认后立即切断旧分支；服务端仍负责按 rewind snapshot 恢复真正的权威状态。
    setMessages(rewriteUiRollback.next.messages);
    setWorkflowEvents(rewriteUiRollback.next.workflowEvents);
    setDmThinking({ ...rewriteUiRollback.next.dmThinking, status: "running", expanded: true });
    invalidateActionSuggestionProjection();
    setActionSuggestions(rewriteUiRollback.next.actionSuggestions);
    setInput("");
    try {
      const result = await rewriteGameMessage(gameId, targetMessageIndex, message, createTurnStreamHandlers(gameId, lifecycleToken));
      if (!isCurrentGameLifecycle(gameId, lifecycleToken)) return;
      const suggestionProjection = await syncGame(gameId, result.game_state, { actionSuggestions: result.action_suggestions, lifecycleToken });
      if (
        isCurrentGameLifecycle(gameId, lifecycleToken)
        && result.turn_status === "completed"
        && !suggestionProjection.generated
      ) {
        requestActionSuggestionProjection(gameId, result.game_state?.turn_number, lifecycleToken);
      }
    } catch (err) {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) {
        // 请求失败时没有可采用的新权威快照，恢复提交前的完整对话和临时投影。
        setMessages(rewriteUiSnapshot.messages);
        setActionSuggestions(rewriteUiSnapshot.actionSuggestions);
        setWorkflowEvents(rewriteUiSnapshot.workflowEvents);
        setDmThinking((current) => ({ ...current, status: "error", expanded: false, rollRecords: current.rollRecords.map((record) => ({ ...record, settlement: "unknown" })) }));
        if (rewriteUiSnapshot.actionSuggestionsLoading) {
          requestActionSuggestionProjection(gameId, gameState?.turn_number, lifecycleToken);
        }
        setError(err.message || "重写消息失败。");
        setInput((current) => current.trim() ? current : message);
      }
    } finally {
      if (isCurrentGameLifecycle(gameId, lifecycleToken)) setIsLoading(false);
    }
  }

  async function sendMessage() {
    if (rewriteTarget) {
      await submitRewriteMessage(input);
      return;
    }
    await submitChatMessage(input, { clearInput: true });
  }
  async function respondToPendingTurn(response) { await submitChatMessage(response); }

  function allowLocalMutation() {
    if (!localActionsLocked) return true;
    setError(localActionBlockMessage);
    return false;
  }

  async function createEncounterFromNames() {
    if (!activeGameId || !allowLocalMutation()) return;
    const enemyNames = encounterDraft.enemy_names.split("\n").map((name) => name.trim()).filter(Boolean);
    if (enemyNames.length === 0) return setError("请至少输入一个敌人名称。");
    try {
      setError("");
      const result = await startEncounter(activeGameId, {
        enemy_names: enemyNames,
        enemy_hp: Number(encounterDraft.enemy_hp || 10),
        enemy_ac: Number(encounterDraft.enemy_ac || 10),
      });
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "开始遭遇失败。"); }
  }

  async function createEncounterFromTemplate() {
    if (!activeGameId || !allowLocalMutation()) return;
    if (!encounterDraft.monster_id) return setError("请选择一个怪物模板。");
    try {
      setError("");
      const result = await spawnEncounterTemplate(activeGameId, {
        monster_id: encounterDraft.monster_id,
        quantity: Number(encounterDraft.quantity || 1),
        custom_name: encounterDraft.custom_name,
        side: encounterDraft.template_side,
        hp_override: encounterDraft.hp_override === "" ? null : Number(encounterDraft.hp_override),
      });
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "生成怪物模板遭遇失败。"); }
  }

  async function addQuickEnemy() {
    if (!activeGameId || !allowLocalMutation()) return;
    if (!encounterDraft.quick_enemy_name.trim()) return setError("请输入敌人名称。");
    try {
      setError("");
      const result = await addEncounterEnemy(activeGameId, {
        name: encounterDraft.quick_enemy_name.trim(),
        hp_max: Number(encounterDraft.quick_enemy_hp || 10),
        ac: Number(encounterDraft.quick_enemy_ac || 10),
        initiative_bonus: Number(encounterDraft.quick_enemy_initiative_bonus || 0),
        side: encounterDraft.quick_enemy_side,
      });
      await syncGame(activeGameId, result.game_state);
      setEncounterDraft((prev) => ({ ...prev, quick_enemy_name: "" }));
    } catch (err) { setError(err.message || "添加敌人失败。"); }
  }

  async function finishEncounter() {
    if (!activeGameId || !allowLocalMutation()) return;
    try {
      setError("");
      const result = await endEncounter(activeGameId);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "结束遭遇失败。"); }
  }

  async function dropEncounterCombatant(combatantRef) {
    if (!activeGameId || !allowLocalMutation()) return;
    try {
      setError("");
      const result = await removeEncounterCombatant(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "移除单位失败。"); }
  }

  async function saveEncounterInitiative(combatantRef) {
    if (!activeGameId || !allowLocalMutation()) return;
    try {
      setError("");
      const result = await setEncounterInitiative(activeGameId, combatantRef, Number(initiativeDrafts[combatantRef] || 0));
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "设置先攻失败。"); }
  }

  async function rerollEncounterInitiative(combatantRef) {
    if (!activeGameId || !allowLocalMutation()) return;
    try {
      setError("");
      const result = await rollEncounterInitiative(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "重掷先攻失败。"); }
  }

  async function runAction(kind) {
    if (!activeGameId || !allowLocalMutation()) return;
    try {
      let result;
      if (kind === "advance") result = await advanceTurn(activeGameId);
      if (kind === "attack") {
        const { attack_name: _attackName, ...payload } = actionDraft.attack;
        result = await attackAction(activeGameId, { ...payload, attack_bonus: Number(payload.attack_bonus) });
      }
      if (kind === "spell") result = await castSpellAction(activeGameId, { ...actionDraft.spell, slot_level: Number(actionDraft.spell.slot_level || 0) });
      if (kind === "skill") result = await skillCheckAction(activeGameId, { ...actionDraft.skill, dc: Number(actionDraft.skill.dc || 0), modifier: actionDraft.skill.modifier === "" ? null : Number(actionDraft.skill.modifier) });
      if (kind === "save") result = await savingThrowAction(activeGameId, { ...actionDraft.save, dc: Number(actionDraft.save.dc || 0), modifier: actionDraft.save.modifier === "" ? null : Number(actionDraft.save.modifier) });
      if (kind === "item") result = await itemActionRequest(activeGameId, { ...actionDraft.item, quantity: Number(actionDraft.item.quantity || 1) });
      if (result?.game_state) await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "执行动作失败。"); }
  }

  const encounter = gameState?.encounter;
  const combatants = encounter?.initiative_order?.map((id) => encounter.combatants[id]).filter(Boolean) || [];
  const timeline = (gameState?.timeline || []).filter(isPlayerVisibleTimelineEvent).slice(-12).reverse();
  const evidenceRecords = gameState?.evidence_records || [];
  const partyCharacters = Object.values(gameState?.characters || {});
  const activeCharacterId = gameState?.active_character_id || partyCharacters[0]?.character_id || "";
  const characterActorById = Object.fromEntries(charActors.map((actor) => [actor.ref, actor]));
  const currentCombatant = encounter?.combatants?.[encounter.current_combatant_id];
  const playerDecisionAvailable = !encounter?.active || Boolean(
    currentCombatant?.side === "party"
    && currentCombatant?.linked_character_id
    && gameState?.characters?.[currentCombatant.linked_character_id]
  );
  const visibleActionSuggestions = (
    gameState?.campaign?.phase === "adventure_selection" || !playerDecisionAvailable
  ) ? [] : actionSuggestions;

  return (
    <div className="app-container">
      {!["home", "new_game", "creator", "characters", "monsters"].includes(view) && (
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">DM</span>
            <span>Agent</span>
          </div>
          <div className="menu-items">
            <div className="menu-active-info">当前游戏：{activeGameId}</div>
            <button onClick={() => setView("chat")} className={view === "chat" ? "active" : ""}>对话</button>
            <button onClick={() => setView("status")} className={view === "status" ? "active" : ""}>时间线</button>
            <button className="btn-danger" onClick={leaveGame}>返回主页</button>
          </div>
        </aside>
      )}
      <main className="main-content">
        {error && <div className="list-item error-banner" style={{ margin: 16 }}>{error}</div>}
        {deleteRequest && (
          <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="delete-confirm-title">
            <div className="modal-content delete-confirm-modal anime-pop">
              <div className="delete-confirm-header">
                <span className="danger-mark">!</span>
                <div>
                  <p className="eyebrow">删除确认 {deleteRequest.step} / 2</p>
                  <h2 id="delete-confirm-title">确认删除{deleteRequest.kind === "game" ? "已保存游戏" : "角色卡模板"}</h2>
                </div>
              </div>
              <p className="delete-confirm-copy">
                即将删除 <strong>{deleteRequest.label}</strong>。这个操作会移除本地保存文件，不能从界面内撤销。
              </p>
              <div className="confirm-step-track" aria-label="删除确认进度">
                {[1, 2].map((step) => (
                  <span key={step} className={`confirm-step ${deleteRequest.step >= step ? "active" : ""}`}>
                    {step}
                  </span>
                ))}
              </div>
              <div className="btn-row">
                <button type="button" className="btn-text" disabled={deleteRequest.busy} onClick={cancelDeleteRequest}>
                  取消
                </button>
                <button type="button" className="btn-danger" disabled={deleteRequest.busy} onClick={confirmDeleteRequest}>
                  {deleteRequest.busy ? "正在删除..." : deleteRequest.step < 2 ? "第一次确认" : "第二次确认并删除"}
                </button>
              </div>
            </div>
          </div>
        )}

        {view === "home" && (
          <div className="home-container anime-fade-in">
            <section className="lobby-hero">
              <div className="lobby-title-block">
                <div className="eyebrow">DM Agent</div>
                <h1 className="title-hero">D&D 2024 跑团主持台</h1>
                <p className="subtitle">今晚的桌面已经铺开。选择一局存档，或先整理自己的角色卡。</p>
              </div>
              <div className="card-grid" aria-label="主要操作">
                <button type="button" className="bento-card glow-hover" onClick={() => setView("new_game")}>
                  <div className="card-icon">骰</div>
                  <h3>新建游戏</h3>
                  <p>开一张新桌，并带入队伍角色。</p>
                </button>
                <button type="button" className="bento-card glow-hover" onClick={openCreator}>
                  <div className="card-icon">人</div>
                  <h3>创建角色卡</h3>
                  <p>整理角色模板、装备与职业资源。</p>
                </button>
                <button type="button" className="bento-card glow-hover" onClick={openCharacterLibrary}>
                  <div className="card-icon">册</div>
                  <h3>角色卡模板</h3>
                  <p>查看可带入游戏的玩家角色卡。</p>
                </button>
              </div>
            </section>

            <section className="lobby-panel model-settings-panel" aria-label="模型配置">
              <div className="panel-heading panel-heading-actions">
                <div>
                  <h3>模型设置</h3>
                  <p className="info-text">选择或保存本地模型档案，后续回合会使用当前启用的档案。</p>
                </div>
                <div className="panel-actions">
                  <span>{llmConnectionLabel}</span>
                  <span>{isLobbyLoading ? "正在加载模型档案" : activeLlmProfile?.label || "无当前档案"}</span>
                </div>
              </div>
              <div className="model-profile-selector">
                <div className="form-group">
                  <label>选择模型档案</label>
                  <select
                    value={llmDraft.profile_id || ""}
                    onChange={(e) => {
                      if (e.target.value === "__new__") beginNewLlmProfile();
                      else chooseLlmProfile(e.target.value);
                    }}
                    disabled={isLlmSaving}
                  >
                    <option value="" disabled>{llmProfiles.length === 0 ? "暂无已保存档案" : "选择一个模型档案"}</option>
                    {llmProfiles.map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.label}{profile.active ? "（当前）" : ""}
                        {profile.provider === "openai-compatible" && !profile.api_key_configured ? " · 未保存密钥" : ""}
                      </option>
                    ))}
                    <option value="__new__">新建模型档案...</option>
                  </select>
                </div>
                <button type="button" className="btn-secondary" onClick={beginNewLlmProfile} disabled={isLlmSaving}>新建档案</button>
              </div>
              <form className="model-settings-form" onSubmit={saveLlmConfig}>
                <div className="model-settings-grid">
                  <div className="form-group">
                    <label>条目名称</label>
                    <input
                      value={llmDraft.profile_label}
                      onChange={(e) => setLlmDraft((prev) => ({ ...prev, profile_label: e.target.value }))}
                      placeholder="例如：DeepSeek 主账号"
                      disabled={isLlmSaving}
                    />
                  </div>
                  <div className="form-group">
                    <label>接入方式</label>
                    <select
                      value={llmDraft.provider}
                      onChange={(e) => setLlmDraft((prev) => {
                        const provider = e.target.value;
                        return {
                          ...prev,
                          provider,
                          model_name: provider === "codex-cli" ? CODEX_DEFAULT_MODEL : "",
                          reasoning_effort: provider === "codex-cli" ? CODEX_DEFAULT_REASONING_EFFORT : "",
                          cli_command: provider === "claude-code" ? "claude" : provider === "codex-cli" ? "codex" : "",
                        };
                      })}
                      disabled={isLlmSaving}
                    >
                      {Object.entries(MODEL_PROVIDER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>模型名称</label>
                    <input
                      value={llmDraft.model_name}
                      onChange={(e) => setLlmDraft((prev) => ({ ...prev, model_name: e.target.value }))}
                      placeholder={llmDraft.provider === "openai-compatible" ? "deepseek-v4-flash" : llmDraft.provider === "codex-cli" ? CODEX_DEFAULT_MODEL : "可留空，使用 CLI 默认模型"}
                      disabled={isLlmSaving}
                    />
                  </div>
                  {llmDraft.provider === "openai-compatible" ? (
                    <>
                      <div className="form-group">
                        <label>Base URL</label>
                        <input
                          value={llmDraft.base_url}
                          onChange={(e) => setLlmDraft((prev) => ({ ...prev, base_url: e.target.value }))}
                          placeholder="https://api.deepseek.com"
                          disabled={isLlmSaving}
                        />
                      </div>
                      <div className="form-group">
                        <label>API Key</label>
                        <input
                          type="password"
                          value={llmDraft.api_key}
                          onChange={(e) => setLlmDraft((prev) => ({ ...prev, api_key: e.target.value }))}
                          placeholder={editingLlmProfile?.api_key_configured ? "留空保持该档案密钥" : "填写 API Key"}
                          autoComplete="new-password"
                          disabled={isLlmSaving}
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="form-group">
                        <label>CLI 命令</label>
                        <input
                          value={llmDraft.cli_command}
                          onChange={(e) => setLlmDraft((prev) => ({ ...prev, cli_command: e.target.value }))}
                          placeholder={llmDraft.provider === "claude-code" ? "claude" : "codex"}
                          disabled={isLlmSaving}
                        />
                      </div>
                      <div className="form-group">
                        <label>每轮处理超时（秒）</label>
                        <input
                          type="number"
                          min="10"
                          max="1800"
                          value={llmDraft.cli_timeout_s}
                          onChange={(e) => setLlmDraft((prev) => ({ ...prev, cli_timeout_s: e.target.value }))}
                          disabled={isLlmSaving}
                        />
                      </div>
                      {llmDraft.provider === "codex-cli" && (
                        <div className="form-group">
                          <label>推理强度</label>
                          <select
                            value={llmDraft.reasoning_effort}
                            onChange={(e) => setLlmDraft((prev) => ({ ...prev, reasoning_effort: e.target.value }))}
                            disabled={isLlmSaving}
                          >
                            {CODEX_REASONING_EFFORTS.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                          </select>
                        </div>
                      )}
                    </>
                  )}
                </div>
                <div className="model-settings-footer">
                  <p className="info-text">{llmStatusMessage || llmHealthMessage || (llmDraft.provider === "openai-compatible"
                    ? "API Key 不会显示；编辑已有档案时留空会保留该档案当前密钥。"
                    : llmDraft.provider === "codex-cli"
                      ? "Codex CLI 默认使用 gpt-5.6-terra / high；仅复用本机登录态，并在隔离的临时只读目录中运行。"
                      : "CLI 使用本机已有登录态；运行时被限制在临时只读工作目录中。")}</p>
                  <button type="submit" className="btn-primary" disabled={isLlmSaving}>
                    {isLlmSaving ? "保存中..." : "保存并启用"}
                  </button>
                </div>
              </form>
            </section>

            <section className="lobby-grid">
              <div className="lobby-panel">
                <div className="panel-heading panel-heading-actions">
                  <h3>已保存游戏</h3>
                  <div className="panel-actions">
                    <span>{games.length} 局</span>
                    {games.length > 0 && (
                      <button type="button" className="mini-action" onClick={toggleGameDeleteMode}>
                        {gameDeleteMode ? "完成" : "批量选择"}
                      </button>
                    )}
                  </div>
                </div>
                <div className="scroll-list">
                  {games.length === 0 && <p className="empty-text">还没有已保存的游戏。</p>}
                  {games.map((game) => (
                    <div key={game.game_id} className={`list-item split-list-item ${selectedGameDeleteSet.has(game.game_id) ? "is-selected" : ""}`}>
                      <button
                        type="button"
                        className="list-main-action"
                        aria-pressed={gameDeleteMode ? selectedGameDeleteSet.has(game.game_id) : undefined}
                        onClick={() => gameDeleteMode ? toggleGameDeleteSelection(game.game_id) : enterGame(game.game_id)}
                      >
                        {gameDeleteMode && <span className={`selection-box ${selectedGameDeleteSet.has(game.game_id) ? "checked" : ""}`} />}
                        <span className="icon">骰</span>
                        <span>{game.title}（{localizeScene(game.scene)}）{game.encounter_active ? " · 战斗中" : ""}</span>
                      </button>
                      {!gameDeleteMode && (
                        <button
                          type="button"
                          className="delete-inline"
                          aria-label={`删除游戏 ${game.title || game.game_id}`}
                          title="删除游戏"
                          onClick={() => requestGameDeletion(game)}
                        >
                          删除
                        </button>
                      )}
                    </div>
                  ))}
                  {gameDeleteMode && (
                    <div className="batch-delete-bar">
                      <span>已选择 {selectedGameDeleteCount} 局</span>
                      <button type="button" className="btn-text" onClick={clearGameDeleteSelection}>清空</button>
                      <button type="button" className="btn-secondary" onClick={selectAllGameDeletes}>全选</button>
                      <button type="button" className="btn-danger" disabled={selectedGameDeleteCount === 0} onClick={requestSelectedGameDeletion}>删除所选</button>
                    </div>
                  )}
                </div>
              </div>
              <div className="lobby-panel">
                <div className="panel-heading panel-heading-actions">
                  <h3>角色卡模板</h3>
                  <div className="panel-actions">
                    <span>{characters.length} 张</span>
                    {characters.length > 0 && (
                      <button type="button" className="mini-action" onClick={toggleCharacterDeleteMode}>
                        {characterDeleteMode ? "完成" : "批量选择"}
                      </button>
                    )}
                  </div>
                </div>
                <div className="scroll-list">
                  {characters.length === 0 && <p className="empty-text">还没有角色卡。先创建一张角色卡，再开局。</p>}
                  {characters.map((character) => (
                    <div key={character.character_id} className={`list-item split-list-item ${selectedCharacterDeleteSet.has(character.character_id) ? "is-selected" : ""}`}>
                      <button
                        type="button"
                        className="list-main-action"
                        aria-pressed={characterDeleteMode ? selectedCharacterDeleteSet.has(character.character_id) : undefined}
                        onClick={() => characterDeleteMode ? toggleCharacterDeleteSelection(character.character_id) : openCharacterSheet(character.character_id)}
                      >
                        {characterDeleteMode && <span className={`selection-box ${selectedCharacterDeleteSet.has(character.character_id) ? "checked" : ""}`} />}
                        <span className="icon">角</span>
                        <span>{character.name} · {character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</span>
                      </button>
                      {!characterDeleteMode && (
                        <button
                          type="button"
                          className="delete-inline"
                          aria-label={`删除角色卡 ${character.name}`}
                          title="删除角色卡"
                          onClick={() => requestCharacterDeletion(character)}
                        >
                          删除
                        </button>
                      )}
                    </div>
                  ))}
                  {characterDeleteMode && (
                    <div className="batch-delete-bar">
                      <span>已选择 {selectedCharacterDeleteCount} 张</span>
                      <button type="button" className="btn-text" onClick={clearCharacterDeleteSelection}>清空</button>
                      <button type="button" className="btn-secondary" onClick={selectAllCharacterDeletes}>全选</button>
                      <button type="button" className="btn-danger" disabled={selectedCharacterDeleteCount === 0} onClick={requestSelectedCharacterDeletion}>删除所选</button>
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        )}

        {view === "characters" && (
          <div className="character-library anime-slide-up">
            <header className="library-header">
              <div>
                <p className="eyebrow">角色卡模板</p>
                <h1>玩家角色册</h1>
                <p className="info-text">查看已保存角色的完整卡面，再决定带谁入局。</p>
              </div>
              <div className="btn-row">
                <button className="btn-text" onClick={() => setView("home")}>返回主页</button>
                <button className="btn-primary" onClick={openCreator}>创建新角色</button>
              </div>
            </header>
            <div className="character-library-layout">
              <aside className="character-roster panel-card">
                <div className="panel-heading panel-heading-actions">
                  <h3>已保存角色</h3>
                  <div className="panel-actions">
                    <span>{characters.length} 张</span>
                    {characters.length > 0 && (
                      <button type="button" className="mini-action" onClick={toggleCharacterDeleteMode}>
                        {characterDeleteMode ? "完成" : "批量选择"}
                      </button>
                    )}
                  </div>
                </div>
                <div className="scroll-list">
                  {characters.length === 0 && <p className="empty-text">还没有角色卡。先创建一张角色卡，再回来查看。</p>}
                  {characters.map((character) => (
                    <div key={character.character_id} className={`character-roster-row ${selectedCharacterDeleteSet.has(character.character_id) ? "is-selected" : ""}`}>
                      <button
                        type="button"
                        className={`character-roster-item ${selectedCharacter?.character_id === character.character_id ? "selected" : ""}`}
                        aria-pressed={characterDeleteMode ? selectedCharacterDeleteSet.has(character.character_id) : undefined}
                        onClick={() => characterDeleteMode ? toggleCharacterDeleteSelection(character.character_id) : openCharacterSheet(character.character_id)}
                      >
                        {characterDeleteMode && <span className={`selection-box ${selectedCharacterDeleteSet.has(character.character_id) ? "checked" : ""}`} />}
                        <span className="avatar">角</span>
                        <span>
                          <strong>{character.name}</strong>
                          <small>{character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</small>
                        </span>
                      </button>
                      {!characterDeleteMode && (
                        <button
                          type="button"
                          className="delete-inline roster-delete"
                          aria-label={`删除角色卡 ${character.name}`}
                          title="删除角色卡"
                          onClick={() => requestCharacterDeletion(character)}
                        >
                          删除
                        </button>
                      )}
                    </div>
                  ))}
                  {characterDeleteMode && (
                    <div className="batch-delete-bar">
                      <span>已选择 {selectedCharacterDeleteCount} 张</span>
                      <button type="button" className="btn-text" onClick={clearCharacterDeleteSelection}>清空</button>
                      <button type="button" className="btn-secondary" onClick={selectAllCharacterDeletes}>全选</button>
                      <button type="button" className="btn-danger" disabled={selectedCharacterDeleteCount === 0} onClick={requestSelectedCharacterDeletion}>删除所选</button>
                    </div>
                  )}
                </div>
              </aside>
              <section className="character-sheet-stage">
                {isCharacterLoading ? (
                  <div className="character-sheet-empty">
                    <h2>读取角色卡中...</h2>
                    <p className="info-text">正在从本地存档载入完整角色信息。</p>
                  </div>
                ) : (
                  <CharacterSheetDetail character={selectedCharacter} />
                )}
              </section>
            </div>
          </div>
        )}

        {view === "creator" && (
          <div className="creator-container anime-slide-up">
            <div className="panel-card">
              <div className="step-indicator">
                {CREATOR_STEPS.map((step, index) => (
                  <React.Fragment key={step.id}>
                    <button type="button" className={`step ${creatorStep === index ? "active" : ""} ${creatorStep > index ? "done" : ""}`} onClick={() => goToCreatorStep(index)}>
                      <span className="step-index">{index + 1}</span>
                      <span className="step-label">{step.label}</span>
                    </button>
                    {index < CREATOR_STEPS.length - 1 && <div className="line" />}
                  </React.Fragment>
                ))}
              </div>
              <div className="creator-header">
                <div>
                  <h2 style={{ marginBottom: 8 }}>角色构筑</h2>
                  <p className="info-text">当前步骤：{CREATOR_STEPS[creatorStep].label}</p>
                </div>
                <p className="info-text">按“基础 → 构筑 → 装备 → 法术 → 总览”的顺序完成创建。</p>
              </div>

              {creatorStep === 0 && (
                <>
                  <div className="form-group">
                    <label>角色名</label>
                    <input value={charDraft.name} onChange={(e) => setCharDraft((p) => ({ ...p, name: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <label>种族</label>
                    {builder.species.length === 0 ? renderBuilderLoadState("种族目录") : <div className="class-grid">
                      {builder.species.map((species) => <ChoiceButton key={species.id} selected={charDraft.species === species.name} onClick={() => setCharDraft((p) => ({ ...p, species: species.name }))}>{species.name_display || localizeSpeciesName(species.name)}</ChoiceButton>)}
                    </div>}
                  </div>
                  <div className="form-group">
                    <label>背景</label>
                    {builder.backgrounds.length === 0 ? renderBuilderLoadState("背景目录") : <div className="class-grid">
                      {builder.backgrounds.map((bg) => <ChoiceButton key={bg.id} selected={charDraft.background_name === bg.name} onClick={() => chooseBackground(bg.name)}>{bg.name_display || localizeBackgroundName(bg.name)}</ChoiceButton>)}
                    </div>}
                  </div>
                  <div className="form-group">
                    <label>起源专长</label>
                    <div className="locked-field">{background?.origin_feat_display || localizeOriginFeat(charDraft.origin_feat) || "选择背景后确定"}</div>
                    <p className="info-text" style={{ marginTop: 8 }}>起源专长由所选背景决定。</p>
                  </div>
                </>
              )}

              {creatorStep === 1 && (
                <>
                  <div className="form-group">
                    <label>职业</label>
                    {builder.classes.length === 0 ? renderBuilderLoadState("职业目录") : <div className="class-grid">
                      {builder.classes.map((cls) => <ChoiceButton key={cls.id} selected={charDraft.class_name === cls.name} disabled={isAbilityGenerating} onClick={() => chooseClass(cls)}>{cls.name_display || localizeClassName(cls.name)}</ChoiceButton>)}
                    </div>}
                  </div>
                  <div className="builder-preview-grid">
                    <div className="builder-preview-card">
                      <h3>生命上限</h3>
                      <div className="timeline-summary">{computedHpMax}</div>
                      <div className="timeline-content">按职业生命骰和体质调整值自动计算。</div>
                    </div>
                    <div className="builder-preview-card">
                      <h3>属性生成</h3>
                      <div className="timeline-summary">{ABILITY_METHOD_LABELS[abilityGenerationMethod]}</div>
                      <div className="timeline-content">{abilityGenerationMethod === "point_buy" ? `已用 ${pointBuySpent}/${pointBuyRules.budget}，剩余 ${pointBuyRemaining} 点。` : abilityPool.map((slot) => slot.score).join(" · ") || "选择一种生成方式。"}</div>
                    </div>
                  </div>
                  <div className="ability-method-picker" role="group" aria-label="属性生成方式">
                    {Object.entries(ABILITY_METHOD_LABELS).map(([method, label]) => (
                      <button
                        type="button"
                        key={method}
                        className={abilityGenerationMethod === method ? "selected" : ""}
                        aria-pressed={abilityGenerationMethod === method}
                        disabled={!classDef || isAbilityGenerating}
                        onClick={() => abilityGenerationMethod !== method && setAbilityGenerationMethod(method)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {abilityGenerationMethod === "point_buy" ? (
                    <div className="stats-editor">
                      {STATS.map((stat) => <div key={stat} className="stat-row"><span className="stat-name">{localizeStat(stat)}</span><button onClick={() => adjustStat(stat, -1)}>-</button><span className="stat-val">{charDraft.stats[stat]}</span><button onClick={() => adjustStat(stat, 1)}>+</button></div>)}
                    </div>
                  ) : (
                    <>
                      <div className="ability-pool-header">
                        <span>{abilityGenerationMethod === "rolled" ? "本次骰池" : "标准数组"}</span>
                        {abilityGenerationMethod === "rolled" && <button type="button" className="btn-secondary" disabled={isAbilityGenerating} onClick={() => setAbilityGenerationMethod("rolled")}>{isAbilityGenerating ? "掷骰中…" : "重新掷骰"}</button>}
                      </div>
                      <div className="ability-pool" aria-live="polite">
                        {abilityPool.map((slot) => (
                          <div key={slot.slot_id} className="ability-pool-slot">
                            {slot.dice?.length > 0 ? slot.dice.map((die, index) => <span key={`${slot.slot_id}-${index}`} className={index === slot.dropped_index ? "dropped" : ""}>{die}</span>) : <span>{slot.score}</span>}
                            {slot.dice?.length > 0 && <strong>= {slot.score}</strong>}
                          </div>
                        ))}
                      </div>
                      <div className="stats-editor ability-assignment-editor">
                        {STATS.map((stat) => (
                          <label key={stat} className="ability-assignment-row">
                            <span className="stat-name">{localizeStat(stat)}</span>
                            <select value={abilityAssignments[stat] || ""} onChange={(event) => assignAbilitySlot(stat, event.target.value)}>
                              {abilityPool.map((slot, index) => <option key={slot.slot_id} value={slot.slot_id}>{slot.score} · 第 {index + 1} 组</option>)}
                            </select>
                            <strong>{charDraft.stats[stat]}</strong>
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                  <div className="form-group" style={{ marginTop: 24 }}>
                    <label>职业技能</label>
                    {!classDef ? <p className="info-text">先选择职业，才能分配职业技能。</p> : <><p className="spell-meta">需要选择 {classSkillTarget} 项职业技能，当前 {selectedClassSkillCount}/{classSkillTarget}。</p><div className="class-grid skill-choice-grid">
                      {(classDef?.skill_choices || []).map((skill) => {
                        const providedByBackground = backgroundSkills.has(skill);
                        const selected = Number(charDraft.skill_proficiencies[skill] || 0) > 0;
                        return <ChoiceButton key={skill} className="skill-choice-card" selected={selected} disabled={providedByBackground} onClick={() => toggleSkill(skill)}>{localizeSkill(skill)}{providedByBackground && <span className="choice-note">背景已提供</span>}</ChoiceButton>;
                      })}
                    </div></>}
                  </div>
                </>
              )}

              {creatorStep === 2 && (
                <>
                  <div className="form-group">
                    <label>装备方案</label>
                    {!classDef ? <p className="info-text">先选择职业，才能设置起始装备。</p> : <div className="class-grid">
                      <ChoiceButton selected={charDraft.equipment_mode === "starter_package"} onClick={() => setEquipmentMode("starter_package")}><strong>标准套装</strong><p className="spell-meta">按职业起始方案直接发放</p></ChoiceButton>
                      <ChoiceButton selected={charDraft.equipment_mode === "custom_purchase"} onClick={() => setEquipmentMode("custom_purchase")}><strong>自定义购买</strong><p className="spell-meta">预算 {formatGoldLine(customPurchaseBudgetGp)}</p></ChoiceButton>
                    </div>}
                  </div>

                  {classDef && charDraft.equipment_mode === "starter_package" && (
                    <>
                      <div className="form-group">
                        <label>起始装备包</label>
                        {starterOptions.length === 0 ? <p className="info-text">当前职业还没有起始装备包元数据。</p> : <div className="class-grid">
                          {starterOptions.map((option) => <ChoiceButton key={option.id} selected={selectedStarterOption?.id === option.id} onClick={() => chooseStarterOption(option.id)}><strong>{option.label_display || option.label}</strong><p className="spell-meta">{formatGoldLine(option.gold_gp)}</p></ChoiceButton>)}
                        </div>}
                      </div>
                      {starterChoiceGroups.map((group) => (
                        <div key={group.id} className="form-group">
                          <label>{group.label_display || group.label}</label>
                          <p className="info-text">{group.description_display || group.description}</p>
                          <div className="class-grid" style={{ marginTop: 12 }}>
                            {(group.options || []).map((option) => <ChoiceButton key={option.id} selected={charDraft.starter_choice_ids[group.id] === option.id} onClick={() => chooseStarterChoice(group.id, option.id)}><strong>{option.label_display || option.label}</strong></ChoiceButton>)}
                          </div>
                        </div>
                      ))}
                    </>
                  )}

                  {classDef && charDraft.equipment_mode === "custom_purchase" && (
                    <div className="builder-preview-grid">
                      {groupedShopItems.map((group) => (
                        <ShopCarousel
                          key={group.type}
                          group={group}
                          quantities={charDraft.custom_purchase_items}
                          onQuantityChange={setCustomPurchaseQuantity}
                        />
                      ))}
                    </div>
                  )}

                  {charDraft.equipment_mode === "custom_purchase" && (
                    <div className="form-group">
                      <label>自定义待定装备</label>
                      <div className="dual-grid">
                        <div className="form-group">
                          <label>名称</label>
                          <input value={charDraft.custom_pending_item?.name || ""} onChange={(e) => updatePendingCustomItem("name", e.target.value)} placeholder="例如：家传短刃" />
                        </div>
                        <div className="form-group">
                          <label>数量</label>
                          <input type="number" min="1" value={charDraft.custom_pending_item?.quantity || 1} onChange={(e) => updatePendingCustomItem("quantity", Number.parseInt(e.target.value || "1", 10))} />
                        </div>
                        <div className="form-group">
                          <label>预留预算（金币）</label>
                          <input type="number" min="0" value={charDraft.custom_pending_item?.reserved_cost_gp || 0} onChange={(e) => updatePendingCustomItem("reserved_cost_gp", Number.parseInt(e.target.value || "0", 10))} />
                        </div>
                        <div className="form-group">
                          <label>说明</label>
                          <input value={charDraft.custom_pending_item?.notes || ""} onChange={(e) => updatePendingCustomItem("notes", e.target.value)} placeholder="由主持人决定材质、伤害、特效等" />
                        </div>
                      </div>
                      <p className="info-text">这件装备只记录名称、数量和预算占用，具体属性在角色创建后由主持人决定。</p>
                    </div>
                  )}

                  <div className="builder-preview-grid">
                    <div className="builder-preview-card">
                      <h3>预算</h3>
                      <div className="timeline-summary">{formatGoldLine(equipmentBudgetGp)}</div>
                      <div className="timeline-content">已花费 {formatGoldLine(equipmentSpentGp)}，剩余 {formatGoldLine(equipmentRemainingGp)}</div>
                    </div>
                    <div className="builder-preview-card">
                      <h3>当前装备预览</h3>
                      {finalEquipmentPreview.length === 0 ? <p className="info-text">还没有选入任何起始装备。</p> : <div className="timeline-list">
                        {finalEquipmentPreview.map((item, index) => <div key={`${item.name}-${index}`} className="timeline-item"><div className="timeline-summary">{item.name_display || item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || localizeEquipmentType(item.type)}</div>{(item.notes_display || item.notes) && <div className="timeline-content">{item.notes_display || item.notes}</div>}</div>)}
                      </div>}
                    </div>
                  </div>
                </>
              )}

              {creatorStep === 3 && (
                <>
                  <div className="builder-preview-grid">
                    <div className="builder-preview-card">
                      <h3>职业资源</h3>
                      {!classDef ? <p className="info-text">选择职业后即可预览 1 级资源。</p> : starterResources.length === 0 ? <p className="info-text">当前职业没有可追踪的 1 级资源。</p> : <div className="timeline-list">{starterResources.map(([name, resource]) => <div key={name} className="timeline-item"><div className="timeline-summary">{localizeClassResource(name)} · {resource.current_value}/{resource.max_value}</div><div className="timeline-content">{resource.description_display || resource.description || "职业资源"} · 恢复方式：{formatResourceRecovery(resource)}</div></div>)}</div>}
                    </div>
                    <div className="builder-preview-card">
                      <h3>起始法术位</h3>
                      {!classDef ? <p className="info-text">选择职业后即可预览 1 级法术位。</p> : !classDef.spellcasting_ability ? <p className="info-text">当前职业起始时不具备施法能力。</p> : startingSpellSlots.length === 0 ? <div><p className="info-text">该职业在 1 级时没有可用法术位。</p><p className="spell-meta">施法属性：{localizeStat(classDef.spellcasting_ability)} · 方式：{localizeSpellcastingMode(classDef.spellcasting_mode)}</p></div> : <div><p className="spell-meta">施法属性：{localizeStat(classDef.spellcasting_ability)} · 方式：{localizeSpellcastingMode(classDef.spellcasting_mode)}</p><div className="timeline-list">{startingSpellSlots.map((slot) => <div key={slot[0]} className="timeline-item"><div className="timeline-summary">{formatSpellSlotLine(slot)}</div><div className="timeline-content">长休后恢复全部法术位。</div></div>)}</div></div>}
                    </div>
                  </div>
                  <div className="form-group">
                    <label>戏法</label>
                    {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasCantripSelection ? <p className="info-text">当前职业在 1 级时不获得戏法。</p> : <div><p className="spell-meta">需要选择 {startingCantripCount} 个戏法。</p><p className="spell-meta">已选 {charDraft.selectedCantrips.length}/{startingCantripCount}</p>{cantripOptions.length === 0 ? <p className="info-text">当前职业没有可用的戏法列表。</p> : <div className="spell-grid">{cantripOptions.map((spell) => <SpellChoiceButton key={spell.id || spell.name} selected={charDraft.selectedCantrips.includes(spell.name)} onClick={() => toggleCantrip(spell.name)}><h4>{localizeName(spell)}</h4><p className="spell-meta">戏法 · {spell.school_display || spell.school}</p></SpellChoiceButton>)}</div>}</div>}
                  </div>
                  <div className="form-group">
                    <label>已准备法术</label>
                    {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasLevelOneSpellcasting ? <p className="info-text">当前职业在 1 级时没有可准备的法术位。</p> : <div><p className="spell-meta">需要选择 {startingPreparedSpellCount} 个 1 环及以上法术。</p><p className="spell-meta">已选 {charDraft.selectedSpells.length}/{startingPreparedSpellCount}</p>{levelOnePreparedSpells.length === 0 ? <p className="info-text">当前职业没有可用的 1 环及以上法术列表。</p> : <div className="spell-grid">{levelOnePreparedSpells.map((spell) => <SpellChoiceButton key={spell.id || spell.name} selected={charDraft.selectedSpells.includes(spell.name)} onClick={() => togglePreparedSpell(spell.name)}><h4>{localizeName(spell)}</h4><p className="spell-meta">{spell.level} 环 · {spell.school_display || spell.school}</p></SpellChoiceButton>)}</div>}</div>}
                  </div>
                </>
              )}

              {creatorStep === 4 && (
                <div className="builder-preview-grid review-grid">
                  <div className="builder-preview-card">
                    <h3>基础信息</h3>
                    <div className="timeline-summary">{charDraft.name || "未命名角色"}</div>
                    <div className="timeline-content">{localizeSpeciesName(charDraft.species)} · {background?.name_display || localizeBackgroundName(charDraft.background_name)}</div>
                    <div className="timeline-content">起源专长：{background?.origin_feat_display || localizeOriginFeat(charDraft.origin_feat)}</div>
                  </div>
                  <div className="builder-preview-card">
                    <h3>职业构筑</h3>
                    <div className="timeline-summary">{classDef?.name_display || localizeClassName(charDraft.class_name)}</div>
                    <div className="timeline-content">生命上限 {computedHpMax} · 职业技能 {selectedClassSkillCount}/{classSkillTarget}</div>
                    <div className="timeline-content">属性生成：{ABILITY_METHOD_LABELS[abilityGenerationMethod]}</div>
                    <div className="timeline-content">{STATS.map((stat) => `${localizeStat(stat)} ${charDraft.stats[stat]}`).join(" · ")}</div>
                  </div>
                  <div className="builder-preview-card">
                    <h3>装备</h3>
                    <div className="timeline-summary">{charDraft.equipment_mode === "custom_purchase" ? "自定义购买" : selectedStarterOption?.label_display || selectedStarterOption?.label || "标准套装"}</div>
                    <div className="timeline-content">预算 {formatGoldLine(equipmentBudgetGp)} · 剩余 {formatGoldLine(equipmentRemainingGp)}</div>
                    {finalEquipmentPreview.length === 0 ? <p className="info-text">暂无装备。</p> : <div className="timeline-list">{finalEquipmentPreview.map((item, index) => <div key={`${item.name}-${index}`} className="timeline-item"><div className="timeline-summary">{item.name_display || item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || localizeEquipmentType(item.type)}</div>{(item.notes_display || item.notes) && <div className="timeline-content">{item.notes_display || item.notes}</div>}</div>)}</div>}
                  </div>
                  <div className="builder-preview-card">
                    <h3>法术</h3>
                    {!classDef?.spellcasting_ability ? <p className="info-text">该职业起始时没有施法能力。</p> : <><div className="timeline-content">戏法：{charDraft.selectedCantrips.length ? charDraft.selectedCantrips.join("、") : "无"}</div><div className="timeline-content">已准备：{charDraft.selectedSpells.length ? charDraft.selectedSpells.join("、") : "无"}</div><div className="timeline-content">施法属性：{localizeStat(classDef.spellcasting_ability)} · 方式：{localizeSpellcastingMode(classDef.spellcasting_mode)}</div></>}
                  </div>
                </div>
              )}

              <div className="btn-row creator-nav">
                <button className="btn-text" onClick={() => creatorStep === 0 ? setView("home") : goToCreatorStep(creatorStep - 1)}>{creatorStep === 0 ? "返回" : "上一步"}</button>
                {creatorStep < CREATOR_STEPS.length - 1
                  ? <button className="btn-primary" onClick={() => goToCreatorStep(creatorStep + 1)}>下一步</button>
                  : <button className="btn-success" onClick={saveChar}>保存角色</button>}
              </div>
            </div>
          </div>
        )}

        {view === "monsters" && <div className="creator-container anime-slide-up"><div className="manager-layout"><div className="panel-card"><div className="btn-row" style={{ marginTop: 0, marginBottom: 12 }}><h2 style={{ margin: 0 }}>怪物模板</h2><button className="btn-secondary" onClick={() => setMonsterDraft({ ...EMPTY_MON })}>新建</button></div><div className="timeline-list">{monsters.length === 0 && <p className="empty-text">还没有怪物模板。</p>}{monsters.map((monster) => <button type="button" key={monster.monster_id} className="timeline-item timeline-button" onClick={() => openMonster(monster.monster_id)}><div className="timeline-summary">{monster.name}</div><div className="timeline-content">{formatMonsterSummary(monster)}</div></button>)}</div></div><div className="panel-card"><h2>{monsterDraft.monster_id ? "编辑怪物" : "新建怪物"}</h2><div className="form-group"><label>名称</label><input value={monsterDraft.name} onChange={(e) => setMonsterDraft((p) => ({ ...p, name: e.target.value }))} /></div><div className="dual-grid"><div className="form-group"><label>体型</label><input value={monsterDraft.size} onChange={(e) => setMonsterDraft((p) => ({ ...p, size: e.target.value }))} placeholder={localizeSize(monsterDraft.size)} /></div><div className="form-group"><label>类型</label><input value={monsterDraft.creature_type} onChange={(e) => setMonsterDraft((p) => ({ ...p, creature_type: e.target.value }))} placeholder={localizeCreatureType(monsterDraft.creature_type)} /></div><div className="form-group"><label>阵营</label><input value={monsterDraft.alignment} onChange={(e) => setMonsterDraft((p) => ({ ...p, alignment: e.target.value }))} placeholder={localizeAlignment(monsterDraft.alignment)} /></div><div className="form-group"><label>挑战等级</label><input value={monsterDraft.challenge_rating} onChange={(e) => setMonsterDraft((p) => ({ ...p, challenge_rating: e.target.value }))} /></div><div className="form-group"><label>护甲等级</label><input type="number" value={monsterDraft.ac} onChange={(e) => setMonsterDraft((p) => ({ ...p, ac: Number.parseInt(e.target.value || "0", 10) }))} /></div><div className="form-group"><label>生命值</label><input type="number" value={monsterDraft.hp_max} onChange={(e) => setMonsterDraft((p) => ({ ...p, hp_max: Number.parseInt(e.target.value || "0", 10) }))} /></div></div><div className="form-group"><label>特性</label><textarea className="text-block" value={monsterDraft.traitsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, traitsText: e.target.value }))} /></div><div className="form-group"><label>动作</label><textarea className="text-block" value={monsterDraft.actionsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, actionsText: e.target.value }))} /></div><div className="form-group"><label>备注</label><textarea className="text-block" value={monsterDraft.notes} onChange={(e) => setMonsterDraft((p) => ({ ...p, notes: e.target.value }))} /></div><div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>返回</button><button className="btn-success" onClick={saveMonster} disabled={!monsterDraft.name.trim()}>保存怪物</button></div></div></div></div>}

        {view === "new_game" && <div className="modal-overlay"><div className="modal-content anime-pop"><h2>新建游戏</h2><p className="info-text">为这次冒险取一个存档名，然后选择要同行的角色。</p><input className="input-lg" placeholder="例如：黑冢初探" value={newGameId} onChange={(e) => setNewGameId(e.target.value)} /><h3>队伍角色</h3><p className="info-text">已选择 {selectedGameChars.length} 名角色。被选中的角色会加入本局队伍。</p>{characters.length === 0 ? <div className="timeline-item"><div className="timeline-summary">还没有可用角色</div><div className="timeline-content">请先到“角色构筑”里保存至少一名角色，再回来建局。</div></div> : <div className="char-select-list">{characters.map((character) => <button type="button" key={character.character_id} className={`char-option ${selectedGameChars.includes(character.character_id) ? "selected" : ""}`} aria-pressed={selectedGameChars.includes(character.character_id)} onClick={() => setSelectedGameChars((prev) => prev.includes(character.character_id) ? prev.filter((item) => item !== character.character_id) : [...prev, character.character_id])}><div className="avatar">角</div><span>{character.name} · {character.class_name_display || localizeClassName(character.class_name)}</span></button>)}</div>}<div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>取消</button><button className="btn-primary" onClick={makeGame}>创建并进入</button></div></div></div>}

        {view === "chat" && (
          <div className="chat-layout">
            <div className="chat-header">
              <div>
                <strong>{gameState?.title || activeGameId}</strong>
                <div className="subtitle-inline">场景：{localizeScene(gameState?.scene || "setup")} · 回合：{gameState?.turn_number ?? 0}</div>
              </div>
            </div>
            <div className="session-content">
              <div className="chat-window">
                {gameState?.campaign?.phase === "adventure_selection" && (
                  <div className="panel-card">
                    <h3>选择冒险</h3>
                    <div className="timeline-list">
                      {(gameState?.campaign?.available_adventures || []).map((hook) => {
                        const isAiGeneratedAdventure = hook.adventure_id === AI_GENERATED_ADVENTURE_ID;
                        const isPendingAdventure = pendingAdventureId === hook.adventure_id;
                        return (
                          <div key={hook.adventure_id} className="timeline-item">
                            <div className="timeline-summary">{hook.title}</div>
                            <div className="timeline-content">{hook.summary}</div>
                            <div className="btn-row" style={{ marginTop: 12 }}>
                              <button className="btn-primary" onClick={() => chooseAdventure(hook.adventure_id)} disabled={isGameMutationBusy || localActionsLocked}>
                                {isPendingAdventure && isAiGeneratedAdventure
                                  ? "主持人构思中..."
                                  : isPendingAdventure
                                    ? "准备中..."
                                    : isAiGeneratedAdventure
                                      ? "生成并开始"
                                      : `选择：${hook.title}`}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {visibleMessages.map((message, index) => {
                  const previousMessage = visibleMessages[index - 1];
                  const canRetryDmMessage = message.sender === "dm"
                    && !message.pendingContext
                    && previousMessage?.sender === "player"
                    && Number.isInteger(message.index);
                  const isFailedDmMessage = canRetryDmMessage && message.turnStatus === "failed";
                  return (
                    <div key={message.renderKey || `${message.sender}-${message.index ?? index}`} className={`message-stack ${message.sender}`}>
                      {message.sender === "dm" && <RollLedger records={message.rollRecords} recorded={message.rollRecordsRecorded} />}
                      <div className={`message ${message.sender} anime-pop`}>
                        <div className="avatar">{message.sender === "dm" ? "主" : message.sender === "system" ? "系" : "玩"}</div>
                        <div className="bubble markdown-body">
                          <MarkdownBlock highlightQuotes highlightNarrativeRolls={message.sender === "dm"}>{message.text}</MarkdownBlock>
                        </div>
                      </div>
                      {message.optimistic ? (
                        <div className={`message-delivery-status ${message.deliveryState}`} role="status" aria-live="polite">
                          {message.deliveryState === "failed"
                            ? "发送失败，内容已放回输入框，可再次发送。"
                            : message.deliveryLabel || "发送中…"}
                        </div>
                      ) : !message.pendingContext ? (
                        <div className={`message-actions ${isFailedDmMessage ? "failed-turn-actions" : ""}`} aria-label="消息操作">
                          {canRetryDmMessage && (
                            <button
                              type="button"
                              className="retry-message-button"
                              onClick={() => retryDmMessage(message)}
                              disabled={isGameMutationBusy || Boolean(rewriteTarget)}
                            >
                              {retryingMessageIndex === message.index ? "正在重试…" : isFailedDmMessage ? "重试本回合" : "重试"}
                            </button>
                          )}
                          <button type="button" className="delete-message-button" onClick={() => deleteMessageFromHere(message)} disabled={isGameMutationBusy}>
                            删除
                          </button>
                          {message.sender === "player" && (
                            <button type="button" onClick={() => startRewriteFromMessage(message)} disabled={isGameMutationBusy}>
                              修改并重写
                            </button>
                          )}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
                {isPlayerChoicePending && (
                  <div className="pending-turn-card">
                    {dmThinking.status === "idle" && pendingTurn.roll_records?.length > 0 && <RollLedger records={pendingTurn.roll_records} />}
                    <div className="pending-turn-title">轮到你选择</div>
                    <div className="pending-turn-prompt">{pendingTurn.prompt || "DM 正在等待你决定接下来的方向。"}</div>
                    <div className="pending-turn-actions">
                      <button className="btn-text" onClick={() => respondToPendingTurn("暂不决定")} disabled={isGameMutationBusy}>暂不决定</button>
                      {playerChoiceOptions.map((option) => (
                        <button key={option} className="btn-primary" onClick={() => respondToPendingTurn(option)} disabled={isGameMutationBusy}>{option}</button>
                      ))}
                    </div>
                  </div>
                )}
                {isLegacyConfirmationPending && (
                  <div className="pending-turn-card">
                    <div className="pending-turn-title">需要重新描述行动</div>
                    <div className="pending-turn-prompt">这个暂停来自旧版交互策略，其中的暂存变化不会提交。清理后即可重新描述你的决定。</div>
                    <div className="pending-turn-actions">
                      <button className="btn-primary" onClick={() => respondToPendingTurn("清理旧暂停")} disabled={isGameMutationBusy}>清理并返回</button>
                    </div>
                  </div>
                )}
                {(isLoading || ["waiting", "error"].includes(dmThinking.status)) && dmThinking.status !== "idle" && <RollLedger records={dmThinking.rollRecords} />}
                <DmThinkingPanel
                  thinking={dmThinking}
                  onToggle={() => setDmThinking((current) => ({ ...current, expanded: !current.expanded }))}
                />
                {SHOW_WORKFLOW_TRACE_IN_PLAYER_SESSION && workflowEvents.length > 0 && (
                  <div className="workflow-trace">
                    {workflowEvents.map((event, index) => {
                      const metadataLine = compactWorkflowMetadata(event?.metadata || {});
                      return (
                        <div key={`${event?.node_name || "node"}-${index}`} className={`workflow-event workflow-${event?.status || "completed"}`}>
                          <div className="workflow-event-header">
                            <span className="workflow-event-title">{workflowNodeLabel(event?.node_name)}</span>
                            <span className="workflow-event-status">{workflowStatusLabel(event?.status)}</span>
                          </div>
                          {event?.summary && <div className="workflow-event-summary">{event.summary}</div>}
                          {metadataLine && <div className="workflow-event-meta">{metadataLine}</div>}
                        </div>
                      );
                    })}
                  </div>
                )}
                {isLoading && dmThinking.status === "idle" && (
                  <div className="loading-indicator">
                    {pendingAdventureId === AI_GENERATED_ADVENTURE_ID
                      ? "主持人正在构思冒险..."
                      : gameState?.campaign?.phase === "adventure_selection"
                        ? "主持人正在准备冒险..."
                        : "主持人思考中..."}
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
              <div className="session-sidepanel">
                {SHOW_DM_CONTROLS_IN_PLAYER_SESSION && (
                  <fieldset className="pending-action-scope" disabled={localActionsLocked} aria-label="本地游戏操作">
                    {localActionsLocked && <p className="info-text" role="status">{localActionBlockMessage}</p>}
                    <div className="panel-card">
                  <h3>遭遇设置</h3>
                  <div className="timeline-list">
                    {encounterSummary.active && <button className="btn-danger" onClick={finishEncounter}>结束遭遇</button>}
                    <div className="form-group">
                      <label>按名称快速开战</label>
                      <textarea className="text-block" value={encounterDraft.enemy_names} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_names: e.target.value }))} placeholder={"地精\\n强盗队长"} />
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>敌方生命</label>
                        <input type="number" value={encounterDraft.enemy_hp} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_hp: e.target.value }))} />
                      </div>
                      <div className="form-group">
                        <label>敌方护甲</label>
                        <input type="number" value={encounterDraft.enemy_ac} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_ac: e.target.value }))} />
                      </div>
                    </div>
                    <button className="btn-secondary" onClick={createEncounterFromNames}>创建命名遭遇</button>
                    {SHOW_DM_ENCOUNTER_TEMPLATE_TOOLS && (
                      <>
                        <div className="form-group">
                          <label>从怪物模板生成</label>
                          <select value={encounterDraft.monster_id} onChange={(e) => setEncounterDraft((p) => ({ ...p, monster_id: e.target.value }))}>
                            <option value="">选择怪物模板</option>
                            {monsters.map((monster) => <option key={monster.monster_id} value={monster.monster_id}>{monster.name} · 挑战等级 {monster.challenge_rating}</option>)}
                          </select>
                        </div>
                        <div className="dual-grid">
                          <div className="form-group">
                            <label>数量</label>
                            <input type="number" value={encounterDraft.quantity} onChange={(e) => setEncounterDraft((p) => ({ ...p, quantity: e.target.value }))} />
                          </div>
                          <div className="form-group">
                            <label>自定义名称</label>
                            <input value={encounterDraft.custom_name} onChange={(e) => setEncounterDraft((p) => ({ ...p, custom_name: e.target.value }))} placeholder="可选" />
                          </div>
                        </div>
                        <div className="dual-grid">
                          <div className="form-group">
                            <label>阵营</label>
                            <select value={encounterDraft.template_side} onChange={(e) => setEncounterDraft((p) => ({ ...p, template_side: e.target.value }))}>
                              <option value="enemy">敌方</option>
                              <option value="party">队伍</option>
                              <option value="ally">友方</option>
                            </select>
                          </div>
                          <div className="form-group">
                            <label>生命值覆盖</label>
                            <input value={encounterDraft.hp_override} onChange={(e) => setEncounterDraft((p) => ({ ...p, hp_override: e.target.value }))} placeholder="可选" />
                          </div>
                        </div>
                        {encounterMonsterPreview && <div className="timeline-item"><div className="timeline-summary">{encounterMonsterPreview.name}</div><div className="timeline-content">{formatMonsterPreviewLine(encounterMonsterPreview)}</div></div>}
                        <button className="btn-secondary" onClick={createEncounterFromTemplate}>生成模板遭遇</button>
                      </>
                    )}
                    <div className="section-divider" style={{ margin: "8px 0" }} />
                    <div className="form-group">
                      <label>快速添加敌人</label>
                      <input value={encounterDraft.quick_enemy_name} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_name: e.target.value }))} placeholder="敌人名称" />
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>生命值</label>
                        <input type="number" value={encounterDraft.quick_enemy_hp} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_hp: e.target.value }))} />
                      </div>
                      <div className="form-group">
                        <label>护甲等级</label>
                        <input type="number" value={encounterDraft.quick_enemy_ac} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_ac: e.target.value }))} />
                      </div>
                    </div>
                    <div className="form-group">
                      <label>先攻加值</label>
                      <input type="number" value={encounterDraft.quick_enemy_initiative_bonus} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_initiative_bonus: e.target.value }))} />
                    </div>
                    <div className="form-group">
                      <label>快速敌人阵营</label>
                      <select value={encounterDraft.quick_enemy_side} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_side: e.target.value }))}>
                        <option value="enemy">敌方</option>
                        <option value="party">队伍</option>
                        <option value="ally">友方</option>
                      </select>
                    </div>
                    <button className="btn-secondary" onClick={addQuickEnemy}>加入当前遭遇</button>
                  </div>
                </div>
                <div className="panel-card">
                  <h3>战斗动作</h3>
                  <div className="timeline-list">
                    <div className="timeline-item">
                      <div className="timeline-summary">当前行动者</div>
                      <div className="timeline-content">
                        {encounterSummary.active ? `${encounterSummary.current_actor_name || "未知"}（${localizeSide(encounterSummary.current_actor_side || "")}）` : "当前没有激活遭遇。"}
                      </div>
                      {encounterSummary.active && currentActorEntry?.type === "character" && currentActorEntry?.resources && Object.keys(currentActorEntry.resources).length > 0 && (
                        <div className="timeline-content">
                          {Object.entries(currentActorEntry.resources).map(([name, resource]) => `${name} ${resource.current_value}/${resource.max_value}`).join(" · ")}
                        </div>
                      )}
                      {encounterSummary.active && currentActorEntry?.attacks?.length > 0 && (
                        <div className="timeline-content">
                          可用攻击：{currentActorEntry.attacks.map((attack) => localizeName(attack)).join(" · ")}
                        </div>
                      )}
                      {encounterSummary.active && currentActorEntry?.side === "enemy" && (
                        <div className="timeline-content">
                          敌方回合仍由主持人裁定，当前界面只负责约束回合顺序与资源合法性。
                        </div>
                      )}
                    </div>
                    <button className="btn-secondary" onClick={handleCurrentActorAttackLoad} disabled={!currentActorEntry}>载入当前行动者</button>
                    <button className="btn-primary" onClick={() => runAction("advance")} disabled={advanceTurnDisabled}>推进回合</button>
                    <div className="action-grid">
                      <select value={actionDraft.attack.attacker_ref} onChange={(e) => handleAttackActorChange(e.target.value)}>
                        <option value="">攻击者</option>
                        {actorList.map((actor) => <option key={`atk-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.attack.attack_name} onChange={(e) => handleAttackOptionChange(e.target.value)} disabled={!actionDraft.attack.attacker_ref || attackChoices.length === 0}>
                        <option value="">{actionDraft.attack.attacker_ref ? "攻击方式" : "请先选择攻击者"}</option>
                        {attackChoices.map((attack) => <option key={`${actionDraft.attack.attacker_ref}-${attack.name}`} value={attack.name}>{formatAttackOption(attack)}</option>)}
                      </select>
                      <select value={actionDraft.attack.target_ref} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, target_ref: e.target.value } }))}>
                        <option value="">目标</option>
                        {actorList.map((actor) => <option key={`tgt-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <input value={actionDraft.attack.attack_bonus} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, attack_bonus: e.target.value } }))} placeholder="攻击加值" readOnly={attackMetadataLocked} />
                      <input value={actionDraft.attack.damage_expression} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, damage_expression: e.target.value } }))} placeholder="伤害表达式" readOnly={attackMetadataLocked} />
                      <input value={actionDraft.attack.damage_type} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, damage_type: e.target.value } }))} placeholder="伤害类型" readOnly={attackMetadataLocked} />
                      <select value={actionDraft.attack.resolution_mode} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, resolution_mode: e.target.value } }))}>
                        {ATTACK_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                      <button className="btn-secondary" onClick={() => runAction("attack")} disabled={attackButtonDisabled}>执行攻击</button>
                    </div>
                    {attackTurnLocked && <div className="timeline-content">当前不是该单位的回合，攻击已锁定。</div>}
                    {attackMetadataLocked && <div className="timeline-content">当前攻击数据来自 {formatAttackSource(attackChoices.find((attack) => attack.name === actionDraft.attack.attack_name)?.source)}，但你仍可切换普通伤害、非致命或俘获模式。</div>}
                    {attackActor && attackChoices.length === 0 && <div className="timeline-content">该单位还没有记录攻击动作。你可以填写本次攻击。</div>}
                    <div className="action-grid">
                      <select value={actionDraft.spell.caster_ref} onChange={(e) => handleSpellCasterChange(e.target.value)}>
                        <option value="">施法者</option>
                        {charActors.map((actor) => <option key={`spell-${actor.ref}`} value={actor.ref}>{actor.name}</option>)}
                      </select>
                      <select value={actionDraft.spell.spell_name} onChange={(e) => handleSpellOptionChange(e.target.value)}>
                        <option value="">法术</option>
                        {spellOptions.map((spell) => <option key={spell.name} value={spell.name}>{spell.label}</option>)}
                      </select>
                      <input value={actionDraft.spell.slot_level} onChange={(e) => setActionDraft((p) => ({ ...p, spell: { ...p.spell, slot_level: e.target.value } }))} placeholder="法术位" disabled={!selectedSpellOption?.requires_slot} />
                      {selectedSpellOption?.requires_attack_target && <select aria-label="法术攻击目标" value={actionDraft.spell.target_ref || ""} onChange={(e) => setActionDraft((p) => ({ ...p, spell: { ...p.spell, target_ref: e.target.value } }))}>
                        <option value="">法术攻击目标</option>
                        {actorList.map((actor) => <option key={`spell-target-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>}
                      {(selectedSpellOption?.damage_types || []).length > 1 && <select aria-label="法术伤害类型" value={actionDraft.spell.damage_type || ""} onChange={(e) => setActionDraft((p) => ({ ...p, spell: { ...p.spell, damage_type: e.target.value } }))}>
                        <option value="">伤害类型</option>
                        {selectedSpellOption.damage_types.map((type) => <option key={type} value={type}>{selectedSpellOption.damage_type_labels?.[type] || type}</option>)}
                      </select>}
                      <button className="btn-secondary" onClick={() => runAction("spell")} disabled={castButtonDisabled}>执行施法</button>
                    </div>
                    {spellTurnLocked && <div className="timeline-content">当前不是该角色的回合，施法已锁定。</div>}
                    {selectedSpellOption && !selectedSpellOption.available && selectedSpellOption.requires_slot && <div className="timeline-content">{selectedSpellOption.name} 已经没有可用法术位。</div>}
                    <div className="action-grid">
                      <select value={actionDraft.skill.actor_ref} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, actor_ref: e.target.value } }))}>
                        <option value="">检定者</option>
                        {actorList.map((actor) => <option key={`skill-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.skill.skill_name} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, skill_name: e.target.value } }))}>
                        <option value="">技能</option>
                        {(skillActor?.skills || []).map((skill) => <option key={skill} value={skill}>{localizeSkill(skill)}</option>)}
                      </select>
                      <input value={actionDraft.skill.dc} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, dc: e.target.value } }))} placeholder="难度值" />
                      <button className="btn-secondary" onClick={() => runAction("skill")} disabled={!actionDraft.skill.actor_ref || !actionDraft.skill.skill_name || skillTurnLocked}>执行技能检定</button>
                    </div>
                    {skillTurnLocked && <div className="timeline-content">当前不是该单位的回合，技能检定已锁定。</div>}
                    <div className="action-grid">
                      <select value={actionDraft.save.target_ref} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, target_ref: e.target.value } }))}>
                        <option value="">目标</option>
                        {actorList.map((actor) => <option key={`save-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.save.save_name} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, save_name: e.target.value } }))}>
                        <option value="">豁免</option>
                        {(saveTargetActor?.saves || []).map((saveName) => <option key={saveName} value={saveName}>{localizeStat(saveName)}</option>)}
                      </select>
                      <input value={actionDraft.save.dc} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, dc: e.target.value } }))} placeholder="难度值" />
                      <button className="btn-secondary" onClick={() => runAction("save")} disabled={!actionDraft.save.target_ref || !actionDraft.save.save_name}>执行豁免</button>
                    </div>
                    <div className="action-grid">
                      <select value={actionDraft.item.user_ref} onChange={(e) => handleItemUserChange(e.target.value)}>
                        <option value="">使用者</option>
                        {charActors.map((actor) => <option key={`item-${actor.ref}`} value={actor.ref}>{actor.name}</option>)}
                      </select>
                      <select value={actionDraft.item.item_name} onChange={(e) => setActionDraft((p) => ({ ...p, item: { ...p.item, item_name: e.target.value } }))}>
                        <option value="">物品</option>
                        {(itemActor?.items || []).map((item) => <option key={item.name} value={item.name}>{`${item.name} (${item.quantity})`}</option>)}
                      </select>
                      <input value={actionDraft.item.quantity} onChange={(e) => setActionDraft((p) => ({ ...p, item: { ...p.item, quantity: e.target.value } }))} placeholder="数量" />
                      <button className="btn-secondary" onClick={() => runAction("item")} disabled={useItemDisabled}>使用物品</button>
                    </div>
                    {itemTurnLocked && <div className="timeline-content">当前不是该角色的回合，物品使用已锁定。</div>}
                    {selectedItemOption && Number(actionDraft.item.quantity || 1) > Number(selectedItemOption.quantity || 0) && <div className="timeline-content">{selectedItemOption.name} 的剩余数量不足。</div>}
                  </div>
                </div>
                  </fieldset>
                )}
                <section className="side-section party-panel">
                  <div className="side-section-header">
                    <h3>队伍状态</h3>
                    <span>{partyCharacters.length} 人</span>
                  </div>
                  {partyCharacters.length === 0 ? (
                    <p className="empty-text">当前队伍还没有角色。</p>
                  ) : (
                    <div className="party-list">
                      {partyCharacters.map((character) => (
                        <CharacterStatusCard
                          key={character.character_id}
                          character={character}
                          actor={characterActorById[character.character_id]}
                          encounter={encounter}
                          primary={character.character_id === activeCharacterId}
                        />
                      ))}
                    </div>
                  )}
                </section>
                <CombatantPanel
                  encounter={encounter}
                  combatants={combatants}
                  initiativeDrafts={initiativeDrafts}
                  setInitiativeDrafts={setInitiativeDrafts}
                  saveEncounterInitiative={saveEncounterInitiative}
                  rerollEncounterInitiative={rerollEncounterInitiative}
                  dropEncounterCombatant={dropEncounterCombatant}
                  localActionsLocked={localActionsLocked}
                />
              </div>
            </div>
            {isActionSuggestionsLoading && playerDecisionAvailable && (
              <div className="action-suggestions-loading" role="status" aria-live="polite">
                <span className="action-suggestions-loading-mark" aria-hidden="true" />
                <span>正在准备行动灵感</span>
              </div>
            )}
            {visibleActionSuggestions.length > 0 && (
              <div className="action-suggestions" aria-label="行动建议">
                {visibleActionSuggestions.map((suggestion, index) => (
                  <button
                    key={`${suggestion.label}-${index}`}
                    type="button"
                    className="action-suggestion"
                    onClick={() => fillActionSuggestion(suggestion)}
                    disabled={chatSubmitDisabled}
                  >
                    <span>{suggestion.label}</span>
                    <small>{suggestion.action}</small>
                  </button>
                ))}
              </div>
            )}
            {rewriteTarget && (
              <div className="rewrite-bar">
                <span>正在从第 {rewriteTarget.index + 1} 条玩家消息重写</span>
                <button type="button" onClick={cancelRewrite} disabled={isLoading}>取消</button>
              </div>
            )}
            {llmHealth && !llmHealth.ready && (
              <div className="chat-model-warning" role="status">
                {llmHealthMessage} 返回主页检查“模型设置”后再继续游戏。
              </div>
            )}
            <details className="chat-control-menu">
              <summary>
                <span>主持文本</span>
                <small>{replyLengthSummary()}</small>
              </summary>
              {localActionsLocked && <p className="info-text" role="status">{localActionBlockMessage}</p>}
              <div className="chat-control-grid">
                <label>
                  <span>最少字数</span>
                  <input
                    type="number"
                    min="0"
                    max="3000"
                    inputMode="numeric"
                    value={replyLengthDraft.min_chars}
                    onChange={(e) => setReplyLengthDraft((prev) => ({ ...prev, min_chars: e.target.value }))}
                    placeholder="不限"
                    disabled={isLoading || isReplyLengthSaving || localActionsLocked}
                  />
                </label>
                <label>
                  <span>最多字数</span>
                  <input
                    type="number"
                    min="0"
                    max="4000"
                    inputMode="numeric"
                    value={replyLengthDraft.max_chars}
                    onChange={(e) => setReplyLengthDraft((prev) => ({ ...prev, max_chars: e.target.value }))}
                    placeholder="不限"
                    disabled={isLoading || isReplyLengthSaving || localActionsLocked}
                  />
                </label>
                <button type="button" className="btn-secondary" onClick={saveReplyLengthSettings} disabled={isReplyLengthSaving || isLoading || !activeGameId || localActionsLocked}>
                  {isReplyLengthSaving ? "保存中..." : "应用"}
                </button>
              </div>
              {replyLengthMessage && <div className="chat-control-note">{replyLengthMessage}</div>}
            </details>
            <div className="input-area">
              <textarea ref={chatInputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder={gameState?.campaign?.phase === "adventure_selection" ? "请先选择冒险。" : isPlayerChoicePending ? "可点击上方选项，也可以输入你自己的决定。" : rewriteTarget ? "修改这条行动，然后从这里重新开始..." : isLoading ? "可以先写下下一步行动..." : "描述你的行动..."} disabled={chatComposerDisabled} />
              <button onClick={sendMessage} disabled={chatSubmitDisabled || llmAuthorizationFailed || !input.trim()}>{rewriteTarget ? "重写" : "发送"}</button>
            </div>
          </div>
        )}


        {view === "status" && (
          <div className="status-screen anime-fade-in">
            <div className="status-layout">
              <TimelinePanel timeline={timeline} title="时间线" emptyText="这局游戏还没有时间线记录。" />
              <div className="status-side-stack">
                <EvidencePanel evidence={evidenceRecords} />
                <CombatantPanel
                  encounter={encounter}
                  combatants={combatants}
                  initiativeDrafts={initiativeDrafts}
                  setInitiativeDrafts={setInitiativeDrafts}
                  saveEncounterInitiative={saveEncounterInitiative}
                  rerollEncounterInitiative={rerollEncounterInitiative}
                  dropEncounterCombatant={dropEncounterCombatant}
                />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
