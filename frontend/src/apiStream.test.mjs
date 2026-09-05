import test from "node:test";
import assert from "node:assert/strict";
import { streamTurn, retryGameMessage, rewriteGameMessage, readStreamChunk } from "./api.js";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("SSE delivers real text and hidden roll receipts before the final response", async (t) => {
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  t.mock.method(globalThis, "fetch", async () => new Response(body, { status: 200 }));
  const text = [], rolls = [];
  let complete = false;
  const pending = streamTurn("synthetic", "action", {
    onAgentOutput: (data, phase) => { if (phase === "delta") text.push(data.text); },
    onRoll: (records) => rolls.push(...records),
    onResult: () => { complete = true; },
  });
  await tick();
  const encoder = new TextEncoder();
  const bytes = encoder.encode('event: agent.output.delta\r\ndata: {"text":"塔门开启"}\r\n\r\n');
  // 覆盖 UTF-8 字符和 SSE 边界被网络分片拆开的情况。
  for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
  controller.enqueue(encoder.encode('event: roll.recorded\ndata: {"roll_records":[{"record_id":"a","visibility":"hidden","total":19}]}\n\n'));
  await tick();
  assert.deepEqual(text, ["塔门开启"]);
  assert.equal(rolls[0].visibility, "hidden");
  assert.equal(complete, false);
  controller.enqueue(encoder.encode('event: turn.completed\ndata: {"turn_status":"completed","game_state":{}}\n\n'));
  controller.close();
  await pending;
  assert.equal(complete, true);
});

test("retry and rewrite opt into the same SSE transport", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return new Response('event: turn.completed\ndata: {"game_state":{},"turn_status":"completed"}\n\n');
  });
  await retryGameMessage("test game", 3, {});
  await rewriteGameMessage("test game", 2, "新的行动", {});
  assert.match(requests[0].url, /test%20game\/messages\/3\/retry\?stream=true$/);
  assert.match(requests[1].url, /test%20game\/messages\/2\/rewrite\?stream=true$/);
  assert.deepEqual(requests[1].body, { message: "新的行动" });
});

test("committed response completes even if the transport never closes", async (t) => {
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode('event: turn.completed\ndata: {"turn_status":"completed","game_state":{}}\n\n')); },
    cancel() { cancelled = true; },
  });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  const result = await streamTurn("synthetic", "action");
  assert.equal(result.turn_status, "completed");
  assert.equal(cancelled, true);
});

test("silent stream times out and warns against replaying an uncertain action", async () => {
  let cancelled = false;
  const reader = new ReadableStream({ cancel() { cancelled = true; } }).getReader();
  await assert.rejects(readStreamChunk(reader, 15), /不要重复发送/);
  assert.equal(cancelled, true);
  reader.releaseLock();
});
