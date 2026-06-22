import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  addEncounterEnemy,
  advanceTurn,
  attackAction,
  castSpellAction,
  createGame,
  endEncounter,
  loadActionOptions,
  loadCharacterBuilder,
  loadGame,
  loadLobby,
  loadMonsterTemplate,
  loadSpells,
  saveCharacter,
  saveMonsterTemplate,
  savingThrowAction,
  selectAdventure,
  skillCheckAction,
  removeEncounterCombatant,
  rollEncounterInitiative,
  spawnEncounterTemplate,
  startEncounter,
  setEncounterInitiative,
  streamTurn,
  useItemAction as itemActionRequest,
} from "./api";
import "./index.css";

const STATS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];
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
};
const BACKGROUND_NAME_LABELS = {
  Acolyte: "侍祭",
  Criminal: "罪犯",
  Entertainer: "艺人",
  Farmer: "农夫",
  Sage: "贤者",
  Soldier: "士兵",
  Wayfarer: "浪人",
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
const mapMessages = (history = []) => history.filter((m) => m.kind !== "tool_result").map((m) => ({
  sender: m.role === "assistant" ? "dm" : m.role === "user" ? "player" : "system",
  text: m.role === "system" ? localizeSceneText(m.content) : m.content,
}));
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
  finalize_turn: "收尾",
  rag_completed: "规则检索",
  tool_completed: "工具结果",
  validation_note: "校验备注",
};
const WORKFLOW_STATUS_LABELS = { started: "开始", completed: "完成", skipped: "跳过", blocked: "暂停", success: "成功", noted: "已记录", error: "错误" };
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
  if (metadata.confirmation_status) fields.push(`确认: ${metadata.confirmation_status}`);
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
const localizeName = (entry) => entry?.name_display || entry?.name || "";
const localizeSpellcastingMode = (mode) => mode === "prepared" ? "预备施法" : mode === "known" ? "已知施法" : mode || "未说明";
const formatActorLabel = (actor) => actor.side ? `${actor.name}（${localizeSide(actor.side)}）` : actor.name;
const localizeEquipmentType = (type) => EQUIPMENT_TYPE_LABELS[type] || type || "物品";
const formatEquipmentLine = (item) => {
  const details = [];
  if (item.quantity && item.quantity > 1) details.push(`x${item.quantity}`);
  if (item.type_display || item.type) details.push(item.type_display || item.type);
  if (item.damage_expression) details.push(item.damage_expression);
  if (item.damage_type_display || item.damage_type) details.push(item.damage_type_display || item.damage_type);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  if (item.is_equipped) details.push("已装备");
  return details.join(" · ");
};
const formatShopItemMeta = (item) => {
  const details = [`${Number(item.cost_gp || 0)} gp`];
  if (Number(item.bundle_size || 1) > 1) details.push(`每份 ${item.bundle_size}`);
  if (item.damage_die) details.push(item.damage_die);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  details.push(item.type_display || localizeEquipmentType(item.type));
  return details.join(" · ");
};
const formatResourceRecovery = (resource) => resource.recovery === "short_rest" ? "短休" : resource.recovery === "long_rest" ? "长休" : resource.recovery;
const formatSpellSlotLine = ([level, total]) => `${level}环法术位 · ${total}`;
const formatGoldLine = (goldGp) => `${Number(goldGp || 0)} 金币`;
const formatAttackSource = (source) => source === "monster_action" ? "怪物动作" : source === "inventory" ? "装备" : source || "攻击";
const formatMonsterSummary = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating}`;
const formatMonsterPreviewLine = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating} · 护甲 ${monster.ac} · 生命 ${monster.hp_max}`;
const formatCombatantStateLine = (combatant) => `生命 ${combatant.hp_current}/${combatant.hp_max} · 护甲 ${combatant.ac} · 先攻 ${combatant.initiative ?? "?"}`;
const formatHpBarLabel = (current, max) => `${current}/${max} 生命`;
const choiceClassName = (base, selected, disabled, extra = "") => [base, selected ? "selected" : "", disabled ? "is-disabled" : "", extra].filter(Boolean).join(" ");
function ChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return <button type="button" className={choiceClassName("class-card", selected, disabled, className)} aria-pressed={selected} disabled={disabled} {...props}>{children}</button>;
}
function SpellChoiceButton({ selected = false, disabled = false, className = "", children, ...props }) {
  return <button type="button" className={choiceClassName("spell-card", selected, disabled, className)} aria-pressed={selected} disabled={disabled} {...props}>{children}</button>;
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
  const [workflowEvents, setWorkflowEvents] = useState([]);
  const [input, setInput] = useState(""), [isLoading, setIsLoading] = useState(false), [error, setError] = useState("");
  const [isBuilderLoading, setIsBuilderLoading] = useState(false);
  const [creatorStep, setCreatorStep] = useState(0);
  const messagesEndRef = useRef(null);

  useEffect(() => { refreshLobby(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, workflowEvents, isLoading]);
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
    notes: charDraft.custom_pending_item.notes?.trim() || "由 DM 在角色创建后补充具体属性",
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
  const spellTurnLocked = Boolean(encounterSummary.active && spellActor && !spellActor.is_current_actor);
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
    || (selectedSpellOption.requires_slot && !selectedSpellOption.available_slot_levels.includes(Number(actionDraft.spell.slot_level || 0)));
  const useItemDisabled = !selectedItemOption
    || itemTurnLocked
    || Number(actionDraft.item.quantity || 1) <= 0
    || Number(actionDraft.item.quantity || 1) > Number(selectedItemOption.quantity || 0);
  const pendingTurn = gameState?.pending_turn || null;
  const isToolConfirmationPending = pendingTurn?.kind === "tool_confirmation";
  const chatInputDisabled = gameState?.campaign?.phase === "adventure_selection" || isLoading;

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

  async function refreshLobby() {
    setIsBuilderLoading(true);
    setError("");
    const [lobbyResult, rulesResult] = await Promise.allSettled([loadLobby(), loadCharacterBuilder()]);
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

    setIsBuilderLoading(false);
    if (nextError) setError(nextError);
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

  function applyGameSnapshot(state, options = { actors: [] }) {
    setGameState(state);
    setMessages(mapMessages(state.chat_history || []));
    setActionOptions(options || { actors: [] });
  }

  async function syncGame(gameId, state) {
    applyGameSnapshot(state, await loadActionOptions(gameId));
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
    setActiveGameId(gameId);
    setWorkflowEvents([]);
    setView("chat");
    await syncGame(gameId, await loadGame(gameId));
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
      if (pointBuyRemaining < 0) return "属性购点超出预算，请调低属性。";
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
      if (equipmentRemainingGp < 0) return `装备花费超出预算 ${Math.abs(equipmentRemainingGp)} gp，请减少购买或降低预留预算。`;
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
      setActiveGameId(gameId);
      setWorkflowEvents([]);
      setView("chat");
      applyGameSnapshot(result.game_state, result.action_options);
      setInput("");
      await refreshLobby().catch(() => {});
    } catch (err) { setError(err.message || "创建游戏失败。"); }
  }
  async function chooseAdventure(adventureId) { if (!activeGameId) return; const result = await selectAdventure(activeGameId, adventureId); await syncGame(activeGameId, result.game_state); }
  async function submitChatMessage(rawMessage, options = {}) {
    const message = String(rawMessage || "").trim();
    const gameId = activeGameId;
    if (!message || !gameId || isLoading) return;
    if (gameState?.campaign?.phase === "adventure_selection") return setError("请先选择冒险。");

    setIsLoading(true);
    setError("");
    setWorkflowEvents([]);
    try {
      const pushWorkflowEvent = (event) => {
        setWorkflowEvents((prev) => [...prev.slice(-29), event]);
      };
      const result = await streamTurn(gameId, message, {
        onEvent: (eventName, data) => {
          if (eventName !== "turn.started") return;
          pushWorkflowEvent({
            node_name: "turn_started",
            status: "started",
            summary: data?.mode === "resume" ? "恢复暂停回合" : "启动新回合",
            metadata: { mode: data?.mode, checkpoint_backend: data?.checkpoint_backend },
          });
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
      });
      if (options.clearInput) setInput("");
      await syncGame(gameId, result.game_state);
    } catch (err) {
      setError(err.message || "发送消息失败。");
    } finally {
      setIsLoading(false);
    }
  }

  async function sendMessage() { await submitChatMessage(input, { clearInput: true }); }
  async function respondToPendingTurn(response) { await submitChatMessage(response); }

  async function createEncounterFromNames() {
    if (!activeGameId) return;
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
    if (!activeGameId) return;
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
    if (!activeGameId) return;
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
    if (!activeGameId) return;
    try {
      setError("");
      const result = await endEncounter(activeGameId);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "结束遭遇失败。"); }
  }

  async function dropEncounterCombatant(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await removeEncounterCombatant(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "移除单位失败。"); }
  }

  async function saveEncounterInitiative(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await setEncounterInitiative(activeGameId, combatantRef, Number(initiativeDrafts[combatantRef] || 0));
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "设置先攻失败。"); }
  }

  async function rerollEncounterInitiative(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await rollEncounterInitiative(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "重掷先攻失败。"); }
  }

  async function runAction(kind) {
    if (!activeGameId) return;
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
  const timeline = (gameState?.timeline || []).slice(-12).reverse();

  return (
    <div className="app-container">
      {!["home", "new_game", "creator", "monsters"].includes(view) && (
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">DM</span>
            <span>Agent</span>
          </div>
          <div className="menu-items">
            <div className="menu-active-info">当前游戏：{activeGameId}</div>
            <button onClick={() => setView("chat")} className={view === "chat" ? "active" : ""}>对话</button>
            <button onClick={() => setView("status")} className={view === "status" ? "active" : ""}>状态</button>
            <button className="btn-danger" onClick={() => { setActiveGameId(null); setGameState(null); setMessages([]); setView("home"); }}>返回主页</button>
          </div>
        </aside>
      )}
      <main className="main-content">
        {error && <div className="list-item error-banner" style={{ margin: 16 }}>{error}</div>}

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
                <button type="button" className="bento-card glow-hover" onClick={openCreator}>
                  <div className="card-icon">册</div>
                  <h3>角色卡模板</h3>
                  <p>查看可带入游戏的玩家角色卡。</p>
                </button>
              </div>
            </section>

            <section className="lobby-grid">
              <div className="lobby-panel">
                <div className="panel-heading">
                  <h3>已保存游戏</h3>
                  <span>{games.length} 局</span>
                </div>
                <div className="scroll-list">
                  {games.length === 0 && <p className="empty-text">还没有已保存的游戏。</p>}
                  {games.map((game) => (
                    <button type="button" key={game.game_id} className="list-item" onClick={() => enterGame(game.game_id)}>
                      <span className="icon">骰</span>
                      <span>{game.title}（{localizeScene(game.scene)}）{game.encounter_active ? " · 战斗中" : ""}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="lobby-panel">
                <div className="panel-heading">
                  <h3>角色卡模板</h3>
                  <span>{characters.length} 张</span>
                </div>
                <div className="scroll-list">
                  {characters.length === 0 && <p className="empty-text">还没有角色卡。先创建一张角色卡，再开局。</p>}
                  {characters.slice(0, 8).map((character) => (
                    <button type="button" key={character.character_id} className="list-item" onClick={openCreator}>
                      <span className="icon">角</span>
                      <span>{character.name} · {character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</span>
                    </button>
                  ))}
                </div>
              </div>
            </section>
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
                    <input value={background?.origin_feat_display || localizeOriginFeat(charDraft.origin_feat)} readOnly />
                    <p className="info-text" style={{ marginTop: 8 }}>当前规则目录里，起源专长由所选背景固定决定，不提供自由下拉选择。</p>
                  </div>
                </>
              )}

              {creatorStep === 1 && (
                <>
                  <div className="form-group">
                    <label>职业</label>
                    {builder.classes.length === 0 ? renderBuilderLoadState("职业目录") : <div className="class-grid">
                      {builder.classes.map((cls) => <ChoiceButton key={cls.id} selected={charDraft.class_name === cls.name} onClick={() => chooseClass(cls)}>{cls.name_display || localizeClassName(cls.name)}</ChoiceButton>)}
                    </div>}
                  </div>
                  <div className="builder-preview-grid">
                    <div className="builder-preview-card">
                      <h3>生命上限</h3>
                      <div className="timeline-summary">{computedHpMax}</div>
                      <div className="timeline-content">按职业生命骰和体质调整值自动计算，创建阶段不再手填。</div>
                    </div>
                    <div className="builder-preview-card">
                      <h3>属性购点</h3>
                      <div className="timeline-summary">{pointBuySpent}/{pointBuyRules.budget}</div>
                      <div className="timeline-content">范围 {pointBuyRules.minimum}-{pointBuyRules.maximum}，剩余 {pointBuyRemaining} 点。</div>
                    </div>
                  </div>
                  <div className="stats-editor">
                    {STATS.map((stat) => <div key={stat} className="stat-row"><span className="stat-name">{localizeStat(stat)}</span><button onClick={() => adjustStat(stat, -1)}>-</button><span className="stat-val">{charDraft.stats[stat]}</span><button onClick={() => adjustStat(stat, 1)}>+</button></div>)}
                  </div>
                  <div className="form-group" style={{ marginTop: 24 }}>
                    <label>职业技能</label>
                    {!classDef ? <p className="info-text">先选择职业，才能分配职业技能。</p> : <><p className="spell-meta">需要选择 {classSkillTarget} 项职业技能，当前 {selectedClassSkillCount}/{classSkillTarget}。</p><div className="class-grid">
                      {(classDef?.skill_choices || []).map((skill) => {
                        const providedByBackground = backgroundSkills.has(skill);
                        const selected = Number(charDraft.skill_proficiencies[skill] || 0) > 0;
                        return <ChoiceButton key={skill} selected={selected} disabled={providedByBackground} onClick={() => toggleSkill(skill)}>{localizeSkill(skill)}{providedByBackground && <span className="choice-note">背景已提供</span>}</ChoiceButton>;
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
                        <div key={group.type} className="builder-preview-card shop-section">
                          <h3>{group.items[0]?.type_display || localizeEquipmentType(group.type)}</h3>
                          <div className="timeline-list">
                            {group.items.map((item) => (
                              <div key={item.id} className={`shop-card ${Number(charDraft.custom_purchase_items?.[item.id] || 0) > 0 ? "selected" : ""}`}>
                                <div>
                                  <div className="timeline-summary">{item.name_display || item.name}</div>
                                  <div className="timeline-content">{formatShopItemMeta(item)}</div>
                                </div>
                                <div className="quantity-stepper">
                                  <button type="button" onClick={() => setCustomPurchaseQuantity(item.id, Number(charDraft.custom_purchase_items?.[item.id] || 0) - 1)}>-</button>
                                  <span>{Number(charDraft.custom_purchase_items?.[item.id] || 0)}</span>
                                  <button type="button" onClick={() => setCustomPurchaseQuantity(item.id, Number(charDraft.custom_purchase_items?.[item.id] || 0) + 1)}>+</button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
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
                          <label>预留预算（gp）</label>
                          <input type="number" min="0" value={charDraft.custom_pending_item?.reserved_cost_gp || 0} onChange={(e) => updatePendingCustomItem("reserved_cost_gp", Number.parseInt(e.target.value || "0", 10))} />
                        </div>
                        <div className="form-group">
                          <label>说明</label>
                          <input value={charDraft.custom_pending_item?.notes || ""} onChange={(e) => updatePendingCustomItem("notes", e.target.value)} placeholder="由 DM 决定材质、伤害、特效等" />
                        </div>
                      </div>
                      <p className="info-text">这件装备只记录名称、数量和预算占用，具体属性在角色创建后由 DM 决定。</p>
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
                        {finalEquipmentPreview.map((item, index) => <div key={`${item.name}-${index}`} className="timeline-item"><div className="timeline-summary">{item.name_display || item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || item.type || "装备"}</div>{item.notes && <div className="timeline-content">{item.notes}</div>}</div>)}
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
                      {!classDef ? <p className="info-text">选择职业后即可预览 1 级法术位。</p> : !classDef.spellcasting_ability ? <p className="info-text">当前职业起始时不具备施法能力。</p> : startingSpellSlots.length === 0 ? <div><p className="info-text">该职业有施法元数据，但当前构筑目录里没有 1 级法术位。</p><p className="spell-meta">施法属性：{localizeStat(classDef.spellcasting_ability)} · 方式：{localizeSpellcastingMode(classDef.spellcasting_mode)}</p></div> : <div><p className="spell-meta">施法属性：{localizeStat(classDef.spellcasting_ability)} · 方式：{localizeSpellcastingMode(classDef.spellcasting_mode)}</p><div className="timeline-list">{startingSpellSlots.map((slot) => <div key={slot[0]} className="timeline-item"><div className="timeline-summary">{formatSpellSlotLine(slot)}</div><div className="timeline-content">角色保存时会由后端自动填充。</div></div>)}</div></div>}
                    </div>
                  </div>
                  <div className="form-group">
                    <label>戏法</label>
                    {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasCantripSelection ? <p className="info-text">当前职业在 1 级时不获得戏法。</p> : <div><p className="spell-meta">需要选择 {startingCantripCount} 个戏法。</p><p className="spell-meta">已选 {charDraft.selectedCantrips.length}/{startingCantripCount}</p>{cantripOptions.length === 0 ? <p className="info-text">当前职业没有可用的戏法列表。</p> : <div className="spell-grid">{cantripOptions.map((spell) => <SpellChoiceButton key={spell.id || spell.name} selected={charDraft.selectedCantrips.includes(spell.name)} onClick={() => toggleCantrip(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">戏法 · {spell.school_display || spell.school}</p></SpellChoiceButton>)}</div>}</div>}
                  </div>
                  <div className="form-group">
                    <label>已准备法术</label>
                    {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasLevelOneSpellcasting ? <p className="info-text">当前职业在 1 级时没有可准备的法术位。</p> : <div><p className="spell-meta">需要选择 {startingPreparedSpellCount} 个 1 环及以上法术。</p><p className="spell-meta">已选 {charDraft.selectedSpells.length}/{startingPreparedSpellCount}</p>{levelOnePreparedSpells.length === 0 ? <p className="info-text">当前职业没有可用的 1 环及以上法术列表。</p> : <div className="spell-grid">{levelOnePreparedSpells.map((spell) => <SpellChoiceButton key={spell.id || spell.name} selected={charDraft.selectedSpells.includes(spell.name)} onClick={() => togglePreparedSpell(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">{spell.level} 环 · {spell.school_display || spell.school}</p></SpellChoiceButton>)}</div>}</div>}
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
                    <div className="timeline-content">{STATS.map((stat) => `${localizeStat(stat)} ${charDraft.stats[stat]}`).join(" · ")}</div>
                  </div>
                  <div className="builder-preview-card">
                    <h3>装备</h3>
                    <div className="timeline-summary">{charDraft.equipment_mode === "custom_purchase" ? "自定义购买" : selectedStarterOption?.label_display || selectedStarterOption?.label || "标准套装"}</div>
                    <div className="timeline-content">预算 {formatGoldLine(equipmentBudgetGp)} · 剩余 {formatGoldLine(equipmentRemainingGp)}</div>
                    {finalEquipmentPreview.length === 0 ? <p className="info-text">暂无装备。</p> : <div className="timeline-list">{finalEquipmentPreview.map((item, index) => <div key={`${item.name}-${index}`} className="timeline-item"><div className="timeline-summary">{item.name_display || item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || item.type || "装备"}</div>{item.notes && <div className="timeline-content">{item.notes}</div>}</div>)}</div>}
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
                      {(gameState?.campaign?.available_adventures || []).map((hook) => (
                        <div key={hook.adventure_id} className="timeline-item">
                          <div className="timeline-summary">{hook.title}</div>
                          <div className="timeline-content">{hook.summary}</div>
                          <div className="btn-row" style={{ marginTop: 12 }}>
                            <button className="btn-primary" onClick={() => chooseAdventure(hook.adventure_id)}>选择：{hook.title}</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {isToolConfirmationPending && (
                  <div className="pending-turn-card">
                    <div className="pending-turn-title">需要你确认</div>
                    <div className="pending-turn-prompt">{pendingTurn.prompt || "当前回合需要确认后才能继续。"}</div>
                    <div className="pending-turn-actions">
                      <button className="btn-danger" onClick={() => respondToPendingTurn("取消")} disabled={isLoading}>取消</button>
                      <button className="btn-primary" onClick={() => respondToPendingTurn("确认")} disabled={isLoading}>确认</button>
                    </div>
                  </div>
                )}
                {messages.map((message, index) => (
                  <div key={`${message.sender}-${index}`} className={`message ${message.sender} anime-pop`}>
                    <div className="avatar">{message.sender === "dm" ? "主" : message.sender === "system" ? "系" : "玩"}</div>
                    <div className="bubble">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
                    </div>
                  </div>
                ))}
                {false && workflowEvents.length > 0 && (
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
                {isLoading && <div className="loading-indicator">主持人思考中...</div>}
                <div ref={messagesEndRef} />
              </div>
              <div className="session-sidepanel">
                {SHOW_DM_CONTROLS_IN_PLAYER_SESSION && (
                  <>
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
                    {attackActor && attackChoices.length === 0 && <div className="timeline-content">该单位还没有可解析的攻击选项，已保留手动填写作为兜底。</div>}
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
                  </>
                )}
                <div className="panel-card">
                  <h3>时间线</h3>
                  <div className="timeline-list">
                    {timeline.map((event) => {
                      const content = eventContent(event);
                      return <div key={event.event_id} className="timeline-item"><div className="timeline-type">{eventLabel(event.type)}</div><div className="timeline-summary">{eventSummary(event)}</div>{content && <div className="timeline-content">{content}</div>}</div>;
                    })}
                  </div>
                </div>
                <div className="panel-card">
                  <h3>场上形势</h3>
                  {!encounter ? (
                    <p className="empty-text">当前没有战斗。</p>
                  ) : (
                    <div className="combatant-list">
                      {combatants.map((combatant) => (
                        <div key={combatant.combatant_id} className={`combatant-item ${encounter.current_combatant_id === combatant.combatant_id ? "combatant-active" : ""}`}>
                          <div className="timeline-summary">{combatant.name} · {localizeSide(combatant.side)}</div>
                          <div className="timeline-content">{formatCombatantStateLine(combatant)}</div>
                          {SHOW_DM_CONTROLS_IN_PLAYER_SESSION && (
                            <>
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
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="input-area">
              <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder={gameState?.campaign?.phase === "adventure_selection" ? "请先选择冒险。" : isToolConfirmationPending ? "可直接确认或取消，也可以输入补充说明。" : "描述你的行动..."} disabled={chatInputDisabled} />
              <button onClick={sendMessage} disabled={chatInputDisabled || !input.trim()}>发送</button>
            </div>
          </div>
        )}


        {view === "status" && <div className="status-screen anime-fade-in"><h2>队伍状态</h2><div className="status-cards">{Object.values(gameState?.characters || {}).map((character) => <div key={character.character_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">角</div><div><h3>{character.name}</h3><span className="badge">{character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${character.hp_max > 0 ? (character.hp_current / character.hp_max) * 100 : 0}%` }}></div><span className="text">{formatHpBarLabel(character.hp_current, character.hp_max)}</span></div><div className="timeline-content">财富：{formatGoldLine(character.gold_gp)}</div></div>)}</div><h2 style={{ marginTop: 32 }}>遭遇状态</h2><div className="status-cards">{combatants.length === 0 && <p className="empty-text">当前没有战斗单位。</p>}{combatants.map((combatant) => <div key={combatant.combatant_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">{combatant.side === "enemy" ? "敌" : "角"}</div><div><h3>{combatant.name}</h3><span className="badge">{localizeSide(combatant.side)} · 先攻 {combatant.initiative ?? "?"}</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${combatant.hp_max > 0 ? (combatant.hp_current / combatant.hp_max) * 100 : 0}%` }}></div><span className="text">{formatHpBarLabel(combatant.hp_current, combatant.hp_max)}</span></div></div>)}</div></div>}
      </main>
    </div>
  );
}
