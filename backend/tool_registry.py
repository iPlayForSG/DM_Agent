"""Tool contracts and lightweight guardrails for agent tool calls."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models import Combatant, GameState


@dataclass(frozen=True)
class ToolContract:
    name: str
    schema: Dict[str, Any]
    side_effect: str = "read"
    risk_level: str = "low"
    requires_confirmation: bool = False
    needs_active_encounter: bool = False
    blocks_active_encounter: bool = False
    current_actor_arg: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ToolGuardrailResult:
    ok: bool
    args: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


TOOL_CONTRACT_METADATA: Dict[str, Dict[str, Any]] = {
    "lookup_rules": {"side_effect": "read", "risk_level": "low"},
    "roll_dice": {"side_effect": "random", "risk_level": "low"},
    "adjust_hp": {"side_effect": "state_write", "risk_level": "medium"},
    "add_status": {"side_effect": "state_write", "risk_level": "medium"},
    "remove_status": {"side_effect": "state_write", "risk_level": "medium"},
    "append_adventure_log": {"side_effect": "story_write", "risk_level": "low"},
    "add_inventory_item": {"side_effect": "state_write", "risk_level": "medium"},
    "record_evidence": {"side_effect": "story_write", "risk_level": "medium"},
    "record_search_outcome": {"side_effect": "story_write", "risk_level": "medium"},
    "record_major_experience": {"side_effect": "state_write", "risk_level": "medium"},
    "record_chapter_progress": {
        "side_effect": "campaign_write",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "set_defeat_state": {
        "side_effect": "combat_write",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "set_scene": {"side_effect": "state_write", "risk_level": "medium"},
    "set_active_character": {"side_effect": "state_write", "risk_level": "low"},
    "start_encounter": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "blocks_active_encounter": True,
    },
    "add_enemy": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "needs_active_encounter": True,
    },
    "save_monster_template": {"side_effect": "asset_write", "risk_level": "medium"},
    "spawn_monster_from_template": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "needs_active_encounter": True,
    },
    "attack_target": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "needs_active_encounter": True,
        "current_actor_arg": "attacker_ref",
    },
    "roll_skill_check": {
        "side_effect": "random",
        "risk_level": "low",
        "current_actor_arg": "actor_ref",
    },
    "roll_saving_throw": {"side_effect": "random", "risk_level": "medium"},
    "cast_spell": {
        "side_effect": "state_write",
        "risk_level": "medium",
        "current_actor_arg": "caster_ref",
    },
    "set_initiative": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "needs_active_encounter": True,
    },
    "roll_initiative": {
        "side_effect": "random",
        "risk_level": "medium",
        "needs_active_encounter": True,
    },
    "advance_turn": {
        "side_effect": "combat_write",
        "risk_level": "medium",
        "needs_active_encounter": True,
    },
    "end_encounter": {
        "side_effect": "combat_write",
        "risk_level": "high",
        "requires_confirmation": True,
        "needs_active_encounter": True,
    },
}


class ToolRegistry:
    def __init__(self, contracts: List[ToolContract]):
        self._contracts = {contract.name: contract for contract in contracts}

    @classmethod
    def from_schemas(cls, schemas: List[Dict[str, Any]]) -> "ToolRegistry":
        contracts: List[ToolContract] = []
        for schema in schemas:
            name = str(schema.get("name") or "").strip()
            if not name:
                continue
            metadata = dict(TOOL_CONTRACT_METADATA.get(name, {}))
            contracts.append(ToolContract(name=name, schema=dict(schema), **metadata))
        return cls(contracts)

    def get(self, name: str) -> Optional[ToolContract]:
        return self._contracts.get(name)

    def schemas_for(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        selected = set(tool_names or [])
        return [
            dict(contract.schema)
            for name, contract in self._contracts.items()
            if name in selected
        ]

    def validate_call(
        self,
        *,
        state: GameState,
        tool_name: str,
        args: Dict[str, Any],
        allowed_tools: List[str],
    ) -> ToolGuardrailResult:
        contract = self.get(tool_name)
        if contract is None:
            return self._reject(tool_name, "Unknown tool.")
        if tool_name not in set(allowed_tools or []):
            return self._reject(
                tool_name,
                f"Tool is not allowed in the current phase: {tool_name}",
                contract=contract,
            )

        normalized_args = dict(args or {})
        schema_error = self._validate_schema_args(contract, normalized_args)
        if schema_error:
            return self._reject(tool_name, schema_error, contract=contract)

        encounter_active = bool(state.encounter and state.encounter.active)
        if contract.needs_active_encounter and not encounter_active:
            return self._reject(
                tool_name,
                f"Tool requires an active encounter: {tool_name}",
                contract=contract,
            )
        if contract.blocks_active_encounter and encounter_active:
            return self._reject(
                tool_name,
                f"Tool cannot run while an encounter is already active: {tool_name}",
                contract=contract,
            )

        current_actor_error = self._validate_current_actor(contract, state, normalized_args)
        if current_actor_error:
            return self._reject(tool_name, current_actor_error, contract=contract)

        return ToolGuardrailResult(
            ok=True,
            args=normalized_args,
            metadata=self._metadata(contract),
        )

    def _validate_schema_args(self, contract: ToolContract, args: Dict[str, Any]) -> str:
        parameters = dict(contract.schema.get("parameters") or {})
        properties = dict(parameters.get("properties") or {})
        required = list(parameters.get("required") or [])
        for field_name in required:
            if field_name not in args:
                return f"Missing required tool argument `{field_name}` for {contract.name}."
            if isinstance(args.get(field_name), str) and not args.get(field_name).strip():
                return f"Required tool argument `{field_name}` cannot be empty for {contract.name}."

        for field_name, value in args.items():
            prop_schema = properties.get(field_name)
            if not prop_schema or value is None:
                continue
            expected_type = prop_schema.get("type")
            if expected_type and not self._matches_json_type(value, expected_type):
                return (
                    f"Invalid type for `{field_name}` on {contract.name}: "
                    f"expected {expected_type}, got {type(value).__name__}."
                )
            enum_values = prop_schema.get("enum")
            if enum_values and value not in enum_values:
                return f"Invalid value for `{field_name}` on {contract.name}: {value!r}."
        return ""

    @staticmethod
    def _matches_json_type(value: Any, expected_type: str) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return True

    def _validate_current_actor(
        self,
        contract: ToolContract,
        state: GameState,
        args: Dict[str, Any],
    ) -> str:
        actor_arg = contract.current_actor_arg
        if not actor_arg:
            return ""

        encounter = state.encounter
        if not encounter or not encounter.active:
            return ""

        actor_ref = str(args.get(actor_arg) or "").strip()
        if not actor_ref:
            return ""

        current = encounter.get_current_combatant()
        if not current and not encounter.turn_order_started:
            current = self._first_ready_combatant(state)
        if not current:
            return f"Tool requires a current combatant before actor-bound action: {contract.name}"

        if self._matches_current_actor(state, current, actor_ref):
            return ""

        actor_name = self._resolve_actor_name(state, actor_ref)
        return (
            f"Tool must be used by the current combatant `{current.name}` "
            f"during an active encounter: {contract.name} (got `{actor_name}`)."
        )

    @staticmethod
    def _first_ready_combatant(state: GameState) -> Optional[Combatant]:
        encounter = state.encounter
        if not encounter or not encounter.initiative_order:
            return None
        for combatant_id in encounter.initiative_order:
            combatant = encounter.combatants.get(combatant_id)
            if not combatant or combatant.initiative is None:
                return None
        for combatant_id in encounter.initiative_order:
            combatant = encounter.combatants.get(combatant_id)
            if combatant and combatant.hp_current > 0 and combatant.defeat_state == "active":
                return combatant
        return None

    @classmethod
    def _matches_current_actor(cls, state: GameState, current: Combatant, actor_ref: str) -> bool:
        allowed_refs = {current.combatant_id, current.name}
        if current.linked_character_id:
            allowed_refs.add(current.linked_character_id)
            character = state.characters.get(current.linked_character_id)
            if character:
                allowed_refs.add(character.name)
        normalized_ref = cls._normalize_ref(actor_ref)
        return any(cls._normalize_ref(ref) == normalized_ref for ref in allowed_refs if ref)

    @classmethod
    def _resolve_actor_name(cls, state: GameState, actor_ref: str) -> str:
        normalized_ref = cls._normalize_ref(actor_ref)
        for combatant in (state.encounter.combatants.values() if state.encounter else []):
            combatant_refs = [combatant.combatant_id, combatant.name, combatant.linked_character_id or ""]
            if any(cls._normalize_ref(ref) == normalized_ref for ref in combatant_refs if ref):
                return combatant.name
        for character in state.characters.values():
            character_refs = [character.character_id, character.name]
            if any(cls._normalize_ref(ref) == normalized_ref for ref in character_refs if ref):
                return character.name
        return actor_ref

    @staticmethod
    def _normalize_ref(value: str) -> str:
        return str(value or "").strip().casefold()

    @classmethod
    def _reject(
        cls,
        tool_name: str,
        error: str,
        contract: Optional[ToolContract] = None,
    ) -> ToolGuardrailResult:
        metadata = cls._metadata(contract) if contract else {"tool_name": tool_name}
        return ToolGuardrailResult(ok=False, error=error, metadata=metadata)

    @staticmethod
    def _metadata(contract: Optional[ToolContract]) -> Dict[str, Any]:
        if contract is None:
            return {}
        return {
            "tool_name": contract.name,
            "side_effect": contract.side_effect,
            "risk_level": contract.risk_level,
            "requires_confirmation": contract.requires_confirmation,
            "needs_active_encounter": contract.needs_active_encounter,
            "blocks_active_encounter": contract.blocks_active_encounter,
            "current_actor_arg": contract.current_actor_arg,
        }
