import React from "react";
import DescriptionTooltip from "../DescriptionTooltip";
import { IconAdventurer, IconTome } from "./Icons";
import {
  ABILITY_METHOD_LABELS,
  STATS,
  formatAbilityModifier,
  formatAttackSummary,
  formatEquipmentLine,
  formatSigned,
  formatSpellSlotStatus,
  localizeAlignment,
  localizeBackgroundName,
  localizeClassName,
  localizeClassResource,
  localizeDefeatState,
  localizeEquipmentMode,
  localizeEquipmentType,
  localizeName,
  localizeOriginFeat,
  localizeSkill,
  localizeSpeciesName,
  localizeSpellcastingMode,
  localizeStat,
} from "../dndLabels";

export function SpellNames({ names, options = [] }) {
  return names.map((name, index) => {
    const spell = options.find((option) => [option.name, option.nameEN, option.name_display].includes(name)) || {};
    const metadata = [
      spell.level === 0 ? "戏法" : spell.level != null ? `${spell.level} 环` : "",
      spell.school_display || spell.school,
      spell.casting_time && `施法时间：${spell.casting_time}`,
      spell.range && `距离：${spell.range}`,
      spell.duration && `持续：${spell.duration}`,
      spell.components && `成分：${spell.components}`,
      spell.concentration && "需要专注",
      spell.ritual && "仪式",
    ];
    return (
      <React.Fragment key={name}>
        {index > 0 && "、"}
        <DescriptionTooltip
          label={localizeName(name)}
          description={spell.description_display || spell.description}
          metadata={metadata}
          extra={spell.higher_levels}
        />
      </React.Fragment>
    );
  });
}

export default function CharacterSheetDetail({ character }) {
  if (!character) {
    return (
      <div className="character-sheet-empty">
        <div className="empty-emblem">
          <IconTome size={28} />
        </div>
        <h2>选择一张角色卡</h2>
        <p className="info-text">从左侧名册中选择冒险者，展开完整的 D&amp;D 2024 角色卷宗。</p>
      </div>
    );
  }

  const stats = character.stats || {};
  const resources = Object.entries(character.resources || {});
  const inventory = character.inventory || [];
  const attacks = inventory.filter((item) => item.type === "weapon" && item.quantity > 0);
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
        <div className="sheet-sigil" aria-hidden="true">
          <IconAdventurer size={34} />
        </div>
        <div className="character-sheet-headline">
          <p className="eyebrow">D&amp;D 2024 角色卡典藏卷宗</p>
          <h1>{character.name}</h1>
          <p>
            {localizeSpeciesName(character.species || character.race)} ·{" "}
            {localizeBackgroundName(character.background_name || character.background)} ·{" "}
            {character.class_name_display || localizeClassName(character.class_name)} {character.level}级
            {character.subclass_name ? `（${character.subclass_name}）` : ""}
          </p>
        </div>
      </header>

      <section className="sheet-vital-strip" aria-label="核心战斗指标">
        <div className="vital-cell vital-hp">
          <span>生命值</span>
          <strong>
            {character.hp_current}/{character.hp_max}
          </strong>
        </div>
        <div className="vital-cell">
          <span>临时生命</span>
          <strong>{character.temp_hp || 0}</strong>
        </div>
        <div className="vital-cell">
          <span>护甲等级 (AC)</span>
          <strong>{character.ac}</strong>
        </div>
        <div className="vital-cell">
          <span>移动速度</span>
          <strong>{character.speed} 尺</strong>
        </div>
        <div className="vital-cell">
          <span>先攻加值</span>
          <strong>{formatSigned(character.initiative_bonus)}</strong>
        </div>
      </section>

      <div className="character-sheet-grid">
        <section className="sheet-panel ability-panel">
          <h3>六维属性</h3>
          <div className="ability-score-grid">
            {STATS.map((stat) => (
              <div key={stat} className="ability-score">
                <span>{localizeStat(stat)}</span>
                <strong>{stats[stat] ?? 10}</strong>
                <em>{formatAbilityModifier(stats[stat])}</em>
              </div>
            ))}
          </div>
          <p className="sheet-panel-note">
            生成方式：{ABILITY_METHOD_LABELS[character.ability_generation_method || "point_buy"] || character.ability_generation_method}
          </p>
        </section>

        <section className="sheet-panel identity-panel">
          <h3>身份与状态</h3>
          <div className="sheet-data-grid">
            <div>
              <span>等级</span>
              <strong>{character.level || 1}级</strong>
            </div>
            {character.subclass_name && (
              <div>
                <span>子职业</span>
                <strong>{character.subclass_name}</strong>
              </div>
            )}
            <div>
              <span>阵营</span>
              <strong>{character.alignment_display || localizeAlignment(character.alignment) || "未说明"}</strong>
            </div>
            <div>
              <span>起源专长</span>
              <strong>{localizeOriginFeat(character.origin_feat) || "未记录"}</strong>
            </div>
            <div>
              <span>经验值</span>
              <strong>{character.experience_points || 0}</strong>
            </div>
            <div>
              <span>英雄激励</span>
              <strong>{character.inspiration ? "有" : "无"}</strong>
            </div>
            <div>
              <span>当前状态</span>
              <strong>{localizeDefeatState(character.defeat_state)}</strong>
            </div>
          </div>
          {statuses.length > 0 && (
            <div className="tags sheet-tags">
              {statuses.map((status) => (
                <span key={status} className="tag">
                  {status}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="sheet-panel">
          <h3>技能与豁免熟练</h3>
          {skills.length === 0 && saves.length === 0 ? (
            <p className="empty-text">没有记录熟练项。</p>
          ) : (
            <>
              {skills.length > 0 && (
                <p className="timeline-content">
                  <strong>技能：</strong>
                  {skills.map(([skill, rank]) => `${localizeSkill(skill)}${Number(rank) === 2 ? "（专精）" : ""}`).join("、")}
                </p>
              )}
              {saves.length > 0 && (
                <p className="timeline-content">
                  <strong>豁免：</strong>
                  {saves.map(([save]) => localizeStat(save)).join("、")}
                </p>
              )}
            </>
          )}
        </section>

        {character.class_features?.length > 0 && (
          <section className="sheet-panel">
            <h3>职业特性</h3>
            <div className="feature-pill-list">
              {character.class_features.map((feature, index) => (
                <div className="timeline-content feature-line" key={`${feature.name}-${index}`}>
                  <span className="feature-level-tag">{feature.level}级</span>
                  <span>{feature.name_display || feature.name}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="sheet-panel">
          <h3>职业资源</h3>
          {resources.length === 0 ? (
            <p className="empty-text">没有可追踪资源。</p>
          ) : (
            resources.map(([name, resource]) => (
              <div key={name} className="sheet-row">
                <DescriptionTooltip
                  label={resource.display_name || localizeClassResource(name)}
                  description={resource.rules_text || resource.description_display || resource.description}
                  metadata={[resource.rules_source].filter(Boolean)}
                />
                <strong>
                  {resource.current_value}/{resource.max_value}
                </strong>
              </div>
            ))
          )}
        </section>

        <section className="sheet-panel">
          <h3>武器与攻击</h3>
          {attacks.length === 0 ? (
            <p className="empty-text">没有记录武器或攻击项。</p>
          ) : (
            attacks.map((attack, index) => (
              <div key={`${attack.name}-${index}`} className="attack-card">
                <strong>{attack.name_display || attack.name}</strong>
                <span>{formatAttackSummary(attack) || "攻击资料未完整记录"}</span>
                {(attack.properties_display || attack.properties)?.length > 0 && (
                  <small>{(attack.properties_display || attack.properties).join("、")}</small>
                )}
              </div>
            ))
          )}
        </section>

        <section className="sheet-panel">
          <h3>法术能力</h3>
          {cantrips.length === 0 && prepared.length === 0 && slots.length === 0 ? (
            <p className="empty-text">该角色没有记录法术。</p>
          ) : (
            <>
              <div className="sheet-data-grid compact">
                <div>
                  <span>施法属性</span>
                  <strong>{localizeStat(spells.ability)}</strong>
                </div>
                <div>
                  <span>施法方式</span>
                  <strong>{localizeSpellcastingMode(spells.casting_mode)}</strong>
                </div>
              </div>
              {slots.length > 0 && (
                <div className="tags sheet-tags">
                  {slots.map((slot) => (
                    <span key={slot[0]} className="tag">
                      {formatSpellSlotStatus(slot)}
                    </span>
                  ))}
                </div>
              )}
              {cantrips.length > 0 && (
                <p className="timeline-content">
                  <strong>戏法：</strong>
                  <SpellNames names={cantrips.map(localizeName)} options={spells.options} />
                </p>
              )}
              {prepared.length > 0 && (
                <p className="timeline-content">
                  <strong>准备：</strong>
                  <SpellNames names={prepared.map(localizeName)} options={spells.options} />
                </p>
              )}
            </>
          )}
        </section>

        <section className="sheet-panel inventory-panel">
          <h3>行囊与物品栏</h3>
          {inventory.length === 0 ? (
            <p className="empty-text">没有记录物品。</p>
          ) : (
            inventory.map((item, index) => (
              <div key={`${item.name}-${index}`} className="inventory-card">
                <div>
                  <strong>
                    <DescriptionTooltip
                      label={item.name_display || item.name}
                      description={item.description_display || item.description || item.notes_display || item.notes}
                      metadata={[item.type_display || localizeEquipmentType(item.type)]}
                    />
                  </strong>
                  <span>{formatEquipmentLine(item) || item.type_display || localizeEquipmentType(item.type)}</span>
                </div>
                <em>x{item.quantity || 1}</em>
                {item.effect_summary && <p className="item-effect-summary">{item.effect_summary}</p>}
                {item.notes && <p>{item.notes}</p>}
                {(item.tags_display || item.tags)?.length > 0 && (
                  <small>{(item.tags_display || item.tags).join("、")}</small>
                )}
              </div>
            ))
          )}
        </section>

        <section className="sheet-panel">
          <h3>起始行装方案</h3>
          <div className="sheet-data-grid">
            <div>
              <span>职业套装</span>
              <strong>{character.starter_option_id ? "已选择" : "未记录"}</strong>
            </div>
            <div>
              <span>装备方式</span>
              <strong>{localizeEquipmentMode(character.equipment_mode)}</strong>
            </div>
          </div>
          {starterChoices.length > 0 && <p className="timeline-content">套装选择：已记录 {starterChoices.length} 项</p>}
          {character.custom_purchase_items?.length > 0 && (
            <p className="timeline-content">自定义购买：已记录 {character.custom_purchase_items.length} 项</p>
          )}
          {character.custom_pending_item?.name && (
            <p className="timeline-content">待定装备：{character.custom_pending_item.name}</p>
          )}
        </section>

        <section className="sheet-panel experiences-panel">
          <h3>重要经历</h3>
          {experiences.length === 0 ? (
            <p className="empty-text">还没有记录重要经历。</p>
          ) : (
            experiences.map((entry, index) => (
              <p key={`${entry}-${index}`} className="timeline-content">
                {entry}
              </p>
            ))
          )}
        </section>
      </div>
    </article>
  );
}
