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
const ATTACK_RESOLUTION_OPTIONS = [
  { value: "normal", label: "Normal Damage" },
  { value: "nonlethal", label: "Nonlethal" },
  { value: "capture", label: "Capture" },
];
const EMPTY_CHAR = { name: "", species: "Human", background_name: "", origin_feat: "", class_name: "", starter_option_id: "", starter_choice_ids: {}, hp_max: 10, stats: Object.fromEntries(STATS.map((k) => [k, 10])), skill_proficiencies: {}, selectedCantrips: [], selectedSpells: [] };
const EMPTY_MON = { monster_id: "", name: "", size: "Medium", creature_type: "Beast", alignment: "Unaligned", challenge_rating: "1", ac: 10, hp_max: 10, initiative_bonus: 0, speed: 30, notes: "", traitsText: "", actionsText: "", reactionsText: "", bonusActionsText: "" };
const EMPTY_ACTIONS = { attack: { attacker_ref: "", attack_name: "", target_ref: "", attack_bonus: 0, damage_expression: "1d6", damage_type: "", resolution_mode: "normal" }, spell: { caster_ref: "", spell_name: "", slot_level: 1 }, skill: { actor_ref: "", skill_name: "", dc: 10, modifier: "" }, save: { target_ref: "", save_name: "", dc: 10, modifier: "" }, item: { user_ref: "", item_name: "", quantity: 1 } };
const EMPTY_ENCOUNTER_DRAFT = { enemy_names: "", enemy_hp: 10, enemy_ac: 10, monster_id: "", quantity: 1, custom_name: "", template_side: "enemy", hp_override: "", quick_enemy_name: "", quick_enemy_hp: 10, quick_enemy_ac: 10, quick_enemy_initiative_bonus: 0, quick_enemy_side: "enemy" };

const parseEntries = (text, prefix) => text.split("\n").map((x) => x.trim()).filter(Boolean).map((description, i) => ({ name: `${prefix} ${i + 1}`, description }));
const entriesToText = (entries = []) => entries.map((x) => x.description).join("\n");
const mapMessages = (history = []) => history.map((m) => ({ sender: m.role === "assistant" ? "dm" : m.role === "user" ? "player" : "system", text: m.content }));
const eventLabel = (t) => ({ player_action: "Player", assistant_response: "DM", dice_result: "Dice", hp_changed: "HP", attack_resolved: "Attack", skill_check: "Skill", saving_throw: "Save", spell_cast: "Spell", item_used: "Item", turn_advanced: "Turn", encounter_started: "Encounter", monster_template_saved: "Monster Saved", monster_spawned: "Monster Spawned" }[t] || t);
const getSpellLevel = (spell) => Number(spell?.level ?? 0);
const formatEquipmentLine = (item) => {
  const details = [];
  if (item.quantity && item.quantity > 1) details.push(`x${item.quantity}`);
  if (item.type) details.push(item.type);
  if (item.damage_expression) details.push(item.damage_expression);
  if (item.damage_type) details.push(item.damage_type);
  if (item.armor_class_bonus) details.push(`AC +${item.armor_class_bonus}`);
  if (item.is_equipped) details.push("equipped");
  return details.join(" · ");
};
const formatResourceRecovery = (resource) => resource.recovery === "short_rest" ? "Short Rest" : resource.recovery === "long_rest" ? "Long Rest" : resource.recovery;
const formatSpellSlotLine = ([level, total]) => `Level ${level} · ${total} slot${Number(total) > 1 ? "s" : ""}`;
const formatGoldLine = (goldGp) => `${Number(goldGp || 0)} gp`;
const formatAttackSource = (source) => source === "monster_action" ? "Monster Action" : source === "inventory" ? "Inventory" : source || "Attack";
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
  const actorList = (actionOptions.actors || []).map((a) => ({ value: a.ref, label: a.side ? `${a.name} (${a.side})` : a.name }));
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
      ? `${spell.name} (Lv ${spell.level}${spell.available ? "" : " · No slots"})`
      : `${spell.name} (Cantrip)`,
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
    } catch (err) { setError(err.message || "Failed to load lobby."); }
  }

  async function syncGame(gameId, state) {
    setGameState(state);
    setMessages(mapMessages(state.chat_history || []));
    setActionOptions(await loadActionOptions(gameId));
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
    if (attack.damage_type) details.push(attack.damage_type);
    return `${attack.name} (${details.join(" / ")})`;
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
  function toggleSkill(skill) { if (backgroundSkills.has(skill)) return; const selected = Number(charDraft.skill_proficiencies[skill] || 0) > 0; const picked = Object.entries(charDraft.skill_proficiencies).filter(([n, v]) => !backgroundSkills.has(n) && Number(v) > 0 && n !== skill); if (!selected && picked.length >= Number(classDef?.skills_to_choose || 0)) return setError(`Only ${classDef?.skills_to_choose || 0} extra class skills allowed.`); setError(""); setCharDraft((p) => ({ ...p, skill_proficiencies: { ...p.skill_proficiencies, [skill]: selected ? 0 : 1 } })); }
  function chooseStarterOption(optionId) { setCharDraft((p) => ({ ...p, starter_option_id: optionId, starter_choice_ids: {} })); }
  function chooseStarterChoice(groupId, optionId) { setCharDraft((p) => ({ ...p, starter_choice_ids: { ...p.starter_choice_ids, [groupId]: optionId } })); }
  function togglePreparedSpell(spellName) {
    if (!hasLevelOneSpellcasting) {
      setError("This class does not prepare level 1 spells in the current builder.");
      return;
    }

    const selected = charDraft.selectedSpells.includes(spellName);
    if (!selected && startingPreparedSpellCount > 0 && charDraft.selectedSpells.length >= startingPreparedSpellCount) {
      setError(`Select exactly ${startingPreparedSpellCount} level 1+ spells for ${classDef?.name}.`);
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
      setError("This class does not gain cantrips in the current builder.");
      return;
    }

    const selected = charDraft.selectedCantrips.includes(spellName);
    if (!selected && charDraft.selectedCantrips.length >= startingCantripCount) {
      setError(`Select exactly ${startingCantripCount} cantrips for ${classDef?.name}.`);
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
    } catch (err) { setError(err.message || "Failed to save character."); }
  }

  async function saveMonster() {
    try {
      setError("");
      await saveMonsterTemplate({ monster_id: monsterDraft.monster_id || undefined, name: monsterDraft.name, size: monsterDraft.size, creature_type: monsterDraft.creature_type, alignment: monsterDraft.alignment, challenge_rating: monsterDraft.challenge_rating, ac: monsterDraft.ac, hp_max: monsterDraft.hp_max, initiative_bonus: monsterDraft.initiative_bonus, speed: monsterDraft.speed, notes: monsterDraft.notes, traits: parseEntries(monsterDraft.traitsText, "Trait"), actions: parseEntries(monsterDraft.actionsText, "Action"), reactions: parseEntries(monsterDraft.reactionsText, "Reaction"), bonus_actions: parseEntries(monsterDraft.bonusActionsText, "Bonus Action") });
      setMonsterDraft({ ...EMPTY_MON }); await refreshLobby();
    } catch (err) { setError(err.message || "Failed to save monster."); }
  }

  async function openMonster(monsterId) {
    try {
      const m = await loadMonsterTemplate(monsterId);
      setMonsterDraft({ monster_id: m.monster_id, name: m.name, size: m.size || "Medium", creature_type: m.creature_type || "Beast", alignment: m.alignment || "Unaligned", challenge_rating: m.challenge_rating || "1", ac: m.ac ?? 10, hp_max: m.hp_max ?? 10, initiative_bonus: m.initiative_bonus ?? 0, speed: m.speed ?? 30, notes: m.notes || "", traitsText: entriesToText(m.traits), actionsText: entriesToText(m.actions), reactionsText: entriesToText(m.reactions), bonusActionsText: entriesToText(m.bonus_actions) });
      setView("monsters");
    } catch (err) { setError(err.message || "Failed to load monster."); }
  }

  async function makeGame() { if (!newGameId.trim()) return setError("Enter a game_id."); try { await createGame({ game_id: newGameId.trim(), title: newGameId.trim(), character_ids: selectedGameChars }); await refreshLobby(); await enterGame(newGameId.trim()); } catch (err) { setError(err.message || "Failed to create game."); } }
  async function chooseAdventure(adventureId) { if (!activeGameId) return; const result = await selectAdventure(activeGameId, adventureId); await syncGame(activeGameId, result.game_state); }
  async function sendMessage() { if (!input.trim() || !activeGameId || isLoading) return; if (gameState?.campaign?.phase === "adventure_selection") return setError("Choose an adventure first."); setIsLoading(true); try { const result = await submitTurn(activeGameId, input.trim()); setInput(""); await syncGame(activeGameId, result.game_state); } catch (err) { setError(err.message || "Failed to send message."); } finally { setIsLoading(false); } }

  async function createEncounterFromNames() {
    if (!activeGameId) return;
    const enemyNames = encounterDraft.enemy_names.split("\n").map((name) => name.trim()).filter(Boolean);
    if (enemyNames.length === 0) return setError("Enter at least one enemy name.");
    try {
      setError("");
      const result = await startEncounter(activeGameId, {
        enemy_names: enemyNames,
        enemy_hp: Number(encounterDraft.enemy_hp || 10),
        enemy_ac: Number(encounterDraft.enemy_ac || 10),
      });
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "Failed to start encounter."); }
  }

  async function createEncounterFromTemplate() {
    if (!activeGameId) return;
    if (!encounterDraft.monster_id) return setError("Choose a monster template.");
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
    } catch (err) { setError(err.message || "Failed to spawn monster template."); }
  }

  async function addQuickEnemy() {
    if (!activeGameId) return;
    if (!encounterDraft.quick_enemy_name.trim()) return setError("Enter an enemy name.");
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
    } catch (err) { setError(err.message || "Failed to add enemy."); }
  }

  async function finishEncounter() {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await endEncounter(activeGameId);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "Failed to end encounter."); }
  }

  async function dropEncounterCombatant(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await removeEncounterCombatant(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "Failed to remove combatant."); }
  }

  async function saveEncounterInitiative(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await setEncounterInitiative(activeGameId, combatantRef, Number(initiativeDrafts[combatantRef] || 0));
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "Failed to set initiative."); }
  }

  async function rerollEncounterInitiative(combatantRef) {
    if (!activeGameId) return;
    try {
      setError("");
      const result = await rollEncounterInitiative(activeGameId, combatantRef);
      await syncGame(activeGameId, result.game_state);
    } catch (err) { setError(err.message || "Failed to roll initiative."); }
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
    } catch (err) { setError(err.message || "Failed to run action."); }
  }

  const encounter = gameState?.encounter;
  const combatants = encounter?.initiative_order?.map((id) => encounter.combatants[id]).filter(Boolean) || [];
  const timeline = (gameState?.timeline || []).slice(-12).reverse();

  return (
    <div className="app-container">
      {!["home", "new_game", "creator", "monsters"].includes(view) && <div className="sidebar"><div className="brand">D&D Agent</div><div className="menu-items"><div className="menu-active-info">Playing: {activeGameId}</div><button onClick={() => setView("chat")} className={view === "chat" ? "active" : ""}>Chat</button><button onClick={() => setView("status")} className={view === "status" ? "active" : ""}>Status</button><button className="btn-danger" onClick={() => { setActiveGameId(null); setGameState(null); setMessages([]); setView("home"); }}>Leave</button></div></div>}
      <main className="main-content">
        {error && <div className="list-item error-banner" style={{ margin: 16 }}>{error}</div>}

        {view === "home" && <div className="home-container anime-fade-in"><h1 className="title-hero">D&D 2024 DM Agent</h1><p className="subtitle">Rules-aware flow, local tools, and ADK orchestration.</p><div className="card-grid"><div className="bento-card glow-hover" onClick={() => setView("new_game")}><div className="card-icon">🎲</div><h3>New Game</h3><p>Create a session and assemble a party.</p></div><div className="bento-card glow-hover" onClick={() => { setCharDraft({ ...EMPTY_CHAR }); setSpellList([]); setView("creator"); }}><div className="card-icon">🧙</div><h3>Character Builder</h3><p>Build and save party templates.</p></div><div className="bento-card glow-hover" onClick={() => { setMonsterDraft({ ...EMPTY_MON }); setView("monsters"); }}><div className="card-icon">🐉</div><h3>Monster Templates</h3><p>Save and reuse custom monsters.</p></div></div><div className="section-divider"></div><h3>Games</h3><div className="scroll-list">{games.length === 0 && <p className="empty-text">No saved games.</p>}{games.map((game) => <div key={game.game_id} className="list-item" onClick={() => enterGame(game.game_id)}><span className="icon">📜</span><span>{game.title} ({game.scene}){game.encounter_active ? " · Combat" : ""}</span></div>)}</div><div className="section-divider"></div><h3>Monsters</h3><div className="scroll-list">{monsters.length === 0 && <p className="empty-text">No monster templates.</p>}{monsters.slice(0, 6).map((monster) => <div key={monster.monster_id} className="list-item" onClick={() => openMonster(monster.monster_id)}><span className="icon">🐾</span><span>{monster.name} · {monster.creature_type} · CR {monster.challenge_rating}</span></div>)}</div></div>}

        {view === "creator" && (
          <div className="creator-container anime-slide-up">
            <div className="panel-card">
              <h2>Character Builder</h2>
              <div className="form-group">
                <label>Name</label>
                <input value={charDraft.name} onChange={(e) => setCharDraft((p) => ({ ...p, name: e.target.value }))} />
              </div>
              <div className="form-group">
                <label>Species</label>
                <div className="class-grid">
                  {builder.species.map((species) => <div key={species.id} className={`class-card ${charDraft.species === species.name ? "selected" : ""}`} onClick={() => setCharDraft((p) => ({ ...p, species: species.name }))}>{species.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>Background</label>
                <div className="class-grid">
                  {builder.backgrounds.map((bg) => <div key={bg.id} className={`class-card ${charDraft.background_name === bg.name ? "selected" : ""}`} onClick={() => chooseBackground(bg.name)}>{bg.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>Origin Feat</label>
                <input value={charDraft.origin_feat} readOnly />
              </div>
              <div className="form-group">
                <label>Class</label>
                <div className="class-grid">
                  {builder.classes.map((cls) => <div key={cls.id} className={`class-card ${charDraft.class_name === cls.name ? "selected" : ""}`} onClick={() => chooseClass(cls)}>{cls.name}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>Starter Package</label>
                {!classDef ? (
                  <p className="info-text">Choose a class to unlock starter package selection.</p>
                ) : starterOptions.length === 0 ? (
                  <p className="info-text">This class has no starter package metadata yet.</p>
                ) : (
                  <div className="class-grid">
                    {starterOptions.map((option) => <div key={option.id} className={`class-card ${selectedStarterOption?.id === option.id ? "selected" : ""}`} onClick={() => chooseStarterOption(option.id)}><strong>{option.label}</strong><p className="spell-meta">{formatGoldLine(option.gold_gp)}</p></div>)}
                  </div>
                )}
              </div>
              {starterChoiceGroups.map((group) => (
                <div key={group.id} className="form-group">
                  <label>{group.label}</label>
                  <p className="info-text">{group.description}</p>
                  <div className="class-grid" style={{ marginTop: 12 }}>
                    {(group.options || []).map((option) => <div key={option.id} className={`class-card ${charDraft.starter_choice_ids[group.id] === option.id ? "selected" : ""}`} onClick={() => chooseStarterChoice(group.id, option.id)}><strong>{option.label}</strong></div>)}
                  </div>
                </div>
              ))}
              <div className="builder-preview-grid">
                <div className="builder-preview-card">
                  <h3>Starter Package</h3>
                  {!selectedStarterOption ? <p className="info-text">Select a class to preview the available starter package.</p> : <div><div className="timeline-summary">{selectedStarterOption.label}</div><div className="timeline-content">{selectedStarterOption.description}</div>{starterChoiceGroups.length > 0 && !starterChoicesComplete && <div className="timeline-content">This package still needs one or more sub-choices before save.</div>}</div>}
                </div>
                <div className="builder-preview-card">
                  <h3>Starter Equipment</h3>
                  {!classDef ? <p className="info-text">Choose a class to preview the equipment the backend will add on save.</p> : starterEquipment.length === 0 ? <p className="info-text">This package does not add any items. You start with gold only.</p> : <div className="timeline-list">{starterEquipment.map((item) => <div key={`${item.name}-${item.type}-${item.quantity || 1}`} className="timeline-item"><div className="timeline-summary">{item.name}</div><div className="timeline-content">{formatEquipmentLine(item) || "Starter item"}</div></div>)}</div>}
                </div>
                <div className="builder-preview-card">
                  <h3>Starting Gold</h3>
                  {!classDef ? <p className="info-text">Choose a class to preview the starting gold grant.</p> : <div><div className="timeline-summary">{formatGoldLine(starterGoldGp)}</div><div className="timeline-content">This amount is applied by the backend when the character is saved.</div></div>}
                </div>
                <div className="builder-preview-card">
                  <h3>Class Resources</h3>
                  {!classDef ? <p className="info-text">Choose a class to preview tracked level 1 resources.</p> : starterResources.length === 0 ? <p className="info-text">This class has no tracked level 1 resources.</p> : <div className="timeline-list">{starterResources.map(([name, resource]) => <div key={name} className="timeline-item"><div className="timeline-summary">{name} · {resource.current_value}/{resource.max_value}</div><div className="timeline-content">{resource.description || "Class resource"} · Recover on {formatResourceRecovery(resource)}</div></div>)}</div>}
                </div>
                <div className="builder-preview-card">
                  <h3>Starting Spell Slots</h3>
                  {!classDef ? <p className="info-text">Choose a class to preview level 1 spell slots.</p> : !classDef.spellcasting_ability ? <p className="info-text">This class does not start with spellcasting.</p> : startingSpellSlots.length === 0 ? <div><p className="info-text">This class has spellcasting metadata, but no level 1 slots in the current builder catalog.</p><p className="spell-meta">Ability {classDef.spellcasting_ability} · Mode {classDef.spellcasting_mode || "prepared"}</p></div> : <div><p className="spell-meta">Ability {classDef.spellcasting_ability} · Mode {classDef.spellcasting_mode || "prepared"}</p><div className="timeline-list">{startingSpellSlots.map((slot) => <div key={slot[0]} className="timeline-item"><div className="timeline-summary">{formatSpellSlotLine(slot)}</div><div className="timeline-content">These slots are auto-filled by the backend when the character is saved.</div></div>)}</div></div>}
                </div>
              </div>
              <div className="form-group">
                <label>HP Max</label>
                <input type="number" value={charDraft.hp_max} onChange={(e) => setCharDraft((p) => ({ ...p, hp_max: Number.parseInt(e.target.value || "0", 10) }))} />
              </div>
              <div className="stats-editor">
                {STATS.map((stat) => <div key={stat} className="stat-row"><span className="stat-name">{stat.toUpperCase()}</span><button onClick={() => setCharDraft((p) => ({ ...p, stats: { ...p.stats, [stat]: p.stats[stat] - 1 } }))}>-</button><span className="stat-val">{charDraft.stats[stat]}</span><button onClick={() => setCharDraft((p) => ({ ...p, stats: { ...p.stats, [stat]: p.stats[stat] + 1 } }))}>+</button></div>)}
              </div>
              <div className="form-group">
                <label>Class Skills</label>
                <div className="class-grid">
                  {(classDef?.skill_choices || []).map((skill) => <div key={skill} className={`class-card ${Number(charDraft.skill_proficiencies[skill] || 0) > 0 ? "selected" : ""}`} onClick={() => toggleSkill(skill)}>{skill}</div>)}
                </div>
              </div>
              <div className="form-group">
                <label>Cantrips</label>
                {!classDef?.spellcasting_ability ? <p className="info-text">This class has no spellcasting in the current builder.</p> : !hasCantripSelection ? <p className="info-text">This class does not gain cantrips at level 1 in the current builder catalog.</p> : <div><p className="spell-meta">Select {startingCantripCount} cantrips.</p><p className="spell-meta">{charDraft.selectedCantrips.length}/{startingCantripCount} selected</p>{cantripOptions.length === 0 ? <p className="info-text">No cantrip list is available for the selected class.</p> : <div className="spell-grid">{cantripOptions.map((spell) => <div key={spell.id || spell.name} className={`spell-card ${charDraft.selectedCantrips.includes(spell.name) ? "selected" : ""}`} onClick={() => toggleCantrip(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">Cantrip · {spell.school}</p></div>)}</div>}</div>}
              </div>
              <div className="form-group">
                <label>Prepared Spells</label>
                {!classDef?.spellcasting_ability ? <p className="info-text">This class has no spellcasting in the current builder.</p> : !hasLevelOneSpellcasting ? <p className="info-text">This class does not prepare level 1 spells in the current builder catalog.</p> : <div><p className="spell-meta">Select {startingPreparedSpellCount} level 1+ spells.</p><p className="spell-meta">{charDraft.selectedSpells.length}/{startingPreparedSpellCount} selected</p>{levelOnePreparedSpells.length === 0 ? <p className="info-text">No level 1+ spell list is available for the selected class.</p> : <div className="spell-grid">{levelOnePreparedSpells.map((spell) => <div key={spell.id || spell.name} className={`spell-card ${charDraft.selectedSpells.includes(spell.name) ? "selected" : ""}`} onClick={() => togglePreparedSpell(spell.name)}><h4>{spell.name}</h4><p className="spell-meta">{spell.level} · {spell.school}</p></div>)}</div>}</div>}
              </div>
              <div className="btn-row">
                <button className="btn-text" onClick={() => setView("home")}>Back</button>
                <button className="btn-success" onClick={saveChar} disabled={!charDraft.name || !charDraft.class_name || !charDraft.background_name || (starterOptions.length > 0 && !selectedStarterOption) || !builderSelectionComplete}>Save Character</button>
              </div>
            </div>
          </div>
        )}

        {view === "monsters" && <div className="creator-container anime-slide-up"><div className="manager-layout"><div className="panel-card"><div className="btn-row" style={{ marginTop: 0, marginBottom: 12 }}><h2 style={{ margin: 0 }}>Monster Templates</h2><button className="btn-secondary" onClick={() => setMonsterDraft({ ...EMPTY_MON })}>New</button></div><div className="timeline-list">{monsters.length === 0 && <p className="empty-text">No monster templates.</p>}{monsters.map((monster) => <div key={monster.monster_id} className="timeline-item" onClick={() => openMonster(monster.monster_id)}><div className="timeline-summary">{monster.name}</div><div className="timeline-content">{monster.creature_type} · CR {monster.challenge_rating}</div></div>)}</div></div><div className="panel-card"><h2>{monsterDraft.monster_id ? "Edit Monster" : "New Monster"}</h2><div className="form-group"><label>Name</label><input value={monsterDraft.name} onChange={(e) => setMonsterDraft((p) => ({ ...p, name: e.target.value }))} /></div><div className="dual-grid"><div className="form-group"><label>Size</label><input value={monsterDraft.size} onChange={(e) => setMonsterDraft((p) => ({ ...p, size: e.target.value }))} /></div><div className="form-group"><label>Type</label><input value={monsterDraft.creature_type} onChange={(e) => setMonsterDraft((p) => ({ ...p, creature_type: e.target.value }))} /></div><div className="form-group"><label>Alignment</label><input value={monsterDraft.alignment} onChange={(e) => setMonsterDraft((p) => ({ ...p, alignment: e.target.value }))} /></div><div className="form-group"><label>CR</label><input value={monsterDraft.challenge_rating} onChange={(e) => setMonsterDraft((p) => ({ ...p, challenge_rating: e.target.value }))} /></div><div className="form-group"><label>AC</label><input type="number" value={monsterDraft.ac} onChange={(e) => setMonsterDraft((p) => ({ ...p, ac: Number.parseInt(e.target.value || "0", 10) }))} /></div><div className="form-group"><label>HP</label><input type="number" value={monsterDraft.hp_max} onChange={(e) => setMonsterDraft((p) => ({ ...p, hp_max: Number.parseInt(e.target.value || "0", 10) }))} /></div></div><div className="form-group"><label>Traits</label><textarea className="text-block" value={monsterDraft.traitsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, traitsText: e.target.value }))} /></div><div className="form-group"><label>Actions</label><textarea className="text-block" value={monsterDraft.actionsText} onChange={(e) => setMonsterDraft((p) => ({ ...p, actionsText: e.target.value }))} /></div><div className="form-group"><label>Notes</label><textarea className="text-block" value={monsterDraft.notes} onChange={(e) => setMonsterDraft((p) => ({ ...p, notes: e.target.value }))} /></div><div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>Back</button><button className="btn-success" onClick={saveMonster} disabled={!monsterDraft.name.trim()}>Save Monster</button></div></div></div></div>}

        {view === "new_game" && <div className="modal-overlay"><div className="modal-content anime-pop"><h2>New Game</h2><input className="input-lg" placeholder="New game_id" value={newGameId} onChange={(e) => setNewGameId(e.target.value)} /><h3>Party</h3><div className="char-select-list">{characters.map((character) => <div key={character.character_id} className={`char-option ${selectedGameChars.includes(character.character_id) ? "selected" : ""}`} onClick={() => setSelectedGameChars((prev) => prev.includes(character.character_id) ? prev.filter((item) => item !== character.character_id) : [...prev, character.character_id])}><div className="avatar">🧙</div><span>{character.name} · {character.class_name}</span></div>)}</div><div className="btn-row"><button className="btn-text" onClick={() => setView("home")}>Cancel</button><button className="btn-primary" onClick={makeGame}>Create</button></div></div></div>}

        {view === "chat" && (
          <div className="chat-layout">
            <div className="chat-header">
              <div>
                <strong>{gameState?.title || activeGameId}</strong>
                <div className="subtitle-inline">Scene {gameState?.scene || "setup"} · Turn {gameState?.turn_number ?? 0}</div>
              </div>
            </div>
            <div className="session-content">
              <div className="chat-window">
                {gameState?.campaign?.phase === "adventure_selection" && (
                  <div className="panel-card">
                    <h3>Select Adventure</h3>
                    <div className="timeline-list">
                      {(gameState?.campaign?.available_adventures || []).map((hook) => (
                        <div key={hook.adventure_id} className="timeline-item">
                          <div className="timeline-summary">{hook.title}</div>
                          <div className="timeline-content">{hook.summary}</div>
                          <div className="btn-row" style={{ marginTop: 12 }}>
                            <button className="btn-primary" onClick={() => chooseAdventure(hook.adventure_id)}>Choose</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {messages.map((message, index) => (
                  <div key={`${message.sender}-${index}`} className={`message ${message.sender} anime-pop`}>
                    <div className="avatar">{message.sender === "dm" ? "🐉" : message.sender === "system" ? "⚙" : "🗨"}</div>
                    <div className="bubble">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
                    </div>
                  </div>
                ))}
                {isLoading && <div className="loading-indicator">Thinking...</div>}
                <div ref={messagesEndRef} />
              </div>
              <div className="session-sidepanel">
                <div className="panel-card">
                  <h3>Encounter Setup</h3>
                  <div className="timeline-list">
                    {encounterSummary.active && <button className="btn-danger" onClick={finishEncounter}>End Encounter</button>}
                    <div className="form-group">
                      <label>Start With Enemy Names</label>
                      <textarea className="text-block" value={encounterDraft.enemy_names} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_names: e.target.value }))} placeholder={"Goblin\\nBandit Captain"} />
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>Enemy HP</label>
                        <input type="number" value={encounterDraft.enemy_hp} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_hp: e.target.value }))} />
                      </div>
                      <div className="form-group">
                        <label>Enemy AC</label>
                        <input type="number" value={encounterDraft.enemy_ac} onChange={(e) => setEncounterDraft((p) => ({ ...p, enemy_ac: e.target.value }))} />
                      </div>
                    </div>
                    <button className="btn-secondary" onClick={createEncounterFromNames}>Start Named Encounter</button>
                    <div className="form-group">
                      <label>Spawn Monster Template</label>
                      <select value={encounterDraft.monster_id} onChange={(e) => setEncounterDraft((p) => ({ ...p, monster_id: e.target.value }))}>
                        <option value="">Monster Template</option>
                        {monsters.map((monster) => <option key={monster.monster_id} value={monster.monster_id}>{monster.name} · CR {monster.challenge_rating}</option>)}
                      </select>
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>Quantity</label>
                        <input type="number" value={encounterDraft.quantity} onChange={(e) => setEncounterDraft((p) => ({ ...p, quantity: e.target.value }))} />
                      </div>
                      <div className="form-group">
                        <label>Custom Name</label>
                        <input value={encounterDraft.custom_name} onChange={(e) => setEncounterDraft((p) => ({ ...p, custom_name: e.target.value }))} placeholder="Optional" />
                      </div>
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>Template Side</label>
                        <select value={encounterDraft.template_side} onChange={(e) => setEncounterDraft((p) => ({ ...p, template_side: e.target.value }))}>
                          <option value="enemy">enemy</option>
                          <option value="party">party</option>
                          <option value="ally">ally</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <label>HP Override</label>
                        <input value={encounterDraft.hp_override} onChange={(e) => setEncounterDraft((p) => ({ ...p, hp_override: e.target.value }))} placeholder="Optional" />
                      </div>
                    </div>
                    {encounterMonsterPreview && <div className="timeline-item"><div className="timeline-summary">{encounterMonsterPreview.name}</div><div className="timeline-content">{encounterMonsterPreview.creature_type} · CR {encounterMonsterPreview.challenge_rating} · AC {encounterMonsterPreview.ac} · HP {encounterMonsterPreview.hp_max}</div></div>}
                    <button className="btn-secondary" onClick={createEncounterFromTemplate}>Spawn Template Encounter</button>
                    <div className="section-divider" style={{ margin: "8px 0" }} />
                    <div className="form-group">
                      <label>Add Quick Enemy</label>
                      <input value={encounterDraft.quick_enemy_name} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_name: e.target.value }))} placeholder="Enemy name" />
                    </div>
                    <div className="dual-grid">
                      <div className="form-group">
                        <label>HP</label>
                        <input type="number" value={encounterDraft.quick_enemy_hp} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_hp: e.target.value }))} />
                      </div>
                      <div className="form-group">
                        <label>AC</label>
                        <input type="number" value={encounterDraft.quick_enemy_ac} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_ac: e.target.value }))} />
                      </div>
                    </div>
                    <div className="form-group">
                      <label>Initiative Bonus</label>
                      <input type="number" value={encounterDraft.quick_enemy_initiative_bonus} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_initiative_bonus: e.target.value }))} />
                    </div>
                    <div className="form-group">
                      <label>Quick Enemy Side</label>
                      <select value={encounterDraft.quick_enemy_side} onChange={(e) => setEncounterDraft((p) => ({ ...p, quick_enemy_side: e.target.value }))}>
                        <option value="enemy">enemy</option>
                        <option value="party">party</option>
                        <option value="ally">ally</option>
                      </select>
                    </div>
                    <button className="btn-secondary" onClick={addQuickEnemy}>Add Enemy To Encounter</button>
                  </div>
                </div>
                <div className="panel-card">
                  <h3>Combat Actions</h3>
                  <div className="timeline-list">
                    <div className="timeline-item">
                      <div className="timeline-summary">Current Turn</div>
                      <div className="timeline-content">
                        {encounterSummary.active ? `${encounterSummary.current_actor_name || "Unknown"} (${encounterSummary.current_actor_side || "?"})` : "No active encounter."}
                      </div>
                      {encounterSummary.active && currentActorEntry?.type === "character" && currentActorEntry?.resources && Object.keys(currentActorEntry.resources).length > 0 && (
                        <div className="timeline-content">
                          {Object.entries(currentActorEntry.resources).map(([name, resource]) => `${name} ${resource.current_value}/${resource.max_value}`).join(" · ")}
                        </div>
                      )}
                      {encounterSummary.active && currentActorEntry?.attacks?.length > 0 && (
                        <div className="timeline-content">
                          Attacks: {currentActorEntry.attacks.map((attack) => attack.name).join(" · ")}
                        </div>
                      )}
                      {encounterSummary.active && currentActorEntry?.side === "enemy" && (
                        <div className="timeline-content">
                          Enemy turns stay DM-controlled. The UI only enforces turn order and resource limits.
                        </div>
                      )}
                    </div>
                    <button className="btn-secondary" onClick={handleCurrentActorAttackLoad} disabled={!currentActorEntry}>Load Current Actor</button>
                    <button className="btn-primary" onClick={() => runAction("advance")} disabled={advanceTurnDisabled}>Advance Turn</button>
                    <div className="action-grid">
                      <select value={actionDraft.attack.attacker_ref} onChange={(e) => handleAttackActorChange(e.target.value)}>
                        <option value="">Attacker</option>
                        {actorList.map((actor) => <option key={`atk-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.attack.attack_name} onChange={(e) => handleAttackOptionChange(e.target.value)} disabled={!actionDraft.attack.attacker_ref || attackChoices.length === 0}>
                        <option value="">{actionDraft.attack.attacker_ref ? "Attack option" : "Choose attacker first"}</option>
                        {attackChoices.map((attack) => <option key={`${actionDraft.attack.attacker_ref}-${attack.name}`} value={attack.name}>{formatAttackOption(attack)}</option>)}
                      </select>
                      <select value={actionDraft.attack.target_ref} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, target_ref: e.target.value } }))}>
                        <option value="">Target</option>
                        {actorList.map((actor) => <option key={`tgt-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <input value={actionDraft.attack.attack_bonus} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, attack_bonus: e.target.value } }))} placeholder="Attack bonus" readOnly={attackMetadataLocked} />
                      <input value={actionDraft.attack.damage_expression} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, damage_expression: e.target.value } }))} placeholder="Damage" readOnly={attackMetadataLocked} />
                      <input value={actionDraft.attack.damage_type} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, damage_type: e.target.value } }))} placeholder="Damage type" readOnly={attackMetadataLocked} />
                      <select value={actionDraft.attack.resolution_mode} onChange={(e) => setActionDraft((p) => ({ ...p, attack: { ...p.attack, resolution_mode: e.target.value } }))}>
                        {ATTACK_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                      <button className="btn-secondary" onClick={() => runAction("attack")} disabled={attackButtonDisabled}>Attack</button>
                    </div>
                    {attackTurnLocked && <div className="timeline-content">Attack is locked because it is not the selected actor's turn.</div>}
                    {attackMetadataLocked && <div className="timeline-content">Using {formatAttackSource(attackChoices.find((attack) => attack.name === actionDraft.attack.attack_name)?.source)} metadata from action-options for {actionDraft.attack.attack_name}. Resolution mode can still switch between normal, nonlethal, and capture.</div>}
                    {attackActor && attackChoices.length === 0 && <div className="timeline-content">No parsed attack options are available for this actor yet. Manual attack fields stay enabled as a fallback.</div>}
                    <div className="action-grid">
                      <select value={actionDraft.spell.caster_ref} onChange={(e) => handleSpellCasterChange(e.target.value)}>
                        <option value="">Caster</option>
                        {charActors.map((actor) => <option key={`spell-${actor.ref}`} value={actor.ref}>{actor.name}</option>)}
                      </select>
                      <select value={actionDraft.spell.spell_name} onChange={(e) => handleSpellOptionChange(e.target.value)}>
                        <option value="">Spell</option>
                        {spellOptions.map((spell) => <option key={spell.name} value={spell.name}>{spell.label}</option>)}
                      </select>
                      <input value={actionDraft.spell.slot_level} onChange={(e) => setActionDraft((p) => ({ ...p, spell: { ...p.spell, slot_level: e.target.value } }))} placeholder="Slot" disabled={!selectedSpellOption?.requires_slot} />
                      <button className="btn-secondary" onClick={() => runAction("spell")} disabled={castButtonDisabled}>Cast</button>
                    </div>
                    {spellTurnLocked && <div className="timeline-content">Spellcasting is locked because it is not this character's turn.</div>}
                    {selectedSpellOption && !selectedSpellOption.available && selectedSpellOption.requires_slot && <div className="timeline-content">No spell slots remain for {selectedSpellOption.name}.</div>}
                    <div className="action-grid">
                      <select value={actionDraft.skill.actor_ref} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, actor_ref: e.target.value } }))}>
                        <option value="">Actor</option>
                        {actorList.map((actor) => <option key={`skill-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.skill.skill_name} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, skill_name: e.target.value } }))}>
                        <option value="">Skill</option>
                        {(skillActor?.skills || []).map((skill) => <option key={skill} value={skill}>{skill}</option>)}
                      </select>
                      <input value={actionDraft.skill.dc} onChange={(e) => setActionDraft((p) => ({ ...p, skill: { ...p.skill, dc: e.target.value } }))} placeholder="DC" />
                      <button className="btn-secondary" onClick={() => runAction("skill")} disabled={!actionDraft.skill.actor_ref || !actionDraft.skill.skill_name || skillTurnLocked}>Skill</button>
                    </div>
                    {skillTurnLocked && <div className="timeline-content">Skill checks are locked because it is not this actor's turn.</div>}
                    <div className="action-grid">
                      <select value={actionDraft.save.target_ref} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, target_ref: e.target.value } }))}>
                        <option value="">Target</option>
                        {actorList.map((actor) => <option key={`save-${actor.value}`} value={actor.value}>{actor.label}</option>)}
                      </select>
                      <select value={actionDraft.save.save_name} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, save_name: e.target.value } }))}>
                        <option value="">Save</option>
                        {(saveTargetActor?.saves || []).map((saveName) => <option key={saveName} value={saveName}>{saveName}</option>)}
                      </select>
                      <input value={actionDraft.save.dc} onChange={(e) => setActionDraft((p) => ({ ...p, save: { ...p.save, dc: e.target.value } }))} placeholder="DC" />
                      <button className="btn-secondary" onClick={() => runAction("save")} disabled={!actionDraft.save.target_ref || !actionDraft.save.save_name}>Save</button>
                    </div>
                    <div className="action-grid">
                      <select value={actionDraft.item.user_ref} onChange={(e) => handleItemUserChange(e.target.value)}>
                        <option value="">User</option>
                        {charActors.map((actor) => <option key={`item-${actor.ref}`} value={actor.ref}>{actor.name}</option>)}
                      </select>
                      <select value={actionDraft.item.item_name} onChange={(e) => setActionDraft((p) => ({ ...p, item: { ...p.item, item_name: e.target.value } }))}>
                        <option value="">Item</option>
                        {(itemActor?.items || []).map((item) => <option key={item.name} value={item.name}>{`${item.name} (${item.quantity})`}</option>)}
                      </select>
                      <input value={actionDraft.item.quantity} onChange={(e) => setActionDraft((p) => ({ ...p, item: { ...p.item, quantity: e.target.value } }))} placeholder="Qty" />
                      <button className="btn-secondary" onClick={() => runAction("item")} disabled={useItemDisabled}>Use</button>
                    </div>
                    {itemTurnLocked && <div className="timeline-content">Item use is locked because it is not this character's turn.</div>}
                    {selectedItemOption && Number(actionDraft.item.quantity || 1) > Number(selectedItemOption.quantity || 0) && <div className="timeline-content">Not enough quantity remaining for {selectedItemOption.name}.</div>}
                  </div>
                </div>
                <div className="panel-card">
                  <h3>Timeline</h3>
                  <div className="timeline-list">
                    {timeline.map((event) => <div key={event.event_id} className="timeline-item"><div className="timeline-type">{eventLabel(event.type)}</div><div className="timeline-summary">{event.summary}</div>{event.content && <div className="timeline-content">{event.content}</div>}</div>)}
                  </div>
                </div>
                <div className="panel-card">
                  <h3>Encounter</h3>
                  {!encounter ? <p className="empty-text">No active encounter.</p> : <div className="combatant-list">{combatants.map((combatant) => <div key={combatant.combatant_id} className={`combatant-item ${encounter.current_combatant_id === combatant.combatant_id ? "combatant-active" : ""}`}><div className="timeline-summary">{combatant.name} · {combatant.side}</div><div className="timeline-content">HP {combatant.hp_current}/{combatant.hp_max} · AC {combatant.ac} · INIT {combatant.initiative ?? "?"}</div><div className="action-grid" style={{ marginTop: 10 }}><input value={initiativeDrafts[combatant.combatant_id] ?? ""} onChange={(e) => setInitiativeDrafts((prev) => ({ ...prev, [combatant.combatant_id]: e.target.value }))} placeholder="Initiative" /><button className="btn-secondary" onClick={() => saveEncounterInitiative(combatant.combatant_id)}>Set Init</button><button className="btn-secondary" onClick={() => rerollEncounterInitiative(combatant.combatant_id)}>Roll Init</button></div>{!combatant.linked_character_id && <div className="btn-row" style={{ marginTop: 10 }}><button className="btn-danger" onClick={() => dropEncounterCombatant(combatant.combatant_id)}>Remove</button></div>}</div>)}</div>}
                </div>
              </div>
            </div>
            <div className="input-area">
              <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder={gameState?.campaign?.phase === "adventure_selection" ? "Choose an adventure first." : "Describe your action..."} disabled={gameState?.campaign?.phase === "adventure_selection"} />
              <button onClick={sendMessage} disabled={gameState?.campaign?.phase === "adventure_selection"}>SEND</button>
            </div>
          </div>
        )}


        {view === "status" && <div className="status-screen anime-fade-in"><h2>Party</h2><div className="status-cards">{Object.values(gameState?.characters || {}).map((character) => <div key={character.character_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">🧙</div><div><h3>{character.name}</h3><span className="badge">{character.class_name} Lv.{character.level}</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${character.hp_max > 0 ? (character.hp_current / character.hp_max) * 100 : 0}%` }}></div><span className="text">{character.hp_current}/{character.hp_max} HP</span></div><div className="timeline-content">Gold {formatGoldLine(character.gold_gp)}</div></div>)}</div><h2 style={{ marginTop: 32 }}>Encounter</h2><div className="status-cards">{combatants.length === 0 && <p className="empty-text">No combatants.</p>}{combatants.map((combatant) => <div key={combatant.combatant_id} className="char-stat-card"><div className="char-header"><div className="avatar-lg">{combatant.side === "enemy" ? "🐉" : "🧙"}</div><div><h3>{combatant.name}</h3><span className="badge">{combatant.side} · INIT {combatant.initiative ?? "?"}</span></div></div><div className="hp-bar"><div className="fill" style={{ width: `${combatant.hp_max > 0 ? (combatant.hp_current / combatant.hp_max) * 100 : 0}%` }}></div><span className="text">{combatant.hp_current}/{combatant.hp_max} HP</span></div></div>)}</div></div>}
      </main>
    </div>
  );
}
