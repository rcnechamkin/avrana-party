// A Svelte action over the real Lucide helper (web/party/lib/icons.js).
import { icon as lucide } from '/party/lib/icons.js';

export function icon(node: HTMLElement, name: string) {
  node.replaceChildren(lucide(name));
  return { update(next: string) { node.replaceChildren(lucide(next)); } };
}
