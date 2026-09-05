async (page) => {
  await page.unroute('**/api/v1/**');
  await page.route('**/api/v1/**', (route) => {
    const url = route.request().url().replace(/^https?:\/\/[^/]+/, 'http://127.0.0.1:23581');
    return route.continue({ url });
  });
  await page.addInitScript(() => {
    window.__dmStreamSamples = [];
    new MutationObserver(() => {
      const output = document.querySelector('.thinking-running [data-streamed-chars]');
      const count = Number(output?.getAttribute('data-streamed-chars') || 0);
      const previous = window.__dmStreamSamples.at(-1)?.count;
      if (count > 0 && count !== previous) window.__dmStreamSamples.push({ count, at: performance.now() });
    }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('http://127.0.0.1:5173');
  return { url: page.url(), title: await page.title() };
}
