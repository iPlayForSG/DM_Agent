const CONFIGURED_BACKEND_BASE = (import.meta.env?.VITE_BACKEND_URL || "").replace(/\/$/, "");
const BACKEND_BASE = import.meta.env?.DEV ? "" : CONFIGURED_BACKEND_BASE;
const API_PREFIX = BACKEND_BASE ? `${BACKEND_BASE}/api/v1` : "/api/v1";

function readableHttpError(response, detail = "") {
  const normalizedDetail = String(detail || "").trim();
  if (response.status >= 500) return "模型或后端服务暂时不可用，请稍后重新载入存档确认进度。";
  if (normalizedDetail && !/^\d{3}(?:\s+OK)?$/i.test(normalizedDetail)) return normalizedDetail;
  if (response.status === 404) return "没有找到对应的存档或页面，请返回主页重新选择。";
  return `请求未能完成（${response.status}）。请稍后重试。`;
}

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
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("主持服务等待超时，请重新载入存档确认当前进度。");
    throw new Error("无法连接后端服务，请确认启动脚本仍在运行，然后刷新页面重试。");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload);
    } catch {
      // ignore JSON parse errors for empty bodies
    }
    throw new Error(readableHttpError(response, detail));
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
  const detail = typeof data === "string" ? data : data.detail || data.error || JSON.stringify(data);
  if (/connection error|connection reset|peer closed|timed?\s*out|network|dm agent request failed|model invocation failed/i.test(String(detail))) {
    return "模型服务连接中断。请重新载入存档确认当前进度后再试。";
  }
  return detail;
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

export async function generateAbilityScores(payload) {
  return request("/rules/ability-scores", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function saveCharacter(draft) {
  return request("/characters", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export async function loadCharacter(identifier) {
  return request(`/characters/${encodeURIComponent(identifier)}`);
}

export async function deleteCharacter(identifier) {
  return request(`/characters/${encodeURIComponent(identifier)}/delete`, {
    method: "POST",
  });
}

export async function deleteCharacters(identifiers) {
  return request("/characters/batch-delete", {
    method: "POST",
    body: JSON.stringify({ ids: identifiers }),
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

export async function deleteGame(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}/delete`, {
    method: "POST",
  });
}

export async function deleteGames(gameIds) {
  return request("/games/batch-delete", {
    method: "POST",
    body: JSON.stringify({ ids: gameIds }),
  });
}

export async function deleteGameMessage(gameId, messageIndex) {
  return request(`/games/${encodeURIComponent(gameId)}/messages/${encodeURIComponent(messageIndex)}/delete`, {
    method: "POST",
  });
}

export async function rewriteGameMessage(gameId, messageIndex, message, handlers) {
  if (handlers) return requestTurnStream(`/games/${encodeURIComponent(gameId)}/messages/${messageIndex}/rewrite?stream=true`, { message }, handlers);
  return request(`/games/${encodeURIComponent(gameId)}/messages/${encodeURIComponent(messageIndex)}/rewrite`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function retryGameMessage(gameId, messageIndex, handlers) {
  if (handlers) return requestTurnStream(`/games/${encodeURIComponent(gameId)}/messages/${messageIndex}/retry?stream=true`, {}, handlers);
  return request(`/games/${encodeURIComponent(gameId)}/messages/${encodeURIComponent(messageIndex)}/retry`, {
    method: "POST",
  });
}

export async function loadActionOptions(gameId) {
  return request(`/games/${encodeURIComponent(gameId)}/action-options`);
}

export async function updateReplyLength(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/reply-length`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loadActionSuggestions(gameId, { timeoutMs = 45000 } = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request(`/games/${encodeURIComponent(gameId)}/action-suggestions`, {
      method: "POST",
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function loadModelConfig() {
  return request("/llm/config");
}

export async function loadModelHealth() {
  return request("/health/llm");
}

export async function updateModelConfig(payload) {
  return request("/llm/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function selectModelConfig(profileId) {
  return request("/llm/config/select", {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId }),
  });
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
  return requestTurnStream(`/games/${encodeURIComponent(gameId)}/turns/stream`, { message }, handlers);
}

async function requestTurnStream(path, body, handlers) {
  let response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("请求等待超时，请稍后重试。");
    throw new Error("无法连接后端服务，请确认启动脚本仍在运行，然后刷新页面重试。");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload);
    } catch {
      // ignore JSON parse errors for empty bodies
    }
    throw new Error(readableHttpError(response, detail));
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
    if (parsed.event === "agent.output.started") handlers.onAgentOutput?.(parsed.data, "started");
    if (parsed.event === "agent.output.delta") handlers.onAgentOutput?.(parsed.data, "delta");
    if (parsed.event === "agent.output.completed") handlers.onAgentOutput?.(parsed.data, "completed");
    if (parsed.event === "turn.node") handlers.onNode?.(parsed.data);
    if (parsed.event === "rag.completed") handlers.onRag?.(parsed.data);
    if (parsed.event === "tool.completed") handlers.onTool?.(parsed.data);
    if (parsed.event === "roll.recorded") handlers.onRoll?.(parsed.data?.roll_records || []);
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

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";
      for (const block of blocks) dispatchBlock(block);
    }
  } catch {
    if (streamError) throw streamError;
    throw new Error("与主持服务的连接意外中断，请重新载入存档确认当前进度。");
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

export async function useFeatureAction(gameId, payload) {
  return request(`/games/${encodeURIComponent(gameId)}/actions/use-feature`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
