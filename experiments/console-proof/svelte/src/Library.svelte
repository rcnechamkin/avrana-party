<script lang="ts">
  import { seatsPhrase } from '/party/lib/library.js';
  import type { Game, Suggestion } from './lib/types';
  let { catalog, suggestions, people, onSuggest }: { catalog: Game[]; suggestions: Suggestion[]; people: number; onSuggest: (game: string) => void } = $props();
  const named = $derived(new Set(suggestions.map((s) => s.game)));
</script>

<ul id="library" class="cp-lib" aria-label="Games">
  {#each catalog as g (g.id)}
    <li>
      <span><strong>{g.name}</strong> <span class="text-muted">{seatsPhrase(g, people)}</span></span>
      <button type="button" class="btn btn-outline btn-sm" disabled={named.has(g.id)} data-key="suggest-{g.id}" onclick={() => onSuggest(g.id)}>{named.has(g.id) ? 'Suggested' : 'Suggest'}</button>
    </li>
  {/each}
</ul>
