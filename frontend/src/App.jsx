import { useEffect, useRef, useState } from "react";
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
  submitTurn,
  useItemAction,
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
const STAT_ABBREVIATION_TO_KEY = {
  str: "strength",
  dex: "dexterity",
  con: "constitution",
  int: "intelligence",
  wis: "wisdom",
  cha: "charisma",
};
const SCENE_LABELS = { setup: "准备", exploration: "探索", combat: "战斗", encounter: "遭遇" };
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
const EMPTY_CHAR = { name: "", species: "Human", background_name: "", origin_feat: "", class_name: "", starter_option_id: "", starter_choice_ids: {}, hp_max: 10, stats: Object.fromEntries(STATS.map((k) => [k, 10])), skill_proficiencies: {}, selectedCantrips: [], selectedSpells: [] };
const EMPTY_MON = { monster_id: "", name: "", size: "中型", creature_type: "野兽", alignment: "无阵营", challenge_rating: "1", ac: 10, hp_max: 10, initiative_bonus: 0, speed: 30, notes: "", traitsText: "", actionsText: "", reactionsText: "", bonusActionsText: "" };
const EMPTY_ACTIONS = { attack: { attacker_ref: "", attack_name: "", target_ref: "", attack_bonus: 0, damage_expression: "1d6", damage_type: "", resolution_mode: "normal" }, spell: { caster_ref: "", spell_name: "", slot_level: 1 }, skill: { actor_ref: "", skill_name: "", dc: 10, modifier: "" }, save: { target_ref: "", save_name: "", dc: 10, modifier: "" }, item: { user_ref: "", item_name: "", quantity: 1 } };
const EMPTY_ENCOUNTER_DRAFT = { enemy_names: "", enemy_hp: 10, enemy_ac: 10, monster_id: "", quantity: 1, custom_name: "", template_side: "enemy", hp_override: "", quick_enemy_name: "", quick_enemy_hp: 10, quick_enemy_ac: 10, quick_enemy_initiative_bonus: 0, quick_enemy_side: "enemy" };

const parseEntries = (text, prefix) => text.split("\n").map((x) => x.trim()).filter(Boolean).map((description, i) => ({ name: `${prefix} ${i + 1}`, description }));
const entriesToText = (entries = []) => entries.map((x) => x.description).join("\n");
const mapMessages = (history = []) => history.map((m) => ({ sender: m.role === "assistant" ? "dm" : m.role === "user" ? "player" : "system", text: m.content }));
const eventLabel = (t) => ({ player_action: "玩家", assistant_response: "主持", dice_result: "骰点", hp_changed: "生命", attack_resolved: "攻击", skill_check: "技能", saving_throw: "豁免", spell_cast: "施法", item_used: "物品", turn_advanced: "回合", encounter_started: "遭遇", monster_template_saved: "怪物模板", monster_spawned: "怪物生成" }[t] || t);
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
const localizeSide = (side) => SIDE_LABELS[side] || side || "未知";
const localizeScene = (scene) => SCENE_LABELS[scene] || scene || "准备";
const normalizeLookupKey = (value) => String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
const localizeSize = (size) => SIZE_LABELS[normalizeLookupKey(size)] || size || "未知体型";
const localizeCreatureType = (type) => CREATURE_TYPE_LABELS[normalizeLookupKey(type)] || type || "未知类型";
const localizeAlignment = (alignment) => ALIGNMENT_LABELS[normalizeLookupKey(alignment)] || alignment || "未知阵营";
const localizeName = (entry) => entry?.name_display || entry?.name || "";
const localizeSpellcastingMode = (mode) => mode === "prepared" ? "预备施法" : mode === "known" ? "已知施法" : mode || "未说明";
const formatActorLabel = (actor) => actor.side ? `${actor.name}（${localizeSide(actor.side)}）` : actor.name;
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
const formatResourceRecovery = (resource) => resource.recovery === "short_rest" ? "短休" : resource.recovery === "long_rest" ? "长休" : resource.recovery;
const formatSpellSlotLine = ([level, total]) => `${level}环法术位 · ${total}`;
const formatGoldLine = (goldGp) => `${Number(goldGp || 0)} 金币`;
const formatAttackSource = (source) => source === "monster_action" ? "怪物动作" : source === "inventory" ? "装备" : source || "攻击";
const formatMonsterSummary = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating}`;
const formatMonsterPreviewLine = (monster) => `${localizeCreatureType(monster.creature_type)} · 挑战等级 ${monster.challenge_rating} · 护甲 ${monster.ac} · 生命 ${monster.hp_max}`;
const formatCombatantStateLine = (combatant) => `生命 ${combatant.hp_current}/${combatant.hp_max} · 护甲 ${combatant.ac} · 先攻 ${combatant.initiative ?? "?"}`;
const formatHpBarLabel = (current, max) => `${current}/${max} 生命`;
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
  const [builder, setBuilder] = useState({ species: [], backgrounds: [], classes: [] }), [spellList, setSpellList] = useState([]);
  const [charDraft, setCharDraft] = useState({ ...EMPTY_CHAR }), [monsterDraft, setMonsterDraft] = useState({ ...EMPTY_MON });
  const [encounterDraft, setEncounterDraft] = useState({ ...EMPTY_ENCOUNTER_DRAFT });
  const [encounterMonsterPreview, setEncounterMonsterPreview] = useState(null);
  const [initiativeDrafts, setInitiativeDrafts] = useState({});
  const [selectedGameChars, setSelectedGameChars] = useState([]), [newGameId, setNewGameId] = useState("");
  const [activeGameId, setActiveGameId] = useState(null), [gameState, setGameState] = useState(null), [actionOptions, setActionOptions] = useState({ actors: [] });
  const [actionDraft, setActionDraft] = useState({ ...EMPTY_ACTIONS }), [messages, setMessages] = useState([]);
  const [input, setInput] = useState(""), [isLoading, setIsLoading] = useState(false), [error, setError] = useState("");
  const messagesEndRef = useRef(null);

  useEffect(() => { refreshLobby(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
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
  const starterOptions = classDef?.starter_equipment_options || [];
  const selectedStarterOption = starterOptions.find((option) => option.id === charDraft.starter_option_id) || starterOptions[0] || null;
  const starterChoiceGroups = selectedStarterOption?.choices || [];
  const starterChoicesComplete = starterChoiceGroups.every((group) => Boolean(charDraft.starter_choice_ids[group.id]));
  // These previews mirror the builder defaults the backend will auto-fill on save.
  const starterEquipment = resolveStarterPreviewItems(selectedStarterOption, charDraft.starter_choice_ids);
  const starterGoldGp = Number(selectedStarterOption?.gold_gp || 0);
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
  const builderSelectionComplete = starterChoicesComplete && cantripSelectionComplete && spellSelectionComplete;
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

  async function refreshLobby() {
    try {
      setError("");
      const [lobby, rules] = await Promise.all([loadLobby(), loadCharacterBuilder()]);
      setGames(lobby.games || []);
      setCharacters(lobby.characters || []);
      setMonsters(lobby.monsters || []);
      setBuilder({ species: rules.species || [], backgrounds: rules.backgrounds || [], classes: rules.classes || [] });
    } catch (err) { setError(err.message || "加载大厅失败。"); }
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

  async function enterGame(gameId) { setActiveGameId(gameId); setView("chat"); await syncGame(gameId, await loadGame(gameId)); }
  async function chooseClass(c) {
    setError("");
    setCharDraft((p) => ({ ...p, class_name: c.name, starter_option_id: c.starter_equipment_options?.[0]?.id || "", starter_choice_ids: {}, selectedCantrips: [], selectedSpells: [] }));
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
  function chooseBackground(name) { const bg = builder.backgrounds.find((x) => x.name === name); const prof = { ...charDraft.skill_proficiencies }; for (const s of bg?.skill_proficiencies || []) prof[s] = 1; setCharDraft((p) => ({ ...p, background_name: name, origin_feat: bg?.origin_feat || "", skill_proficiencies: prof })); }
  function toggleSkill(skill) { if (backgroundSkills.has(skill)) return; const selected = Number(charDraft.skill_proficiencies[skill] || 0) > 0; const picked = Object.entries(charDraft.skill_proficiencies).filter(([n, v]) => !backgroundSkills.has(n) && Number(v) > 0 && n !== skill); if (!selected && picked.length >= Number(classDef?.skills_to_choose || 0)) return setError(`该职业最多只能额外选择 ${classDef?.skills_to_choose || 0} 个技能。`); setError(""); setCharDraft((p) => ({ ...p, skill_proficiencies: { ...p.skill_proficiencies, [skill]: selected ? 0 : 1 } })); }
  function chooseStarterOption(optionId) { setCharDraft((p) => ({ ...p, starter_option_id: optionId, starter_choice_ids: {} })); }
  function chooseStarterChoice(groupId, optionId) { setCharDraft((p) => ({ ...p, starter_choice_ids: { ...p.starter_choice_ids, [groupId]: optionId } })); }
  function togglePreparedSpell(spellName) {
    if (!hasLevelOneSpellcasting) {
      setError("当前职业在此构筑器中没有 1 环法术准备。");
      return;
    }

    const selected = charDraft.selectedSpells.includes(spellName);
    if (!selected && startingPreparedSpellCount > 0 && charDraft.selectedSpells.length >= startingPreparedSpellCount) {
      setError(`${classDef?.name} 需要准确选择 ${startingPreparedSpellCount} 个 1 环及以上法术。`);
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
      setError("当前职业在此构筑器中不获得戏法。");
      return;
    }

    const selected = charDraft.selectedCantrips.includes(spellName);
    if (!selected && charDraft.selectedCantrips.length >= startingCantripCount) {
      setError(`${classDef?.name} 需要准确选择 ${startingCantripCount} 个戏法。`);
      return;
    }

    setError("");
    setCharDraft((p) => ({
      ...p,
      selectedCantrips: selected ? p.selectedCantrips.filter((x) => x !== spellName) : [...p.selectedCantrips, spellName],
    }));
  }

  async function saveChar() {
    try {
      setError("");
      await saveCharacter({ name: charDraft.name, species: charDraft.species, background_name: charDraft.background_name, origin_feat: charDraft.origin_feat, class_name: charDraft.class_name, starter_option_id: charDraft.starter_option_id, starter_choice_ids: charDraft.starter_choice_ids, hp_current: charDraft.hp_max, hp_max: charDraft.hp_max, stats: charDraft.stats, skill_proficiencies: charDraft.skill_proficiencies, spells: { cantrips: charDraft.selectedCantrips, prepared: charDraft.selectedSpells }, inventory: [] });
      setCharDraft({ ...EMPTY_CHAR }); setSpellList([]); setView("home"); await refreshLobby();
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
      setView("chat");
      applyGameSnapshot(result.game_state, result.action_options);
      setInput("");
      await refreshLobby().catch(() => {});
    } catch (err) { setError(err.message || "创建游戏失败。"); }
  }
  async function chooseAdventure(adventureId) { if (!activeGameId) return; const result = await selectAdventure(activeGameId, adventureId); await syncGame(activeGameId, result.game_state); }
  async function sendMessage() { if (!input.trim() || !activeGameId || isLoading) return; if (gameState?.campaign?.phase === "adventure_selection") return setError("请先选择冒险。"); setIsLoading(true); try { const result = await submitTurn(activeGameId, input.trim()); setInput(""); await syncGame(activeGameId, result.game_state); } catch (err) { setError(err.message || "发送消息失败。"); } finally { setIsLoading(false); } }

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
        const { attack_name, ...payload } = actionDraft.attack;
        result = await attackAction(activeGameId, { ...payload, attack_bonus: Number(payload.attack_bonus) });
      }
      if (kind === "spell") result = await castSpellAction(activeGameId, { ...actionDraft.spell, slot_level: Number(actionDraft.spell.slot_level || 0) });
      if (kind === "skill") result = await skillCheckAction(activeGameId, { ...actionDraft.skill, dc: Number(actionDraft.skill.dc || 0), modifier: actionDraft.skill.modifier === "" ? null : Number(actionDraft.skill.modifier) });
      if (kind === "save") result = await savingThrowAction(activeGameId, { ...actionDraft.save, dc: Number(actionDraft.save.dc || 0), modifier: actionDraft.save.modifier === "" ? null : Number(actionDraft.save.modifier) });
      if (kind === "item") result = await useItemAction(activeGameId, { ...actionDraft.item, quantity: Number(actionDraft.item.quantity || 1) });
      if (result?.game_state) await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "执行动作失败。"); }
  }

  const encounter = gameState?.encounter;
  const combatants = encounter?.initiative_order?.map((id) => encounter.combatants[id]).filter(Boolean) || [];
  const timeline = (gameState?.timeline || []).slice(-12).reverse();

  return (
    <div className="app-container">
      {!["home", "new_game", "creator", "monsters"].includes(view) && <div className="sidebar"><div className="brand">DM_Agent</div><div className="menu-items"><div className="menu-active-info">当前游戏：{activeGameId}</div><button onClick={() => setView("chat")} className={view === "chat" ? "active" : ""}>对话</button><button onClick={() => setView("status")} className={view === "status" ? "active" : ""}>状态</button><button className="btn-danger" onClick={() => { setActiveGameId(null); setGameState(null); setMessages([]); setView("home"); }}>返回主页</button></div></div>}
      <main className="main-content">
        {error && <div className="list-item error-banner" style={{ margin: 16 }}>{error}</div>}

        {view === "home" && <div className="home-container anime-fade-in"><h1 className="title-hero">D&D 2024 跑团主持台</h1><p className="subtitle">本地规则、状态追踪、战斗工具与 LangGraph DM 编排整合在同一个前端里。</p><div className="card-grid"><div className="bento-card glow-hover" onClick={() => setView("new_game")}><div className="card-icon">局</div><h3>新建游戏</h3><p>创建一局新冒险，并把已保存角色编入队伍。</p></div><div className="bento-card glow-hover" onClick={() => { setCharDraft({ ...EMPTY_CHAR }); setSpellList([]); setView("creator"); }}><div className="card-icon">角</div><h3>角色构筑</h3><p>创建并保存角色模板，供建局时直接选入队伍。</p></div><div className="bento-card glow-hover" onClick={() => { setMonsterDraft({ ...EMPTY_MON }); setView("monsters"); }}><div className="card-icon">怪</div><h3>怪物模板</h3><p>保存和复用自定义怪物，快速生成遭遇。</p></div></div><div className="section-divider"></div><h3>已保存游戏</h3><div className="scroll-list">{games.length === 0 && <p className="empty-text">还没有已保存的游戏。</p>}{games.map((game) => <div key={game.game_id} className="list-item" onClick={() => enterGame(game.game_id)}><span className="icon">卷</span><span>{game.title}（{localizeScene(game.scene)}）{game.encounter_active ? " · 战斗中" : ""}</span></div>)}</div><div className="section-divider"></div><h3>怪物模板</h3><div className="scroll-list">{monsters.length === 0 && <p className="empty-text">还没有怪物模板。</p>}{monsters.slice(0, 6).map((monster) => <div key={monster.monster_id} className="list-item" onClick={() => openMonster(monster.monster_id)}><span className="icon">兽</span><span>{monster.name} · {formatMonsterSummary(monster)}</span></div>)}</div></div>}

        {view === "creator" && (
          <div className="creator-container anime-slide-up">
            <div className="panel-card">
              <h2>角色构筑</h2>
              <div className="form-group">
                <label>角色名</label>
                <input value={charDraft.name} onChange={(e) => setCharDraft((p) => ({ ...p, name: e.target.value }))} />
              </div>
              <div className="form-group">
                <label>种族</label>
                <div className="class-grid">
                  {builder.species.map((species) => <div key={species.id} className={`class-card ${charDraft.species === species.name ? "selected" : ""}`} onClick={() => setCharDraft((p) => ({ ...p, species: species.name }))}>{species.name_display || species.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>背景</label>
                <div className="class-grid">
                  {builder.backgrounds.map((bg) => <div key={bg.id} className={`class-card ${charDraft.background_name === bg.name ? "selected" : ""}`} onClick={() => chooseBackground(bg.name)}>{bg.name_display || bg.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>起源专长</label>
                <input value={background?.origin_feat_display || charDraft.origin_feat} readOnly />
              </div>
              <div className="form-group">
                <label>职业</label>
                <div className="class-grid">
                  {builder.classes.map((cls) => <div key={cls.id} className={`class-card ${charDraft.class_name === cls.name ? "selected" : ""}`} onClick={() => chooseClass(cls)}>{cls.name_display || cls.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>起始装备包</label>
                {!classDef ? (
                  <p className="info-text">先选择职业，才能查看可用的起始装备包。</p>
                ) : starterOptions.length === 0 ? (
                  <p className="info-text">当前职业还没有起始装备包元数据。</p>
                ) : (
                  <div className="class-grid">
                    {starterOptions.map((option) => <div key={option.id} className={`class-card ${selectedStarterOption?.id === option.id ? "selected" : ""}`} onClick={() => chooseStarterOption(option.id)}><strong>{option.label_display || option.label}</strong><p className="spell-meta">{formatGoldLine(option.gold_gp)}</p></div>)}
                  </div>
                )}
              </div>
              {starterChoiceGroups.map((group) => (
                <div key={group.id} className="form-group">
                  <label>{group.label_display || group.label}</label>
                  <p className="info-text">{group.description_display || group.description}</p>
                  <div className="class-grid" style={{ marginTop: 12 }}>
                    {(group.options || []).map((option) => <div key={option.id} className={`class-card ${charDraft.starter_choice_ids[group.id] === option.id ? "selected" : ""}`} onClick={() => chooseStarterChoice(group.id, option.id)}><strong>{option.label_display || option.label}</strong></div>)}
                  </div>
                </div>
              ))}
              <div className="builder-preview-grid">
                <div className="builder-preview-card">
                  <h3>起始装备包</h3>
                  {!selectedStarterOption ? <p className="info-text">选择职业后即可预览起始装备包。</p> : <div><div className="timeline-summary">{selectedStarterOption.label_display || selectedStarterOption.label}</div><div className="timeline-content">{selectedStarterOption.description_display || selectedStarterOption.description}</div>{starterChoiceGroups.length > 0 && !starterChoicesComplete && <div className="timeline-content">该装备包仍有未完成的子选项，保存前需要补齐。</div>}</div>}
                </div>
                <div className="builder-preview-card">
                  <h3>起始装备</h3>
                  {!classDef ? <p className="info-text">选择职业后即可预览保存时由后端补齐的装备。</p> : starterEquipment.length === 0 ? <p className="info-text">当前方案不直接附带物品，只提供金币。</p> : <div className="timeline-list">{starterEquipment.map((item) => <div key={`${item.name}-${item.type}-${item.quantity || 1}`} className="timeline-item"><div className="timeline-summary">{item.name_display || item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || "起始物品"}</div></div>)}</div>}
                </div>
                <div className="builder-preview-card">
                  <h3>起始金币</h3>
                  {!classDef ? <p className="info-text">选择职业后即可预览起始金币。</p> : <div><div className="timeline-summary">{formatGoldLine(starterGoldGp)}</div><div className="timeline-content">角色保存时会由后端自动写入。</div></div>}
                </div>
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
                <label>生命上限</label>
                <input type="number" value={charDraft.hp_max} onChange={(e) => setCharDraft((p) => ({ ...p, hp_max: Number.parseInt(e.target.value || "0", 10) }))} />
              </div>
              <div className="stats-editor">
                {STATS.map((stat) => <div key={stat} className="stat-row"><span className="stat-name">{localizeStat(stat)}</span><button onClick={() => setCharDraft((p) => ({ ...p, stats: { ...p.stats, [stat]: p.stats[stat] - 1 } }))}>-</button><span className="stat-val">{charDraft.stats[stat]}</span><button onClick={() => setCharDraft((p) => ({ ...p, stats: { ...p.stats, [stat]: p.stats[stat] + 1 } }))}>+</button></div>)}
              </div>
              <div className="form-group">
                <label>职业技能</label>
                <div className="class-grid">
                  {(classDef?.skill_choices || []).map((skill) => <div key={skill} className={`class-card ${Number(charDraft.skill_proficiencies[skill] || 0) > 0 ? "selected" : ""}`} onClick={() => toggleSkill(skill)}>{localizeSkill(skill)}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>戏法</label>
                {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasCantripSelection ? <p className="info-text">当前职业在 1 级时不获得戏法。</p> : <div><p className="spell-meta">需要选择 {startingCantripCount} 个戏法。</p><p className="spell-meta">已选 {charDraft.selectedCantrips.length}/{startingCantripCount}</p>{cantripOptions.length === 0 ? <p className="info-text">当前职业没有可用的戏法列表。</p> : <div className="spell-grid">{cantripOptions.map((spell) => <div key={spell.id || spell.name} className={`spell-card ${charDraft.selectedCantrips.includes(spell.name) ? "selected" : ""}`} onClick={() => toggleCantrip(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">戏法 · {spell.school_display || spell.school}</p></div>)}</div>}</div>}
              </div>
              <div className="form-group">
                <label>已准备法术</label>
                {!classDef?.spellcasting_ability ? <p className="info-text">当前职业在此构筑器中没有施法能力。</p> : !hasLevelOneSpellcasting ? <p className="info-text">当前职业在 1 级时没有可准备的法术位。</p> : <div><p className="spell-meta">需要选择 {startingPreparedSpellCount} 个 1 环及以上法术。</p><p className="spell-meta">已选 {charDraft.selectedSpells.length}/{startingPreparedSpellCount}</p>{levelOnePreparedSpells.length === 0 ? <p className="info-text">当前职业没有可用的 1 环及以上法术列表。</p> : <div className="spell-grid">{levelOnePreparedSpells.map((spell) => <div key={spell.id || spell.name} className={`spell-card ${charDraft.selectedSpells.includes(spell.name) ? "selected" : ""}`} onClick={() => togglePreparedSpell(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">{spell.level} 环 · {spell.school_display || spell.school}</p></div>)}</div>}</div>}
              </div>
              <div className="btn-row">
                <button className="btn-text" onClick={() => setView("home")}>返回</button>
                <button className="btn-success" onClick={saveChar} disabled={!charDraft.name || !charDraft.class_name || !charDraft.background_name || (starterOptions.length > 0 && !selectedStarterOption) || !builderSelectionComplete}>保存角色</button>
              </div>
            </div>
          </div>
        )}

        {view === "monsters" && <div className="creator-container anime-slide-up"><div className="manager-layout"><div className="panel-card"><div className="btn-row" style={{ marginTop: 0, marginBottom: 12 }}><h2 style={{ margin: 0 }}>怪物模板</h2><button className="btn-secondary" onClick={() => setMonsterDraft({ ...EMPTY_MON })}>新建</button></div><div className="timeline-list">{monsters.length === 0 && <p className="empty-text">还没有怪物模板。</p>}{monsters.map((monster) => <div key={monster.monster_id} className="timeline-item" onClick={() => openMonster(monster.monster_id)}><div className="timeline-summary">{monster.name}</div><div className="timeline-content">{formatMonsterSummary(monster)}</div></div>)}</div></div><div className="panel-card"><h2>{monsterDraft.monster_id ? "编辑怪物" : "新建怪物"}</h2><div className="form-group"><label>名称</label><input value={monsterDraft.name} onChange={(e) => setMonsterDraft((p) => ({ ...p, name: e.target.value }))} /></div><div className="dual-grid"><div className="form-group"><label>体型</label><input value={monsterDraft.size} onChange={(e) => setMonsterDraft((p) => ({ ...p, size: e.target.value }))} placeholder={localizeSize(monsterDraft.size)} /></div><div className="form-group"><label>类型</label><input value={monsterDraft.creature_type} onChange={(e) => setMonsterDraft((p) => ({ ...p, creature_type: e.target.value }))} placeholder={localizeCreatureType(monsterDraft.creature_type)} /></div><div className="form-group"><label>阵营</label><input value={monsterDraft.alignment} onChange={(e) => setMonsterDraft((p) => ({ ...p, alignment: e.target.value }))} placeholder={localizeAlignment(monsterDraft.alignment)} /></div><div className="form-group"><label>挑战等级</label><input value={monsterDraft.challenge_rating} onChange={(e) => setMonsterDraft((p) => ({ ...p, challenge_rating: e.target.value }))} /></div><div className="form-group"><label>护甲等级</label><input type="number" value={monsterDraft.ac} onChange={(e) => setMonsterDraft((p) => ({ ...p, ac: Number.parseInt(e.target.value || "0", 10) }))} /></div><div className="form-group"><label>生命值</label><input type="number" value={monsterDraft.hp_max} onChange={(e) => setMonsterDraft((p) => ({ ...p, hp_max: Number.parseInt(e.target.value || "0", 10) }))} /></div></div><div className="form-group"><label>特性</label><textarea className="text-block" value={monsterDraft.traitsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, traitsText: e.target.value }))} /></div><div className="form-group"><label>动作</label><textarea className="text-block" value={monsterDraft.actionsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, actionsText: e.target.value }))} /></div><div className="form-group"><label>备注</label><textarea className="text-block" value={monsterDraft.notes} onChange={(e) => setMonsterDraft((p) => ({ ...p, notes: e.target.value }))} /></div><div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>返回</button><button className="btn-success" onClick={saveMonster} disabled={!monsterDraft.name.trim()}>保存怪物</button></div></div></div></div>}

        {view === "new_game" && <div className="modal-overlay"><div className="modal-content anime-pop"><h2>新建游戏</h2><p className="info-text">先输入游戏存档 ID，再从下方选择要带入本局的队伍角色。</p><input className="input-lg" placeholder="例如：第一章-测试局" value={newGameId} onChange={(e) => setNewGameId(e.target.value)} /><h3>队伍角色</h3><p className="info-text">已选择 {selectedGameChars.length} 名角色。这里不是摆设，选中的角色会直接写入新游戏。</p>{characters.length === 0 ? <div className="timeline-item"><div className="timeline-summary">还没有可用角色</div><div className="timeline-content">请先到“角色构筑”里保存至少一名角色，再回来建局。</div></div> : <div className="char-select-list">{characters.map((character) => <div key={character.character_id} className={`char-option ${selectedGameChars.includes(character.character_id) ? "selected" : ""}`} onClick={() => setSelectedGameChars((prev) => prev.includes(character.character_id) ? prev.filter((item) => item !== character.character_id) : [...prev, character.character_id])}><div className="avatar">角</div><span>{character.name} · {character.class_name_display || localizeClassName(character.class_name)}</span></div>)}</div>}<div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>取消</button><button className="btn-primary" onClick={makeGame}>创建并进入</button></div></div></div>}

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
                            <button className="btn-primary" onClick={() => chooseAdventure(hook.adventure_id)}>选择这条线索</button>
                          </div>
                        </div>
                      ))}
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
                {isLoading && <div className="loading-indicator">主持人思考中...</div>}
                <div ref={messagesEndRef} />
              </div>
              <div className="session-sidepanel">
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
                <div className="panel-card">
                  <h3>时间线</h3>
                  <div className="timeline-list">
                    {timeline.map((event) => <div key={event.event_id} className="timeline-item"><div className="timeline-type">{eventLabel(event.type)}</div><div className="timeline-summary">{event.summary}</div>{event.content && <div className="timeline-content">{event.content}</div>}</div>)}
                  </div>
                </div>
                <div className="panel-card">
                  <h3>遭遇面板</h3>
                  {!encounter ? <p className="empty-text">当前没有激活遭遇。</p> : <div className="combatant-list">{combatants.map((combatant) => <div key={combatant.combatant_id} className={`combatant-item ${encounter.current_combatant_id === combatant.combatant_id ? "combatant-active" : ""}`}><div className="timeline-summary">{combatant.name} · {localizeSide(combatant.side)}</div><div className="timeline-content">{formatCombatantStateLine(combatant)}</div><div className="action-grid" style={{ marginTop: 10 }}><input value={initiativeDrafts[combatant.combatant_id] ?? ""} onChange={(e) => setInitiativeDrafts((prev) => ({ ...prev, [combatant.combatant_id]: e.target.value }))} placeholder="先攻" /><button className="btn-secondary" onClick={() => saveEncounterInitiative(combatant.combatant_id)}>设置先攻</button><button className="btn-secondary" onClick={() => rerollEncounterInitiative(combatant.combatant_id)}>重掷先攻</button></div>{!combatant.linked_character_id && <div className="btn-row" style={{ marginTop: 10 }}><button className="btn-danger" onClick={() => dropEncounterCombatant(combatant.combatant_id)}>移除</button></div>}</div>)}</div>}
                </div>
              </div>
            </div>
            <div className="input-area">
              <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder={gameState?.campaign?.phase === "adventure_selection" ? "请先选择冒险。" : "描述你的行动..."} disabled={gameState?.campaign?.phase === "adventure_selection"} />
              <button onClick={sendMessage} disabled={gameState?.campaign?.phase === "adventure_selection"}>发送</button>
            </div>
          </div>
        )}


        {view === "status" && <div className="status-screen anime-fade-in"><h2>队伍状态</h2><div className="status-cards">{Object.values(gameState?.characters || {}).map((character) => <div key={character.character_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">角</div><div><h3>{character.name}</h3><span className="badge">{character.class_name_display || localizeClassName(character.class_name)} · {character.level}级</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${character.hp_max > 0 ? (character.hp_current / character.hp_max) * 100 : 0}%` }}></div><span className="text">{formatHpBarLabel(character.hp_current, character.hp_max)}</span></div><div className="timeline-content">财富：{formatGoldLine(character.gold_gp)}</div></div>)}</div><h2 style={{ marginTop: 32 }}>遭遇状态</h2><div className="status-cards">{combatants.length === 0 && <p className="empty-text">当前没有战斗单位。</p>}{combatants.map((combatant) => <div key={combatant.combatant_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">{combatant.side === "enemy" ? "敌" : "角"}</div><div><h3>{combatant.name}</h3><span className="badge">{localizeSide(combatant.side)} · 先攻 {combatant.initiative ?? "?"}</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${combatant.hp_max > 0 ? (combatant.hp_current / combatant.hp_max) * 100 : 0}%` }}></div><span className="text">{formatHpBarLabel(combatant.hp_current, combatant.hp_max)}</span></div></div>)}</div></div>}
      </main>
    </div>
  );
}
