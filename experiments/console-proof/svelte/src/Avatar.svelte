<script lang="ts">
  // The same rule as web/party/lib/profile-ui.js avatarNode (a bundled Gaze picture, else the text).
  import { gazeOf } from '/party/lib/profile-ui.js';
  let { avatar, size = '' }: { avatar: string; size?: '' | 'sm' | 'lg' } = $props();
  const gaze = $derived(gazeOf({ avatar }));
</script>

{#if gaze}
  <img class="avrana-avatar {size}" src="/party/avatars/{gaze}.svg" alt="" width="48" height="48">
{:else}
  <span class="avrana-avatar {size}" aria-hidden="true">{avatar}</span>
{/if}
