async (page) => {
  await page.waitForFunction(() => window.__dmStreamSamples.length > 1
    && !document.querySelector('.thinking-running')
    && document.querySelectorAll('.message-stack.dm').length >= 2, null, { timeout: 45000 });
  return page.evaluate(() => {
    const samples = window.__dmStreamSamples;
    const ledgers = [...document.querySelectorAll('.message-stack.dm .turn-roll-ledger')];
    return {
      rendered_updates_while_running: samples.length,
      first_chars: samples[0].count,
      last_chars: samples.at(-1).count,
      rendering_span_ms: Math.round(samples.at(-1).at - samples[0].at),
      reply_cards: document.querySelectorAll('.message-stack.dm').length,
      ledger_cards: ledgers.length,
      ledgers_default_collapsed: ledgers.every((ledger) => !ledger.open),
      horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
}
