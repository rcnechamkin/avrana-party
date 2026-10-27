// Next-game suggestions preview (FIXTURE-backed; not a voting backend): most approvals first, each
// with who suggested it and who approved it by name. The one new vanilla module the proof needed.
import { h } from '/party/lib/ui.js';
import { approvalLine, gameName } from '/party/x/shared/rules.js';

export function renderSuggestions(list, suggestions, { catalog, me, onApprove }) {
  if (!suggestions.length) { list.replaceChildren(h('li', { text: 'No suggestions yet. Suggest one from the Library.' })); return; }
  list.replaceChildren(...suggestions.map((s) => {
    const mine = s.approvals.includes(me);
    return h('li', { 'data-suggestion': s.id },
      h('div', {},
        h('strong', { text: gameName(catalog, s.game) }),
        h('div', { class: 'who', text: `Suggested by ${s.by}` }),
        h('div', { class: 'who', 'data-approvals': s.count, text: approvalLine(s) })),
      h('button', { type: 'button', class: 'btn btn-sm ' + (mine ? 'btn-primary' : 'btn-outline'), 'aria-pressed': String(mine), 'data-key': `approve-${s.id}`,
        'aria-label': `${mine ? 'Withdraw approval for' : 'Approve'} ${gameName(catalog, s.game)}`, text: mine ? 'Approved' : 'Approve',
        onclick: () => onApprove(s.id) }));
  }));
}
