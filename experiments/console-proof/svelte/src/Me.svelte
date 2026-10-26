<script lang="ts">
  import Avatar from './Avatar.svelte';
  import type { View } from './lib/types';
  let { view, line }: { view: View; line: string } = $props();
</script>

<div id="me" class="cp-me"><Avatar avatar={view.me.avatar} size="lg" /><strong>{view.me.name}</strong></div>
<p id="me-role" class="m-0">{line}</p>
