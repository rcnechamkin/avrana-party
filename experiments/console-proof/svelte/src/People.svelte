<script lang="ts">
  import { roster } from '/party/lib/party-mode.js';
  import Avatar from './Avatar.svelte';
  import type { View } from './lib/types';
  let { view }: { view: View } = $props();
  const people = $derived(roster(view));
</script>

<ul id="people" class="avrana-people" aria-label="People at the party">
  {#each people as m (m.id)}
    <li>
      <Avatar avatar={m.avatar || ''} size="sm" />
      <span class="who">{m.name}{m.me ? ' (you)' : ''}</span>
      <span class="tags">{#if m.host}<span class="avrana-tag">Host</span>{/if}</span>
    </li>
  {/each}
</ul>
