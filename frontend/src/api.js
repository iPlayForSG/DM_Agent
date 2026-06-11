const BACKEND_BASE = (import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");
const API_PREFIX = BACKEND_BASE ? `${BACKEND_BASE}/api/v1` : "/api/v1";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
  } catch {
    throw new Error("无法连接后端服务，请确认启动脚本仍在运行，然后刷新页面重试。");
  }

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

function parseSseBlock(block) {
  let event = "message";
  const dataLines = [];

  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(":")) continue;

    const separatorIndex = rawLine.indexOf(":");
    const field = separatorIndex >= 0 ? rawLine.slice(0, separatorIndex) : rawLine;
    let value = separatorIndex >= 0 ? rawLine.slice(separatorIndex + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value || "message";
    if (field === "data") dataLines.push(value);
  }

  if (dataLines.length === 0) return null;

  const rawData = dataLines.join("\n");
  let data = rawData;
  try {
    data = JSON.parse(rawData);
  } catch {
    // SSE data can be plain text. Keep it as-is when it is not JSON.
  }

  return { event, data };
}

function streamErrorMessage(data) {
  if (!data) return "流式回合请求失败。";
  if (typeof data === "string") return data;
  return data.detail || data.error || JSON.stringify(data);
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

export async function streamTurn(gameId, message, handlers = {}) {
  let response;
  try {
    response = await fetch(`${API_PREFIX}/games/${encodeURIComponent(gameId)}/turns/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch {
    throw new Error("无法连接后端服务，请确认启动脚本仍在运行，然后刷新页面重试。");
  }

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

  if (!response.body) {
    const payload = await response.json();
    handlers.onResult?.(payload, "turn.completed");
    return payload;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalPayload = null;
  let streamError = null;

  const dispatchBlock = (block) => {
    const parsed = parseSseBlock(block);
    if (!parsed) return;

    handlers.onEvent?.(parsed.event, parsed.data);
    if (parsed.event === "turn.node") handlers.onNode?.(parsed.data);
    if (parsed.event === "rag.completed") handlers.onRag?.(parsed.data);
    if (parsed.event === "tool.completed") handlers.onTool?.(parsed.data);
    if (parsed.event === "validation.note") handlers.onValidation?.(parsed.data);
    if (parsed.event === "turn.completed" || parsed.event === "turn.input_required") {
      finalPayload = parsed.data;
      handlers.onResult?.(parsed.data, parsed.event);
    }
    if (parsed.event === "turn.error") {
      streamError = new Error(streamErrorMessage(parsed.data));
      handlers.onError?.(parsed.data);
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) dispatchBlock(block);
  }

  buffer += decoder.decode();
  if (buffer.trim()) dispatchBlock(buffer);

  if (streamError) throw streamError;
  if (!finalPayload) throw new Error("流式回合没有返回结果。");
  return finalPayload;
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
