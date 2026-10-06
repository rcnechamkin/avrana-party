// Design-prototype helper: the two things every shell page can open over itself without leaving it.
//   1. the Party drawer (people, and chat once the Party owns one)   ?drawer=chat | people, ?chat=off
//   2. the Limited Mode explanation                                  ?about=limited
// A briefing is a shell page too: both open over it and close back to it. Not product code.
(function () {
  var root = document.documentElement, d = root.dataset;
  var AV = '../../../../web/party/avatars/';
  var briefing = d.state === 'briefing' || d.state === 'limited';

  // the first slice has no Party-owned chat: the same control opens people only
  if (d.chat === 'off') {
    if (d.drawer) d.drawer = 'people';
    document.querySelectorAll('.hud').forEach(function (h) {
      h.setAttribute('data-set', 'drawer=people');
      h.setAttribute('aria-label', 'Your Party: 4 people here. Open people');
    });
  }

  var html =
    '<div class="scrim" id="pscrim" data-set="drawer=,about="></div>' +
    '<section class="drawer" id="social" role="dialog" aria-modal="true" aria-labelledby="social-h">' +
      '<div class="sheet__head"><h2 id="social-h" tabindex="-1">Your Party</h2><button class="iconbtn" data-set="drawer=" aria-label="Close"><i data-i="x"></i></button></div>' +
      '<div class="tabs" role="tablist">' +
        '<a href="#" role="tab" data-set="drawer=chat" id="tab-chat">Chat</a>' +
        '<a href="#" role="tab" data-set="drawer=people" id="tab-people">People</a>' +
      '</div>' +
      '<div class="sheet__body" id="pane-chat">' +
        '<div class="chat" role="log" aria-label="Party chat">' +
          '<p class="sys"><i data-i="user-round"></i><span><bdi>Priya</bdi> joined</span></p>' +
          '<div class="msg"><img src="' + AV + 'gaze-12.svg" alt=""><div><p class="msg__n"><bdi>Dana</bdi></p><p class="msg__t">one more BLUFF then something calmer?</p></div></div>' +
          '<div class="msg"><img src="' + AV + 'gaze-21.svg" alt=""><div><p class="msg__n"><bdi>Sam</bdi></p><p class="msg__t">calmer = EXPO. we never finished mission 4</p></div></div>' +
          '<p class="sys"><i data-i="megaphone"></i><span><bdi>Sam</bdi> suggested ' + (briefing ? 'EXPO' : '<a href="game.html?game=expo" style="text-decoration:underline;text-underline-offset:3px;display:inline-block;padding:13px 6px;margin:-13px -6px">EXPO</a>') + '</span></p>' +
          '<div class="msg"><img src="' + AV + 'gaze-28.svg" alt=""><div><p class="msg__n"><bdi>Priya</bdi></p><p class="msg__t">I’m in for either</p></div></div>' +
          '<p class="sys net-only"><i data-i="wifi-off"></i><span>Not connected. New messages arrive when this phone is back.</span></p>' +
        '</div>' +
      '</div>' +
      '<div class="sheet__body" id="pane-people">' +
        '<ul class="people">' +
          '<li><img class="avatar" src="' + AV + 'gaze-07.svg" alt=""><span class="people__n"><bdi>Cody</bdi></span><span class="tag">You</span><span class="tag host-only">Host</span><span class="tag lim-only">Limited</span></li>' +
          '<li data-was-host><img class="avatar" src="' + AV + 'gaze-12.svg" alt=""><span class="people__n"><bdi>Dana</bdi></span><span class="tag guest-only n-h-moved">Host</span><span class="people__s h-only"><i data-i="moon-star"></i>Away</span></li>' +
          '<li><img class="avatar" src="' + AV + 'gaze-21.svg" alt=""><span class="people__n"><bdi>Sam</bdi></span><span class="tag guest-only h-moved">Host</span></li>' +
          '<li><img class="avatar" src="' + AV + 'gaze-28.svg" alt=""><span class="people__n"><bdi>Priya</bdi></span>' + (briefing ? '' : '<span class="people__s"><i data-i="moon-star"></i>Away</span>') + '</li>' +
        '</ul>' +
      '</div>' +
      // over a briefing the drawer says where the Party is, so closing it is plainly the way back
      (briefing ? '<p class="drawer__where"><i data-i="hourglass"></i><span>The Party is getting ready for <b id="where-game"></b>. Close this to answer.</span></p>' : '') +
      '<form class="compose" id="compose" onsubmit="return false">' +
        '<label class="vh" for="say">Message the Party</label>' +
        '<input id="say" placeholder="Message the Party" autocomplete="off">' +
        '<button class="iconbtn needs-box" aria-label="Send"><i data-i="send"></i></button>' +
      '</form>' +
      '<div class="grab" aria-hidden="true"></div>' +
    '</section>' +

    // Limited Mode: the three facts LIMITED-MODE 3.9 requires (not private, what is missing, how Full Mode returns)
    '<section class="sheet" id="about-limited" role="dialog" aria-modal="true" aria-labelledby="about-h">' +
      '<div class="grab" aria-hidden="true"></div>' +
      '<div class="sheet__head"><h2 id="about-h" tabindex="-1">Limited Mode on this phone</h2><button class="iconbtn" data-set="about=" aria-label="Close"><i data-i="x"></i></button></div>' +
      '<div class="sheet__body">' +
        '<p class="about__now" id="about-now" hidden><i data-i="triangle-alert"></i><span></span></p>' +
        '<ul class="about">' +
          '<li><b>This connection isn’t private.</b>Other people on this Wi-Fi could see what this phone sends.</li>' +
          '<li><b>This phone can’t play Gauntlet II or Worms.</b>It can still watch Worms. The Party, hosting and card games work as usual. The screen may dim while you play.</li>' +
          '<li><b>Full Mode returns when the box’s owner renews its certificate.</b>There is nothing to do on this phone.</li>' +
        '</ul>' +
      '</div>' +
      '<div class="sheet__foot"><button class="btn" data-set="about=">' + (briefing ? 'Back to the briefing' : 'Done') + '</button></div>' +
    '</section>';
  document.body.insertAdjacentHTML('beforeend', html);
  if (window.paintIcons) window.paintIcons();

  if (d.net) { var say = document.getElementById('say'); say.disabled = true; say.placeholder = 'Not connected'; }
  if (briefing) {
    var t = document.getElementById('title');
    document.getElementById('where-game').textContent = t ? t.textContent : 'the next game';
    // what Limited Mode means for the round on screen, first
    var why = document.getElementById('why-limited'), lim = root.hasAttribute('data-limited');
    if (why && lim) { var now = document.getElementById('about-now'); now.hidden = false; now.lastElementChild.textContent = why.textContent; }
  }

  // reflect the open tab; move focus into what opened and back to what opened it
  var opener = null, was = '';
  document.addEventListener('click', function (e) { var b = e.target.closest('[data-set]'); if (b && !b.closest('#social, #about-limited, #pscrim')) opener = b; }, true);
  function sync() {
    ['chat', 'people'].forEach(function (k) {
      var tab = document.getElementById('tab-' + k);
      if (d.drawer === k) tab.setAttribute('aria-current', 'true'); else tab.removeAttribute('aria-current');
    });
    var open = d.drawer ? 'drawer' : d.about ? 'about' : '';
    if (open && !was) document.getElementById(open === 'drawer' ? 'social-h' : 'about-h').focus({ preventScroll: true });
    if (!open && was && opener && document.contains(opener)) opener.focus({ preventScroll: true });
    was = open;
  }
  // Tab stays inside the open drawer or sheet (they are modal)
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || !was) return;
    var box = document.getElementById(was === 'drawer' ? 'social' : 'about-limited');
    var f = [].filter.call(box.querySelectorAll('a[href], button, input, [tabindex="0"]'), function (el) { return !el.disabled && el.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], at = document.activeElement;
    if (!box.contains(at) || at === box.querySelector('h2')) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
    else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
  });
  new MutationObserver(sync).observe(root, { attributes: true });
  sync();
})();
