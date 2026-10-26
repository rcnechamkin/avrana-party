<script lang="ts">
  // The Svelte 5 console (AVR-762 experiment): the same surfaces and protocol as the vanilla
  // console, written as runes components. Pure rules come from the same files (web/party/lib and
  // the experiment's shared rules); the DOM is Svelte's.
  import { onMount, tick } from 'svelte';
  import { parseFromPage } from '/party/lib/layer.js';
  import { FIXTURE_NOTE, LAYER_PROTOCOL, TABS, api, attentionText, gameUrl, parseTicketRequest, shellOf, whereLine } from '/party/x/shared/rules.js';
  import type { Game, Suggestion, TabId, View, Viewport } from './lib/types';
  import { icon } from './lib/icon';
  import Suggestions from './Suggestions.svelte';
  import People from './People.svelte';
  import Library from './Library.svelte';
  import Me from './Me.svelte';

  const shell = shellOf(location);
  const inLayer = shell.shell === 'layer' && parent !== window;

  let view = $state<View | null>(null);
  let catalog = $state<Game[]>([]);
  let suggestions = $state<Suggestion[]>([]);
  let tab = $state<TabId>('home');
  let open = $state(!inLayer);
  let vp = $state<Viewport | null>(null);
  let entering = $state(false);
  let now = $state(Date.now());
  let offset = $state(0);
  let busy = false;
  let layerButton = $state<HTMLButtonElement>();
  let closeButton = $state<HTMLButtonElement>();
  let backButton = $state<HTMLButtonElement>();
  let sheet = $state<HTMLElement>();

  const member = $derived(Boolean(view?.me));
  const where = $derived(whereLine(view, catalog));

  // ---- the page that mounted this frame (layer shell only) ----
  const post = (msg: Record<string, unknown>) => parent.postMessage({ avrana: LAYER_PROTOCOL, ...msg }, shell.pageOrigin);
  function place() {
    if (!vp) return;
    if (open) post({ type: 'place', mode: 'open', side: 'right', y: 0 });
    else post({ type: 'place', mode: 'button', side: 'right', y: Math.round(vp.h / 3) });
  }
  async function onMessage(ev: MessageEvent) {
    if (ev.source !== parent || ev.origin !== shell.pageOrigin) return;   // only the registered game origin (or own, in Limited Mode)
    const next = parseFromPage(ev.data) as Viewport | null;
    if (next) { const first = !vp; vp = next; if (first) place(); return; }
    const req = parseTicketRequest(ev.data);
    if (!req) return;
    const body = await api('/api/ticket', { game: shell.game });
    post(body ? { type: 'ticket', id: req.id, ticket: body.ticket, role: body.role } : { type: 'ticket-error', id: req.id, error: 'unavailable' });
  }

  // ---- open, close, back to the game ----
  async function openConsole() {
    if (!inLayer || open) return;
    if (shell.strategy === 'R') { post({ type: 'navigate', to: 'console' }); return; }   // the restore path leaves the game
    open = true; entering = true;
    place();
    await tick();
    closeButton?.focus({ preventScroll: true });
    requestAnimationFrame(() => requestAnimationFrame(() => { entering = false; }));
    refresh();
  }
  async function closeConsole() {
    if (!inLayer || !open) return;
    open = false;
    place();
    await tick();
    layerButton?.focus({ preventScroll: true });
  }
  function backToGame() {
    if (inLayer) { closeConsole(); return; }
    const url = gameUrl(view, shell.fw, shell.strategy, shell.limited, location.origin);
    if (url) location.assign(url);
  }
  function onKeydown(e: KeyboardEvent) {
    if (!inLayer || !open || !sheet) return;
    if (e.key === 'Escape') { e.preventDefault(); closeConsole(); return; }
    if (e.key !== 'Tab') return;
    const all = [...sheet.querySelectorAll<HTMLElement>('button, input, select, [tabindex="0"]')]
      .filter((el) => !(el as HTMLButtonElement).disabled && el.getClientRects().length > 0);
    if (!all.length) return;
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (e.shiftKey && at <= 0) { e.preventDefault(); all.at(-1)!.focus(); }
    else if (!e.shiftKey && (at === -1 || at === all.length - 1)) { e.preventDefault(); all[0].focus(); }
  }

  // ---- the Party ----
  async function refresh() {
    const [v, s] = await Promise.all([api('/api/view'), api('/api/suggestions')]);
    if (v) { view = v; offset = v.now - Date.now(); }
    if (s) suggestions = s.suggestions;
  }
  async function act(path: string, body: Record<string, string>) {
    if (busy) return;
    busy = true;
    const res = await api(path, body);
    busy = false;
    if (res) suggestions = res.suggestions;
  }

  onMount(() => {
    if (inLayer) { document.documentElement.classList.add('avrana-layer-doc'); document.body.classList.add('avrana-layer'); }
    else document.body.classList.add('cp-page');
    addEventListener('message', onMessage);
    (async () => {
      const [cat] = await Promise.all([api('/api/catalog'), refresh()]);
      catalog = cat ? cat.games : [];
      if (inLayer) post({ type: 'ready' });
      else { await tick(); backButton?.focus({ preventScroll: true }); performance.mark('console-ready'); document.body.dataset.ready = '1'; }
    })();
    const poll = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (open) refresh(); else api('/api/view').then((v) => { if (v) view = v; });
    }, 2000);
    const clock = setInterval(() => { if (open && view?.attention.some((a) => a.kind === 'your_turn')) now = Date.now(); }, 1000);
    return () => { removeEventListener('message', onMessage); clearInterval(poll); clearInterval(clock); };
  });
</script>

<svelte:document onkeydown={onKeydown} />

{#if inLayer && vp && !open && member}
  <button bind:this={layerButton} id="layer-button" type="button" class="avrana-layer-button" aria-haspopup="dialog" aria-label="Your Party" onclick={openConsole}>
    <span class="ring" aria-hidden="true"><span use:icon={'users'}></span></span><span id="layer-unread" class="unread" aria-hidden="true">{view?.attention.length || ''}</span>
  </button>
{/if}

{#if open && member && view}
  <div id="console" class="avrana-layer-open">
    {#if inLayer}<div id="backdrop" class="avrana-layer-backdrop" onclick={closeConsole} role="presentation"></div>{/if}
    <section bind:this={sheet} id="sheet" class="avrana-drawer avrana-layer-sheet cp-sheet" data-entering={entering ? '' : undefined}
      role={inLayer ? 'dialog' : 'region'} aria-modal={inLayer ? 'true' : undefined} aria-labelledby="console-h">
      <div class="head">
        <h2 id="console-h" class="m-0">Your Party</h2>
        {#if inLayer}<button bind:this={closeButton} id="close" type="button" class="btn btn-ghost btn-square" aria-label="Close" onclick={closeConsole}><span use:icon={'x'}></span></button>{/if}
      </div>
      <p id="where" class="where" role="status" aria-live="polite">{where}</p>
      <div class="cp-panel cp-tight"><button bind:this={backButton} id="back-to-game" type="button" class="btn btn-primary cp-back" onclick={backToGame}>Back to Game</button></div>
      <div class="cp-panel cp-tight">
        <ul id="attention" class="cp-attention" aria-label="For you">
          {#each view.attention as a (a.id)}<li data-kind={a.kind}>{attentionText(a, now + offset, catalog)}</li>{/each}
        </ul>
      </div>
      <div id="tabs" class="avrana-tabs" role="group" aria-label="Show">
        {#each TABS as t (t.id)}
          <button type="button" id="tab-{t.id}" data-tab={t.id} aria-pressed={tab === t.id} onclick={() => (tab = t.id as TabId)}>{t.label}</button>
        {/each}
      </div>
      {#if tab === 'home'}
        <div id="panel-home" class="body cp-panel">
          <h3 class="m-0">Next game suggestions</h3>
          <p class="cp-note" id="fixture-note">{FIXTURE_NOTE}</p>
          <Suggestions {suggestions} {catalog} me={view.me.name} onApprove={(id) => act('/api/suggestions/approve', { id })} />
        </div>
      {:else if tab === 'party'}
        <div id="panel-party" class="body cp-panel"><People {view} /></div>
      {:else if tab === 'library'}
        <div id="panel-library" class="body cp-panel"><Library {catalog} {suggestions} people={view.members.length} onSuggest={(game) => act('/api/suggestions/nominate', { game })} /></div>
      {:else}
        <div id="panel-me" class="body cp-panel"><Me {view} line={where} /></div>
      {/if}
    </section>
  </div>
{/if}
