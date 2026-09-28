// Small shell editor over the SAME shared model and avatar service.
import { AVATARS } from './profile.js';
import { icon } from './icons.js';
import { h } from './ui.js';

/** A person's picture: their photo, or the emoji character they chose. size: '', 'sm' or 'lg'. */
export function avatarNode(me, size = '') {
  const cls = ('avrana-avatar ' + size).trim();
  return me.pfp ? h('img', { class: cls, src: me.pfp, alt: '', width: 48, height: 48 })
    : h('span', { class: cls, 'aria-hidden': 'true', text: me.avatar });
}
export function wireProfile(profile, changed) {
  const $ = (id) => document.getElementById(id);
  let chosen = profile.snapshot().avatar, image = null, selection = 0;
  const say = (text) => { $('profile-note').textContent = text; };
  function render() {
    const me = profile.snapshot();
    // Who you are at this party; a new guest's first step is choosing a name.
    $('player-chip').classList.toggle('border-primary', !me.name);
    $('player-chip').replaceChildren(avatarNode(me, 'lg'),
      h('span', { class: 'grid min-w-0 flex-1' },
        h('span', { class: 'truncate', text: me.name || 'Choose your name' }),
        h('span', { class: 'text-[0.9375rem] font-normal text-muted',
          text: me.name ? 'Your profile' : 'Pick a name to join a game' })),
      icon('user-round-pen', { cls: 'text-muted' }));
    $('profile-stats').textContent = me.favorites.length + ' favorites · ' + me.playTotal + ' games opened';
    $('remove-photo').hidden = !me.pfp;
    if (!$('profile').open) {
      $('profile-name').value = me.name;
      chosen = me.avatar;
    }
    $('avatar-choices').replaceChildren(...AVATARS.map((avatar) => h('button', {
      type: 'button', class: 'btn btn-ghost h-14 border-line text-[1.75rem] aria-pressed:border-primary aria-pressed:bg-base-300', text: avatar,
      'aria-label': 'Choose ' + avatar, 'aria-pressed': avatar === chosen,
      onclick: () => { chosen = avatar; render(); },
    })));
  }
  $('profile').addEventListener('toggle', () =>
    $('player-chip').setAttribute('aria-expanded', String($('profile').open)));
  $('player-chip').setAttribute('aria-expanded', String($('profile').open));
  $('player-chip').onclick = () => {
    $('profile').open = !$('profile').open;
    if ($('profile').open) $('profile-name').focus();
  };
  $('profile-form').onsubmit = (event) => {
    event.preventDefault();
    try {
      profile.save({ name: $('profile-name').value, avatar: chosen });
      $('profile').open = false;
      say('Profile saved on this browser.');
      render(); changed();
    } catch (err) { say(err.message); }
  };
  $('remove-photo').onclick = async () => {
    try { await profile.removePhoto(); render(); changed(); say('Photo removed.'); }
    catch (err) { say(err.message); }
  };
  function release() {
    selection++;
    image?.close?.(); image = null;
    $('photo-crop').hidden = true;
    $('profile-photo').value = '';
  }
  function draw() {
    if (!image) return;
    const cv = $('photo-canvas'), ctx = cv.getContext('2d');
    const zoom = Number($('photo-zoom').value);
    const scale = Math.max(cv.width / image.width, cv.height / image.height) * zoom;
    const width = image.width * scale, height = image.height * scale;
    const x = (cv.width - width) * Number($('photo-x').value) / 100;
    const y = (cv.height - height) * Number($('photo-y').value) / 100;
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(image, x, y, width, height);
  }
  $('profile-photo').onchange = async () => {
    const file = $('profile-photo').files[0];
    release();
    if (!file) return;
    const current = selection;
    if (file.size > 8 * 1024 * 1024 || !/^image\/(jpeg|png|webp)$/.test(file.type)) {
      say('Choose a JPEG, PNG or WebP photo under 8 MB.'); return;
    }
    try {
      let decoded;
      if (globalThis.createImageBitmap) decoded = await createImageBitmap(file, { imageOrientation: 'from-image' });
      else {
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result);
          reader.onerror = reject; reader.readAsDataURL(file);
        });
        decoded = await new Promise((resolve, reject) => {
          const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = data;
        });
        // drawImage uses natural dimensions; make the common image interface explicit.
        decoded.width = decoded.naturalWidth; decoded.height = decoded.naturalHeight;
      }
      if (selection !== current) { decoded.close?.(); return; }
      image = decoded;
      $('photo-zoom').value = 1; $('photo-x').value = 50; $('photo-y').value = 50;
      $('photo-crop').hidden = false; draw(); say('Frame your photo, then use it.');
    } catch { if (selection === current) { release(); say('This browser could not read that photo.'); } }
  };
  for (const id of ['photo-zoom', 'photo-x', 'photo-y']) $(id).oninput = draw;
  $('photo-cancel').onclick = release;
  $('photo-use').onclick = async () => {
    if (!image) return;
    $('photo-use').disabled = true;
    $('photo-cancel').disabled = true;
    $('profile-photo').disabled = true;
    try {
      const blob = await new Promise((resolve) => $('photo-canvas').toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('This photo could not be prepared.');
      await profile.uploadPhoto(blob);
      release(); render(); changed(); say('Photo saved.');
    } catch (err) { say(err.message); }
    finally { for (const id of ['photo-use', 'photo-cancel', 'profile-photo']) $(id).disabled = false; }
  };
  window.addEventListener('storage', (event) => {
    if (event.key === null || /^(wc-|lg-)/.test(event.key)) { render(); changed(); }
  });
  render();
  return render;
}
