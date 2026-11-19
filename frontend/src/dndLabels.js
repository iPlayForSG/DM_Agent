export const STATS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];

export function formatLlmHealthMessage(health) {
  if (!health || health.ready) return "";
  if (health.reason === "cli_not_found") return "模型连接失败：未找到所选 Coding Agent CLI，请检查命令或 PATH。";
  if (health.reason === "cli_probe_failed") return "模型连接失败：CLI 无法正常启动，请检查本机安装。";
  if (!health.configured) return "模型档案尚未完整配置，请补全 Base URL、模型名称和 API Key。";
  if (Number(health.status_code) === 401) return "模型连接失败：API Key 无效或已被服务拒绝。";
  if (health.status_code) return `模型连接失败（HTTP ${health.status_code}），请检查服务地址和模型档案。`;
  return "暂时无法验证模型连接，请检查模型服务是否可访问。";
}

export const MODEL_PROVIDER_LABELS = {
  "openai-compatible": "API（OpenAI-compatible）",
  "claude-code": "Claude Code CLI",
  "codex-cli": "Codex CLI",
};

export const CODEX_DEFAULT_MODEL = "gpt-5.6-terra";
export const CODEX_DEFAULT_REASONING_EFFORT = "high";
export const CODEX_REASONING_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"];

export const EMPTY_LLM_DRAFT = {
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

export const STAT_LABELS = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};

export const STAT_SHORT_LABELS = {
  strength: "STR",
  dexterity: "DEX",
  constitution: "CON",
  intelligence: "INT",
  wisdom: "WIS",
  charisma: "CHA",
};

export const SKILL_LABELS = {
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

export const SIDE_LABELS = { party: "队伍", enemy: "敌方", ally: "友方" };
export const AI_GENERATED_ADVENTURE_ID = "adv-ai-generated";

export const CLASS_RESOURCE_NAME_LABELS = {
  "Wild Shape": "野性变身",
  "Second Wind": "二次呼吸",
  "Lay on Hands": "圣疗之手",
  "Channel Divinity": "引导神力",
  "Rage": "狂暴",
  "Sorcery Points": "法术点",
  "Ki Points": "气力点",
  "Bardic Inspiration": "吟游激励",
};

export const CLASS_NAME_LABELS = {
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

export const SPECIES_NAME_LABELS = {
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

export const BACKGROUND_NAME_LABELS = {
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

export const ORIGIN_FEAT_LABELS = {
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

export const STAT_ABBREVIATION_TO_KEY = {
  str: "strength",
  dex: "dexterity",
  con: "constitution",
  int: "intelligence",
  wis: "wisdom",
  cha: "charisma",
};

export const SCENE_LABELS = {
  adventure_selection: "冒险选择",
  setup: "准备",
  preparation: "准备",
  exploration: "探索",
  social: "社交",
  combat: "战斗",
  encounter: "遭遇",
};

export const SIZE_LABELS = {
  tiny: "微型",
  small: "小型",
  medium: "中型",
  large: "大型",
  huge: "超大型",
  gargantuan: "巨型",
};

export const CREATURE_TYPE_LABELS = {
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

export const ALIGNMENT_LABELS = {
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

export const ATTACK_RESOLUTION_OPTIONS = [
  { value: "normal", label: "普通伤害" },
  { value: "nonlethal", label: "非致命" },
  { value: "capture", label: "俘获" },
];

export const POINT_BUY_COSTS = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
export const DEFAULT_STATS = { strength: 15, dexterity: 14, constitution: 13, intelligence: 12, wisdom: 10, charisma: 8 };

export const ABILITY_METHOD_LABELS = {
  point_buy: "27 点购点",
  standard_array: "标准数组",
  rolled: "4d6 去最低",
};

export const DEFEAT_STATE_LABELS = {
  active: "正常",
  unconscious: "昏迷",
  captured: "被俘",
  dead: "死亡",
};

export const CLASS_RECOMMENDED_STAT_ORDER = {
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

export const recommendedStatsForClass = (className) => {
  const order = CLASS_RECOMMENDED_STAT_ORDER[className];
  if (!order) return { ...DEFAULT_STATS };
  return Object.fromEntries(order.map((stat, index) => [stat, [15, 14, 13, 12, 10, 8][index]]));
};

export const CREATOR_STEPS = [
  { id: "identity", label: "基础", subtitle: "等级、姓名、种族与出身背景" },
  { id: "build", label: "构筑", subtitle: "职业、六维属性、子职与技能" },
  { id: "equipment", label: "装备", subtitle: "起始套装或金币自购行囊" },
  { id: "spells", label: "法术", subtitle: "职业资源、法术位与法术准备" },
  { id: "review", label: "总览", subtitle: "核对完整角色卡并保存入册" },
];

export const EQUIPMENT_TYPE_LABELS = {
  currency: "货币",
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
  potion: "药水",
  consumable: "消耗品",
  scroll: "卷轴",
};

export const EMPTY_PENDING_ITEM = { name: "", quantity: 1, reserved_cost_gp: 0, notes: "" };

export const EMPTY_CHAR = {
  level: 1,
  subclass_id: "",
  subclass_spell_variant: "",
  bonus_spells: [],
  ability_increases: {},
  expertise_skills: [],
  mystic_arcanum: {},
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

export const EMPTY_MON = {
  monster_id: "",
  name: "",
  size: "中型",
  creature_type: "野兽",
  alignment: "无阵营",
  challenge_rating: "1",
  ac: 10,
  hp_max: 10,
  initiative_bonus: 0,
  speed: 30,
  notes: "",
  traitsText: "",
  actionsText: "",
  reactionsText: "",
  bonusActionsText: "",
};

export const EMPTY_ACTIONS = {
  attack: {
    attacker_ref: "",
    attack_name: "",
    target_ref: "",
    attack_bonus: 0,
    damage_expression: "1d6",
    damage_type: "",
    resolution_mode: "normal",
  },
  spell: { caster_ref: "", spell_name: "", slot_level: 1 },
  skill: { actor_ref: "", skill_name: "", dc: 10, modifier: "" },
  save: { target_ref: "", save_name: "", dc: 10, modifier: "" },
  item: { user_ref: "", item_name: "", quantity: 1 },
};

export const EMPTY_ENCOUNTER_DRAFT = {
  enemy_names: "",
  enemy_hp: 10,
  enemy_ac: 10,
  monster_id: "",
  quantity: 1,
  custom_name: "",
  template_side: "enemy",
  hp_override: "",
  quick_enemy_name: "",
  quick_enemy_hp: 10,
  quick_enemy_ac: 10,
  quick_enemy_initiative_bonus: 0,
  quick_enemy_side: "enemy",
};

export const parseEntries = (text, prefix) =>
  text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean)
    .map((description, i) => ({ name: `${prefix} ${i + 1}`, description }));

export const entriesToText = (entries = []) => entries.map((x) => x.description).join("\n");

export const localizeSceneText = (text = "") =>
  text.replace(
    /\b(adventure_selection|preparation|setup|exploration|social|combat|encounter)\b/g,
    (value) => SCENE_LABELS[value] || value,
  );

export const mapMessages = (history = [], timeline = []) => {
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
      narrativeMode: m.narrative_mode || "story",
      rollRecords: m.roll_records || [],
      rollRecordsRecorded: Boolean(m.roll_records_recorded),
    });
    return items;
  }, []);
};

export const EVENT_LABELS = {
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

export const SHOW_DM_ENCOUNTER_TEMPLATE_TOOLS = false;
export const SHOW_DM_CONTROLS_IN_PLAYER_SESSION = false;
export const SHOW_WORKFLOW_TRACE_IN_PLAYER_SESSION = false;

export const EVENT_SUMMARY_LABELS = {
  "Player action": "玩家行动",
  "DM response": "主持人叙事",
  SCENE_CHANGED: "场景切换",
  CHAPTER_RECORDED: "章节记录",
};

export const eventLabel = (t) => EVENT_LABELS[t] || "记录";

export const eventSummary = (event) => {
  const summary = EVENT_SUMMARY_LABELS[event?.summary] || event?.summary || eventLabel(event?.type);
  return event?.type === "scene_changed" ? localizeSceneText(summary) : summary;
};

export const eventContent = (event) => {
  const content = event?.content || "";
  return event?.type === "scene_changed" ? localizeSceneText(content) : content;
};

export const WORKFLOW_NODE_LABELS = {
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

export const WORKFLOW_STATUS_LABELS = {
  started: "开始",
  completed: "完成",
  skipped: "跳过",
  blocked: "暂停",
  success: "成功",
  noted: "已记录",
  warning: "提醒",
  failed: "失败",
  error: "错误",
};

export const workflowNodeLabel = (nodeName) => WORKFLOW_NODE_LABELS[nodeName] || nodeName || "节点";
export const workflowStatusLabel = (status) => WORKFLOW_STATUS_LABELS[status] || status || "完成";

export const compactWorkflowMetadata = (metadata = {}) => {
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

export const getSpellLevel = (spell) => Number(spell?.level ?? 0);

export const localizeStat = (stat) => {
  if (!stat) return stat;
  const lower = String(stat).trim().toLowerCase();
  const key = STAT_ABBREVIATION_TO_KEY[lower] || lower;
  return STAT_LABELS[key] || stat;
};

export const localizeSkill = (skill) => {
  if (!skill) return skill;
  const key = String(skill).trim().toLowerCase().replace(/[\s-]+/g, "_").replace(/'/g, "");
  return SKILL_LABELS[key] || skill;
};

export const localizeClassResource = (name) => CLASS_RESOURCE_NAME_LABELS[name] || name;

export const localizeClassName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return CLASS_NAME_LABELS[trimmed] || value;
};

export const localizeSpeciesName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return SPECIES_NAME_LABELS[trimmed] || value;
};

export const localizeBackgroundName = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return BACKGROUND_NAME_LABELS[trimmed] || value;
};

export const localizeOriginFeat = (value) => {
  if (!value) return value;
  const trimmed = String(value).trim();
  return ORIGIN_FEAT_LABELS[trimmed] || value;
};

export const localizeSide = (side) => SIDE_LABELS[side] || side || "未知";
export const localizeScene = (scene) => SCENE_LABELS[scene] || scene || "准备";
export const normalizeLookupKey = (value) => String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
export const localizeSize = (size) => SIZE_LABELS[normalizeLookupKey(size)] || size || "未知体型";
export const localizeCreatureType = (type) => CREATURE_TYPE_LABELS[normalizeLookupKey(type)] || type || "未知类型";
export const localizeAlignment = (alignment) => ALIGNMENT_LABELS[normalizeLookupKey(alignment)] || alignment || "未知阵营";
export const localizeName = (entry) => (typeof entry === "string" ? entry : entry?.name_display || entry?.name || "");
export const localizeSpellcastingMode = (mode) =>
  mode === "prepared" ? "预备施法" : mode === "known" ? "已知施法" : mode || "未说明";
export const formatActorLabel = (actor) => (actor.side ? `${actor.name}（${localizeSide(actor.side)}）` : actor.name);
export const localizeEquipmentType = (type) => EQUIPMENT_TYPE_LABELS[type] || type || "物品";
export const localizeDefeatState = (state) => DEFEAT_STATE_LABELS[state] || state || "正常";

export const formatEquipmentLine = (item) => {
  const details = [];
  if (item.type === "currency" || item.quantity > 1) details.push(`数量 ${item.quantity ?? 0}`);
  if (item.type_display || item.type) details.push(item.type_display || localizeEquipmentType(item.type));
  if (item.damage_expression) details.push(`伤害 ${item.damage_expression}`);
  if (item.healing_expression) details.push(`治疗 ${item.healing_expression}`);
  if (item.spell_name) details.push(`${item.spell_level ?? "?"}环 · ${item.spell_name}`);
  if (item.damage_type_display || item.damage_type) details.push(item.damage_type_display || item.damage_type);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  if (item.is_equipped) details.push("已装备");
  return details.join(" · ");
};

export const formatShopItemMeta = (item) => {
  const details = [formatGoldLine(item.cost_gp)];
  if (Number(item.bundle_size || 1) > 1) details.push(`每份 ${item.bundle_size}`);
  if (item.damage_die) details.push(item.damage_die);
  if (item.armor_class_bonus) details.push(`护甲 +${item.armor_class_bonus}`);
  details.push(item.type_display || localizeEquipmentType(item.type));
  return details.join(" · ");
};

export const formatResourceRecovery = (resource) =>
  resource.recovery_display || (resource.recovery === "short_rest" ? "短休" : resource.recovery === "long_rest" ? "长休" : resource.recovery);

export const formatSpellSlotLine = ([level, total]) => `${level}环法术位 · ${total}`;
export const formatGoldLine = (goldGp) => `${Number(goldGp || 0)} 金币`;
export const localizeEquipmentMode = (mode) =>
  mode === "starter_package" ? "标准套装" : mode === "custom_purchase" ? "自定义购买" : "未记录";
export const formatAttackSource = (source) =>
  source === "monster_action" ? "怪物动作" : source === "inventory" ? "装备" : source || "攻击";
export const formatMonsterSummary = (monster) =>
  `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating}`;
export const formatMonsterPreviewLine = (monster) =>
  `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating} · 护甲 ${monster.ac} · 生命 ${monster.hp_max}`;
export const formatCombatantStateLine = (combatant) =>
  `生命 ${combatant.hp_current}/${combatant.hp_max} · 护甲 ${combatant.ac} · 先攻 ${combatant.initiative ?? "?"}`;
export const formatHpBarLabel = (current, max) => `${current}/${max} 生命`;
export const formatSigned = (value) => `${Number(value || 0) >= 0 ? "+" : ""}${Number(value || 0)}`;
export const formatAbilityModifier = (score) => formatSigned(Math.floor((Number(score || 10) - 10) / 2));

export const formatSpellSlotStatus = ([level, slot]) => {
  const total = Number(slot?.total ?? slot ?? 0);
  const used = Number(slot?.used || 0);
  return `${level}环 ${Math.max(0, total - used)}/${total}`;
};

export const formatAttackSummary = (attack) => {
  const details = [];
  if (attack?.attack_bonus !== undefined && attack?.attack_bonus !== null && attack?.attack_bonus !== "") {
    details.push(`命中 ${formatSigned(attack.attack_bonus)}`);
  }
  details.push(attack?.damage_expression || "伤害资料未完整记录");
  if (attack?.damage_type_display || attack?.damage_type) {
    details.push(attack.damage_type_display || attack.damage_type);
  }
  return [localizeName(attack), details.join(" · ")].filter(Boolean).join(" · ");
};

export const choiceClassName = (base, selected, disabled, extra = "") =>
  [base, selected ? "selected" : "", disabled ? "is-disabled" : "", extra].filter(Boolean).join(" ");

export const resolveStarterPreviewItems = (starterOption, starterChoiceIds = {}) => {
  if (!starterOption) return [];
  const resolved = [...(starterOption.items || [])];
  for (const choiceGroup of starterOption.choices || []) {
    const selectedId = starterChoiceIds[choiceGroup.id];
    const selectedOption = (choiceGroup.options || []).find((option) => option.id === selectedId);
    if (selectedOption) resolved.push(...(selectedOption.items || []));
  }
  return resolved;
};

export const asMarkdownQuote = (text) =>
  String(text || "")
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
