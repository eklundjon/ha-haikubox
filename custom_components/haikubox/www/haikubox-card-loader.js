// Startup loader for the Haikubox cards.
//
// Why this exists: the integration injects the card modules with
// add_extra_js_url, which HA bakes into index.html at page-render time. HA's
// web server comes up (and serves index.html) before stage-2 integrations like
// this one have set up, and the frontend never loads extra modules added after
// the page was rendered. A page loaded in that window — which is exactly when
// a browser or Companion app reconnecting after a restart reloads — gets no
// card JS, and every Haikubox card stays a "Custom element doesn't exist"
// error until a manual refresh.
//
// This file is copied into config/www and registered as a Lovelace resource,
// so it's served from /local (mounted before the web server starts) and listed
// in the page from the first render. It imports the real card modules from
// the integration's own static path, retrying until that path is registered.
// Once the element is defined, Lovelace rebuilds any error cards on its own.
//
// The integration version rides in on this file's ?v= query (the resource URL)
// and is forwarded to the card URLs, so they match the add_extra_js_url URLs
// exactly — the browser's module map then runs each card module only once no
// matter which path loads it first.

// Keep in sync with _CARDS in __init__.py: [custom element tag, module URL].
const CARDS = [
  ["haikubox-bird-card", "/haikubox/haikubox-bird-card.js"],
  ["haikubox-bird-list-card", "/haikubox/haikubox-bird-list-card.js"],
];

const version = new URL(import.meta.url).searchParams.get("v") ?? "dev";

// Retry schedule: 1s doubling to a 30s cap, for up to ~10 minutes. Stage 2
// can take minutes on a slow box (its timeout is 300s); past that the
// integration most likely failed to load, and we stop rather than poll a 404
// forever.
const FIRST_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const GIVE_UP_MS = 10 * 60_000;

async function load(tag, path) {
  const started = Date.now();
  let delay = FIRST_DELAY_MS;
  for (let attempt = 0; ; attempt++) {
    // Already defined (add_extra_js_url got there first, or an earlier try).
    if (customElements.get(tag)) return;
    // The first try uses the exact add_extra_js_url URL. Retries add a unique
    // param: a failed fetch may be remembered by the module map or the HTTP
    // cache (404s are heuristically cacheable), so the same URL could keep
    // failing even after the path is registered. A card module that ends up
    // loaded under two URLs is harmless — its customElements.define is guarded.
    const url = `${path}?v=${encodeURIComponent(version)}` +
      (attempt ? `&retry=${attempt}` : "");
    try {
      await import(url);
      return;
    } catch (err) {
      if (Date.now() - started > GIVE_UP_MS) {
        console.warn(`Haikubox: giving up loading ${path}`, err);
        return;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 2, MAX_DELAY_MS);
  }
}

for (const [tag, path] of CARDS) load(tag, path);
