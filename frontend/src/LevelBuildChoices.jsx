const ABILITIES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];

export default function LevelBuildChoices({ profile, draft, setDraft, loading, error, formatSkill, formatStat }) {
  if (!profile) return <p className="info-text" role="status">{error || "正在加载所选等级的规则…"}</p>;
  const selectedExpertise = draft.expertise_skills || [];
  const expertiseOptions = Object.entries(draft.skill_proficiencies || {}).filter(([skill, rank]) => Number(rank) > 0
    && (draft.class_name !== "Wizard" || ["Arcana", "History", "Investigation", "Medicine", "Nature", "Religion"].includes(skill)));
  return <section className="builder-preview-card level-build-choices">
    <h3>{draft.level || 1}级构筑</h3>
    <p className="spell-meta">生命 {profile.hp_max} · 熟练加值 +{profile.proficiency_bonus}</p>
    {loading && <p className="info-text" role="status">正在更新等级预览…</p>}
    {error && <p className="info-text" role="alert">{error}</p>}
    {Number(draft.level || 1) >= 3 && <div className="form-group">
      <label>子职业</label>
      <select aria-label="子职业" value={draft.subclass_id || ""} onChange={(event) => setDraft((current) => ({ ...current,
        subclass_id: event.target.value, subclass_spell_variant: "", bonus_spells: [], selectedCantrips: [], selectedSpells: [], mystic_arcanum: {},
      }))}>
        <option value="">请选择子职业</option>
        {profile.subclasses.map((subclass) => <option key={subclass.id} value={subclass.id}>{subclass.name_display}</option>)}
      </select>
    </div>}
    {(profile.spell_variants || []).length > 0 && <div className="form-group"><label>结社法术环境</label>
      <select aria-label="结社法术环境" value={draft.subclass_spell_variant || profile.spell_variants[0]} onChange={(event) => setDraft((current) => ({ ...current, subclass_spell_variant: event.target.value, selectedSpells: [], selectedCantrips: [] }))}>
        {profile.spell_variants.map((variant) => <option key={variant}>{variant}</option>)}
      </select></div>}
    {profile.ability_increase_levels.length > 0 && <>
      <h4>升级属性提升</h4>
      <p className="spell-meta">使用可重复选择的“属性值提升”专长：每次分配两点，可选同一属性两次；上限20。19级也可用此专长作为史诗恩惠的替代选择。</p>
      {profile.ability_increase_levels.map((level) => <div className="form-group" key={level}>
        <label>{level}级 · 两点属性提升</label><div className="dual-grid">
          {[0, 1].map((index) => <select key={index} aria-label={`${level}级属性提升第${index + 1}点`} value={draft.ability_increases?.[level]?.[index] || ""} onChange={(event) => setDraft((current) => {
            const choices = [...(current.ability_increases?.[level] || ["", ""])]; choices[index] = event.target.value;
            return { ...current, ability_increases: { ...current.ability_increases, [level]: choices } };
          })}><option value="">选择属性 +1</option>{ABILITIES.map((ability) => <option key={ability} value={ability}>{formatStat(ability)}</option>)}</select>)}
        </div>
      </div>)}
      <p className="timeline-content">最终属性：{ABILITIES.map((ability) => `${formatStat(ability)} ${profile.stats[ability]}`).join(" · ")}</p>
    </>}
    {profile.expertise_count > 0 && <div className="form-group">
      <label>技能专精 · {selectedExpertise.length}/{profile.expertise_count}</label>
      <p className="spell-meta">先选择下方职业技能，再从已熟练技能中选出专精。</p>
      <div className="class-grid skill-choice-grid">{expertiseOptions.map(([skill]) => <button type="button" className={`class-card ${selectedExpertise.includes(skill) ? "selected" : ""}`} aria-pressed={selectedExpertise.includes(skill)} key={skill}
        disabled={!selectedExpertise.includes(skill) && selectedExpertise.length >= profile.expertise_count}
        onClick={() => setDraft((current) => ({ ...current, expertise_skills: (current.expertise_skills || []).includes(skill)
          ? current.expertise_skills.filter((value) => value !== skill) : [...(current.expertise_skills || []), skill] }))}>{formatSkill(skill)}</button>)}</div>
    </div>}
    <details className="sheet-section"><summary>已获得的职业特性 · {profile.features.length} 项</summary>
      {profile.features.map((feature, index) => <p className="timeline-content" key={`${feature.name}-${index}`}>{feature.level}级 · {feature.name_display || feature.name}</p>)}
      <p className="spell-meta">特性会记录到角色卡；战斗风格、祈唤等特性内部选择及具体效果仍按对应规则处理。</p>
    </details>
  </section>;
}
