<script lang="ts">
  // Next-game suggestions preview (FIXTURE-backed; not a voting backend).
  import { approvalLine, gameName } from '/party/x/shared/rules.js';
  import type { Game, Suggestion } from './lib/types';
  let { suggestions, catalog, me, onApprove }: { suggestions: Suggestion[]; catalog: Game[]; me: string; onApprove: (id: string) => void } = $props();
</script>

<ol id="sugg" class="cp-sugg" aria-label="Suggestions, most approved first">
  {#each suggestions as s (s.id)}
    {@const mine = s.approvals.includes(me)}
    <li data-suggestion={s.id}>
      <div>
        <strong>{gameName(catalog, s.game)}</strong>
        <div class="who">Suggested by {s.by}</div>
        <div class="who" data-approvals={s.count}>{approvalLine(s)}</div>
      </div>
      <button type="button" class="btn btn-sm {mine ? 'btn-primary' : 'btn-outline'}" aria-pressed={mine} data-key="approve-{s.id}"
        aria-label="{mine ? 'Withdraw approval for' : 'Approve'} {gameName(catalog, s.game)}" onclick={() => onApprove(s.id)}>{mine ? 'Approved' : 'Approve'}</button>
    </li>
  {:else}
    <li>No suggestions yet. Suggest one from the Library.</li>
  {/each}
</ol>
