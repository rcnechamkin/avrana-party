// Design-prototype helper: turns query-string switches into data attributes so one page can
// show its variants (?role=guest, ?state=limited, ?sheet=filters, ...). Not product code.
(function () {
  var q = new URLSearchParams(location.search);
  var root = document.documentElement;
  root.dataset.role = q.get('role') === 'guest' ? 'guest' : 'host';
  q.forEach(function (v, k) { if (k !== 'role') root.dataset[k] = v; });

  function set(pair) {
    var i = pair.indexOf('=');
    var k = pair.slice(0, i), v = pair.slice(i + 1);
    if (v) root.dataset[k] = v; else delete root.dataset[k];
  }
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-set]');
    if (!el) return;
    e.preventDefault();
    el.getAttribute('data-set').split(',').forEach(set);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') ['sheet', 'drawer', 'ping', 'about'].forEach(function (k) { delete root.dataset[k]; });
  });
  // carry the role across the prototype's own links
  document.addEventListener('DOMContentLoaded', function () {
    if (root.dataset.role !== 'guest') return;
    document.querySelectorAll('a[href]').forEach(function (a) {
      var u = a.getAttribute('href');
      if (/^[a-z-]+\.html/.test(u) && u.indexOf('role=') < 0) a.setAttribute('href', u + (u.indexOf('?') < 0 ? '?' : '&') + 'role=guest');
    });
  });
})();
