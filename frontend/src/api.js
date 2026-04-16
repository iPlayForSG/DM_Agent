const API_PREFIX = "/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload);
    } catch {
      // ignore JSON parse errors for empty bodies
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function loadLobby() {
  const [gamesPayload, charactersPayload, classesPayload, monstersPayload] = await Promise.all([
    request("/games"),
    request("/characters"),
    request("/library/classes"),
    request("/monsters"),
  ]);

  return {
    games: gamesPayload.games || [],
    characters: charactersPayload.characters || [],
    classes: classesPayload.classes || [],
    monsters: monstersPayload.monsters || [],
  };
}

export async function loadSpells(className) {
  const payload = await request(`/library/spells/${encodeURIComponent(className)}`);
  return payload.spells || [];
}

export async function loadCharacterBuilder() {
  return request("/rules/character-builder");
}

export async function saveCharacter(draft) {
  return request("/characters", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export async function saveMonsterTemplate(draft) {
  return request("/monsters", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export async function loadMonsterTemplate(monsterId) {
  return request(`/monsters/${encodeURIComponent(monsterId)}`);
}

export async function createGame(payload) {
  return request("/games", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loadGame(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}`);
}

export async function loadActionOptions(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}/action-options`);
}

export async function selectAdventure(gameId, adventureId) {
  return request(`/games/${encodeURIComponent(gameId)}/select-adventure`, {
    method: "POST",
    body: JSON.stringify({ adventure_id: adventureId }),
  });
}

export async function startEncounter(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/start`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function addEncounterEnemy(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/add-enemy`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function spawnEncounterTemplate(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/spawn-template`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function endEncounter(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/end`, {
    method: "POST",
  });
}

export async function removeEncounterCombatant(gameId, combatantRef) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/remove-combatant`, {
    method: "POST",
    body: JSON.stringify({ combatant_ref: combatantRef }),
  });
}

export async function setEncounterInitiative(gameId, combatantRef, initiative) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/set-initiative`, {
    method: "POST",
    body: JSON.stringify({ combatant_ref: combatantRef, initiative }),
  });
}

export async function rollEncounterInitiative(gameId, combatantRef) {
  return request(`/games/${encodeURIComponent(gameId)}/encounters/roll-initiative`, {
    method: "POST",
    body: JSON.stringify({ combatant_ref: combatantRef }),
  });
}

export async function submitTurn(gameId, message) {
  return request(`/games/${encodeURIComponent(gameId)}/turns`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function advanceTurn(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/advance-turn`, {
    method: "POST",
  });
}

export async function attackAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/attack`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function skillCheckAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/skill-check`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function savingThrowAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/saving-throw`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function castSpellAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/cast-spell`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function useItemAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/use-item`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
