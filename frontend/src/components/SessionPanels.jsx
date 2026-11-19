import React, { useEffect, useState } from "react";
import DescriptionTooltip from "../DescriptionTooltip";
import { rollOutcomeLabel, rollSettlementLabel } from "../rollUi";
import { SpellNames } from "./CharacterSheetDetail";
import { IconD20, IconSwords } from "./Icons";
import MarkdownBlock from "./MarkdownBlock";
import {
  SHOW_DM_CONTROLS_IN_PLAYER_SESSION,
  STATS,
  asMarkdownQuote,
  eventContent,
  eventLabel,
  eventSummary,
  formatAbilityModifier,
  formatAttackSummary,
  formatCombatantStateLine,
  formatEquipmentLine,
  formatHpBarLabel,
  formatResourceRecovery,
  formatSigned,
  formatSpellSlotStatus,
  localizeClassName,
  localizeClassResource,
  localizeDefeatState,
  localizeEquipmentType,
  localizeName,
  localizeSide,
  localizeSkill,
  localizeStat,
} from "../dndLabels";

export function RollLedger({ records = [], recorded = true }) {
  const hidden = records.filter((record) => record.visibility === "hidden").length;
  const labels = {
    dice: "掷骰",
    attack: "攻击检定",
    damage: "伤害",
    skill: "技能检定",
    save: "豁免",
    initiative: "先攻",
    ability: "属性骰",
  };
  return (
    <details className="turn-roll-ledger">
      <summary>
        <span className="roll-ledger-title">
          <IconD20 size={14} />
          <span>本轮骰点</span>
        </span>
        <small>{recorded ? `${records.length} 次${hidden ? ` · 含 ${hidden} 次暗骰` : ""}` : "未记录"}</small>
      </summary>
      {records.length === 0 ? (
        <p className="roll-empty">{recorded ? "本轮没有执行掷骰。" : "此回合没有保存逐次骰点记录。"}</p>
      ) : (
        <ol className="roll-record-list">
          {records.map((record) => (
            <li key={record.record_id} className="roll-record">
              <div className="roll-record-heading">
                <strong>
                  {record.actor ? `${record.actor} · ` : ""}
                  {record.kind === "skill"
                    ? localizeSkill(record.label)
                    : record.kind === "save"
                      ? `${localizeStat(record.label)}豁免`
                      : record.label || labels[record.kind] || "掷骰"}
                </strong>
                <span className={`roll-visibility ${record.visibility}`}>
                  {record.visibility === "hidden" ? "暗骰" : "明骰"}
                </span>
              </div>
              {record.target && <div className="roll-record-context">目标：{record.target}</div>}
              <div className="roll-equation">
                <code>{record.expression}</code>
                <span>{record.detail || `[${record.dice.join(", ")}]`}</span>
                <strong>= {record.total}</strong>
              </div>
              <div className="roll-record-context">
                {record.roll_mode === "advantage" ? "优势 · " : record.roll_mode === "disadvantage" ? "劣势 · " : ""}
                {record.dc != null ? `目标值 ${record.dc} · ` : ""}
                {rollOutcomeLabel(record) && <strong className="roll-outcome">{rollOutcomeLabel(record)} · </strong>}
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

export function DmThinkingPanel({ thinking, onToggle }) {
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
  const title = isRunning ? "主持人处理中…" : isError ? "主持过程" : isWaiting ? "等待你的选择" : "主持过程";
  const elapsed = thinking.startedAt ? Math.max(0, Math.floor((now - thinking.startedAt) / 1000)) : 0;
  const statusLabel = isRunning ? `${elapsed} 秒` : isError ? "已中断" : isWaiting ? "待继续" : "已完成";
  const activity = thinking.waitingForModel
    ? `正在等待主持模型${thinking.segmentCount > 1 ? `的第 ${thinking.segmentCount} 次响应` : "响应"}，继续判断和组织剧情。`
    : "正在处理行动和规则结算。";
  const body =
    thinking.output ||
    (isRunning ? "模型尚未输出公开的过程说明或剧情文本。" : "本轮没有额外的公开过程文本。");

  return (
    <section className={`dm-thinking-panel thinking-${thinking.status}`} aria-label="主持人的思考过程">
      <button
        type="button"
        className="dm-thinking-toggle"
        aria-expanded={thinking.expanded}
        aria-controls="dm-thinking-output"
        onClick={onToggle}
      >
        <span className={`dm-thinking-chevron ${thinking.expanded ? "expanded" : ""}`} aria-hidden="true">
          ›
        </span>
        <span className="dm-thinking-title">{title}</span>
        <span className="dm-thinking-status" role="status" aria-live="polite">
          {statusLabel}
        </span>
      </button>
      {isError && thinking.errorMessage && (
        <p className="dm-inline-error" role="alert">
          {thinking.errorMessage}
        </p>
      )}
      {isRunning && thinking.retryMessage && (
        <p className="dm-reconnect-status" role="status">
          {thinking.retryMessage}
        </p>
      )}
      {thinking.expanded && (
        <div
          id="dm-thinking-output"
          className="dm-thinking-output markdown-body"
          data-streamed-chars={thinking.output.length}
        >
          {isRunning && (
            <p className="dm-current-activity" role="status">
              {activity}
              {elapsed >= 45 ? " 等待较久，连接仍由心跳检查；请勿重复发送。" : ""}
            </p>
          )}
          <MarkdownBlock>{asMarkdownQuote(body)}</MarkdownBlock>
        </div>
      )}
    </section>
  );
}

export function TimelinePanel({ timeline, title = "时间线", emptyText = "还没有记录。" }) {
  return (
    <section className="panel-card timeline-panel">
      <div className="panel-heading">
        <h3>{title}</h3>
        <span>{timeline.length} 条记录</span>
      </div>
      <div className="timeline-list">
        {timeline.length === 0 && <p className="empty-text">{emptyText}</p>}
        {timeline.map((event) => {
          const content = eventContent(event);
          return (
            <div key={event.event_id} className="timeline-item">
              <div className="timeline-type">{eventLabel(event.type)}</div>
              <div className="timeline-summary">{eventSummary(event)}</div>
              {content && (
                <div className="timeline-content markdown-body">
                  <MarkdownBlock>{content}</MarkdownBlock>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function EvidencePanel({ evidence = [] }) {
  return (
    <section className="panel-card timeline-panel">
      <div className="panel-heading">
        <h3>线索与证据</h3>
        <span>{evidence.length} 条</span>
      </div>
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

export function KnownWorldPanel({ entries = [] }) {
  if (!entries.length) return null;
  return (
    <section className="panel-card timeline-panel">
      <div className="panel-heading">
        <h3>战役见闻</h3>
        <span>{entries.length} 项</span>
      </div>
      <div className="timeline-list">
        {entries.map(({ id, title, summary }) => (
          <div key={id} className="timeline-item">
            <div className="timeline-summary">{title}</div>
            <div className="timeline-content">{summary}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CombatStatusStrip({ entries = [], name, loading = false }) {
  const labels = { buff: "增益", debuff: "减益", concentration: "专注", status: "状态" };
  return (
    <aside className="combat-status-strip" aria-label={`${name}当前状态`}>
      {loading ? (
        <span className="combat-status-empty">状态待同步</span>
      ) : entries.length === 0 ? (
        <span className="combat-status-empty">暂无状态记录</span>
      ) : (
        entries.map((entry) => (
          <div key={entry.id} className={`combat-status-entry status-${entry.kind}`}>
            <span className="combat-status-kind">{labels[entry.kind] || "状态"}</span>
            <div>
              <DescriptionTooltip
                label={entry.name}
                description={entry.description}
                metadata={[entry.source].filter(Boolean)}
              />
              {entry.summary && <div className="combat-status-summary">{entry.summary}</div>}
              {entry.source && <div className="combat-status-source">{entry.source}</div>}
            </div>
          </div>
        ))
      )}
    </aside>
  );
}

export function SceneActorPanel({ actors = [], ready = true }) {
  const visible = actors.filter((actor) => actor.scene_actor && actor.status_entries?.length > 0);
  if (visible.length === 0) return null;
  return (
    <section className="side-section">
      <div className="side-section-header">
        <h3>场景人物状态</h3>
        <span>{visible.length} 人</span>
      </div>
      <div className="timeline-list">
        {visible.map((actor) => (
          <div key={actor.ref} className="timeline-item">
            <strong>{actor.name}</strong>
            <CombatStatusStrip name={actor.name} entries={actor.status_entries} loading={!ready} />
          </div>
        ))}
      </div>
    </section>
  );
}

export function CombatantPanel({
  encounter,
  combatants,
  statusByRef = {},
  statusReady = true,
  initiativeDrafts,
  setInitiativeDrafts,
  saveEncounterInitiative,
  rerollEncounterInitiative,
  dropEncounterCombatant,
  localActionsLocked = false,
}) {
  const nextActorId = encounter?.active && encounter?.turn_order_started ? encounter.current_combatant_id : null;
  return (
    <section className="side-section combat-panel">
      <div className="side-section-header">
        <h3>
          <IconSwords size={15} className="inline-section-icon" /> 场上形势
        </h3>
        {encounter?.active && (
          <span className="combat-round-pill">
            {encounter.turn_order_started ? `第 ${encounter.round_number} 轮` : "先攻准备"}
          </span>
        )}
      </div>
      {!encounter?.active ? (
        <p className="empty-text">当前没有战斗。</p>
      ) : (
        <div className="combatant-list" aria-label="先攻行动顺序">
          <p className="combat-order-hint">
            {!encounter.active
              ? "本次战斗已结束"
              : encounter.turn_order_started
                ? `第 ${encounter.round_number} 轮 · 按先攻顺序`
                : "等待先攻确定"}
          </p>
          {combatants.map((combatant, index) => {
            const hpPct =
              combatant.hp_max > 0 ? Math.max(0, Math.min(100, (combatant.hp_current / combatant.hp_max) * 100)) : 0;
            return (
              <div
                key={combatant.combatant_id}
                className={`combatant-item side-${combatant.side || "enemy"} ${
                  nextActorId === combatant.combatant_id ? "combatant-active" : ""
                }`}
                aria-current={nextActorId === combatant.combatant_id ? "step" : undefined}
              >
                <div className="timeline-summary combatant-heading">
                  <span>
                    <span className="combat-order-number">{index + 1}</span>
                    {combatant.name} · {localizeSide(combatant.side)}
                  </span>
                  {nextActorId === combatant.combatant_id && (
                    <span className="combatant-turn-badge" title="下一次对话从该行动者继续">
                      接下来行动
                    </span>
                  )}
                </div>
                <div className="combatant-mini-hp" aria-hidden="true">
                  <div className="combatant-mini-hp-fill" style={{ width: `${hpPct}%` }} />
                </div>
                <div className="timeline-content">{formatCombatantStateLine(combatant)}</div>
                <CombatStatusStrip
                  name={combatant.name}
                  entries={statusByRef[combatant.linked_character_id || combatant.combatant_id]}
                  loading={!statusReady}
                />
                {combatant.surprised_at_start && (
                  <div className="timeline-content combatant-flag">开战时被突袭 · 仅影响先攻</div>
                )}
                {combatant.initiative_roll_mode && combatant.initiative_roll_mode !== "normal" && (
                  <div className="timeline-content combatant-flag">
                    先攻{combatant.initiative_roll_mode === "advantage" ? "优势" : "劣势"}
                  </div>
                )}
                {SHOW_DM_CONTROLS_IN_PLAYER_SESSION && (
                  <fieldset
                    className="pending-action-scope"
                    disabled={localActionsLocked}
                    aria-label="先攻和战斗单位操作"
                  >
                    <div className="action-grid" style={{ marginTop: 10 }}>
                      <input
                        value={initiativeDrafts[combatant.combatant_id] ?? ""}
                        onChange={(e) =>
                          setInitiativeDrafts((prev) => ({ ...prev, [combatant.combatant_id]: e.target.value }))
                        }
                        placeholder="先攻"
                      />
                      <button className="btn-secondary" onClick={() => saveEncounterInitiative(combatant.combatant_id)}>
                        设置先攻
                      </button>
                      <button
                        className="btn-secondary"
                        onClick={() => rerollEncounterInitiative(combatant.combatant_id)}
                      >
                        重掷先攻
                      </button>
                    </div>
                    {!combatant.linked_character_id && (
                      <div className="btn-row" style={{ marginTop: 10 }}>
                        <button className="btn-danger" onClick={() => dropEncounterCombatant(combatant.combatant_id)}>
                          移除
                        </button>
                      </div>
                    )}
                  </fieldset>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function TurnActionResources({ character, actor, encounter }) {
  const inCombat = Boolean(encounter?.active);
  const combatant = Object.values(encounter?.combatants || {}).find(
    (entry) => entry.linked_character_id === character.character_id,
  );
  const ownTurn = Boolean(combatant && encounter?.current_combatant_id === combatant.combatant_id);
  const slots = [
    { label: "动作", used: encounter?.turn_action_used },
    { label: "附赠动作", used: encounter?.turn_bonus_action_used },
    { label: "反应", used: combatant && encounter?.reactions_used?.[combatant.combatant_id], reaction: true },
  ];
  return (
    <section className="sheet-section turn-resources" aria-label="行动额度">
      <h4>
        行动额度 <span>{inCombat ? "剩余 / 基础额度" : "战斗中的基础额度"}</span>
      </h4>
      <div className="turn-resource-grid">
        {slots.map((slot) => {
          let value = "1 次";
          let note = "每次自己的回合";
          let stateClass = "ready";
          if (inCombat) {
            value = "— / 1";
            stateClass = "waiting";
            if (!encounter.turn_order_started) note = "等待先攻";
            else if (!combatant || !actor) note = "等待状态";
            else if (!actor.can_act) {
              value = "0 / 1";
              note = "无法行动";
              stateClass = "spent";
            }
            // turn_* 是当前行动者的槽位，不能当作非当前角色的剩余量。
            else if (!ownTurn && !slot.reaction) {
              note = "等待回合";
              stateClass = "waiting";
            } else {
              value = slot.used ? "0 / 1" : "1 / 1";
              note = slot.used ? "已使用" : slot.reaction ? "需满足触发条件" : "可用";
              stateClass = slot.used ? "spent" : "ready";
            }
          }
          return (
            <div className={`turn-resource is-${stateClass}`} key={slot.label}>
              <span>{slot.label}</span>
              <strong>{value}</strong>
              <small>{note}</small>
            </div>
          );
        })}
      </div>
      <p className="turn-resource-note">在自己回合开始时恢复。附赠动作与反应需有对应能力或触发条件。</p>
    </section>
  );
}

export function CharacterStatusCard({
  character,
  actor,
  encounter,
  primary = false,
  onToggleControl,
  controlDisabled,
  statusReady = true,
}) {
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
    <details
      className={`party-card ${primary ? "party-card-primary" : ""}`}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="avatar">{primary ? "主" : "伴"}</span>
        <span className="party-card-title">
          <strong>{character.name}</strong>
          <span>
            {character.class_name_display || localizeClassName(character.class_name)} · {character.level}级
          </span>
        </span>
        {!primary && (
          <button
            type="button"
            className="combat-control-button"
            disabled={controlDisabled}
            aria-label={`${character.name}：${
              actor?.combat_controller === "player" ? "玩家控制，切换为 DM 控制" : "DM 控制，切换为玩家控制"
            }`}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onToggleControl(
                character.character_id,
                actor?.combat_controller === "player" ? "dm" : "player",
              );
            }}
          >
            {actor?.combat_controller === "player" ? "玩家控制" : "DM 控制"}
          </button>
        )}
        <span className="party-card-hp">{formatHpBarLabel(character.hp_current, character.hp_max)}</span>
      </summary>
      <div className="party-card-body">
        <div className="hp-bar">
          <div
            className="fill"
            style={{
              width: `${character.hp_max > 0 ? Math.max(0, Math.min(100, (character.hp_current / character.hp_max) * 100)) : 0}%`,
            }}
          />
          <span className="text">{formatHpBarLabel(character.hp_current, character.hp_max)}</span>
        </div>
        <div className="party-vitals">
          <span>护甲 {character.ac}</span>
          <span>速度 {character.speed}</span>
          <span>先攻 {formatSigned(character.initiative_bonus)}</span>
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
        {(statuses.length > 0 || defeatState !== "active" || character.inspiration || character.hiding) && (
          <div className="tags">
            {character.hiding && (
              <span className="tag" title="攻击、言语施法、被敌人发现或暴露后结束；不等于魔法隐形">
                躲藏中 · 发现 DC {character.hiding.stealth_total}
              </span>
            )}
            {character.inspiration && <span className="tag">激励</span>}
            {defeatState !== "active" && <span className="tag">{localizeDefeatState(defeatState)}</span>}
            {statuses.map((status) => (
              <span key={status} className="tag">
                {status}
              </span>
            ))}
          </div>
        )}
        {(encounter?.active || !statusReady || actor?.status_entries?.length > 0 || character.concentration_spell) && (
          <CombatStatusStrip name={character.name} entries={actor?.status_entries} loading={!statusReady} />
        )}
        <TurnActionResources character={character} actor={actor} encounter={encounter} />
        {resources.length > 0 && (
          <section className="sheet-section">
            <h4>职业资源</h4>
            {resources.map(([name, resource]) => (
              <div key={name} className="class-resource-entry">
                <div className="sheet-row">
                  <DescriptionTooltip
                    label={resource.display_name || localizeClassResource(name)}
                    description={resource.rules_text || resource.description_display || resource.description}
                    metadata={[resource.rules_source].filter(Boolean)}
                  />
                  <strong>
                    {resource.current_value}/{resource.max_value}
                  </strong>
                </div>
                <small>
                  {resource.short_rest_recovery
                    ? `短休恢复 ${resource.short_rest_recovery} 次；长休恢复全部`
                    : `${formatResourceRecovery(resource)}恢复全部`}
                </small>
              </div>
            ))}
          </section>
        )}
        {(cantrips.length > 0 || prepared.length > 0 || slots.length > 0) && (
          <section className="sheet-section">
            <h4>法术</h4>
            {slots.length > 0 && (
              <div className="tags">
                {slots.map((slot) => (
                  <span key={slot[0]} className="tag">
                    {formatSpellSlotStatus(slot)}
                  </span>
                ))}
              </div>
            )}
            {cantrips.length > 0 && (
              <div className="timeline-content">
                戏法：<SpellNames names={cantrips} options={spells.options} />
              </div>
            )}
            {prepared.length > 0 && (
              <div className="timeline-content">
                准备：<SpellNames names={prepared} options={spells.options} />
              </div>
            )}
          </section>
        )}
        {attacks.length > 0 && (
          <section className="sheet-section">
            <h4>攻击</h4>
            {attacks.slice(0, 5).map((attack) => (
              <div key={`${character.character_id}-${localizeName(attack)}`} className="sheet-row">
                <span>{formatAttackSummary(attack)}</span>
              </div>
            ))}
          </section>
        )}
        {character.class_features?.length > 0 && (
          <details className="sheet-section">
            <summary>
              职业特性 · {character.subclass_name || character.class_name} · {character.level}级
            </summary>
            {character.class_features.map((feature, index) => (
              <div className="timeline-content" key={`${feature.name}-${index}`}>
                {feature.level}级 · {feature.name_display || feature.name}
              </div>
            ))}
          </details>
        )}
        {(skills.length > 0 || saves.length > 0) && (
          <section className="sheet-section">
            <h4>熟练</h4>
            {skills.length > 0 && <div className="timeline-content">技能：{skills.map(localizeSkill).join("、")}</div>}
            {saves.length > 0 && <div className="timeline-content">豁免：{saves.map(localizeStat).join("、")}</div>}
          </section>
        )}
        <details
          className="sheet-section inventory-disclosure"
          open={inventoryOpen}
          onToggle={(event) => setInventoryOpen(event.currentTarget.open)}
        >
          <summary>
            <h4>物品栏</h4>
            <span>{inventory.length} 项</span>
          </summary>
          {inventory.length === 0 ? (
            <p className="empty-text">没有记录物品。</p>
          ) : (
            inventory.map((item, index) => (
              <div key={`${character.character_id}-item-${item.name}-${index}`} className="inventory-row">
                <DescriptionTooltip
                  label={item.name_display || item.name}
                  description={item.description_display || item.description || item.notes_display || item.notes}
                  metadata={[item.type_display || localizeEquipmentType(item.type)]}
                />
                <small>
                  {formatEquipmentLine(item) || item.type_display || localizeEquipmentType(item.type)}
                  {item.effect_summary && <span className="item-effect-summary">{item.effect_summary}</span>}
                </small>
              </div>
            ))
          )}
        </details>
      </div>
    </details>
  );
}
