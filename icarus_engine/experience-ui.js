/* Optional dashboard controls. No market requests or external media until requested. */
(() => {
  'use strict';
  const themes = [['dark', 'Dark'], ['light', 'Light'], ['midnight', 'Midnight'], ['ocean', 'Ocean'],
    ['forest', 'Forest'], ['ember', 'Ember'], ['sakura', 'Anime: Sakura'], ['neon', 'Anime: Neon']];
  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const snapshots = new Map();
  const fillSnapshots = new Map();
  const cueTimers = new WeakMap();
  let initialized = false, currentView = '', uptime = null;
  const read = (key, fallback) => { try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch (_) { /* Session-only if browser storage is unavailable. */ } };
  const allowedTheme = value => themes.some(([id]) => id === value) ? value : 'dark';

  function motion() {
    root.dataset.motion = read('icarus-motion', 'system') === 'off' || reduced.matches ? 'off' : 'live';
    if (root.dataset.motion === 'off') document.querySelectorAll('.experience-cue, .experience-fill-cue').forEach(el => {
      clearTimeout(cueTimers.get(el));
      el.classList.remove('experience-cue', 'experience-fill-cue');
    });
    const note = document.getElementById('experienceMotionNote');
    if (note) note.textContent = reduced.matches ? 'Your system requests reduced motion; all cues are off.' :
      root.dataset.motion === 'off' ? 'All motion is off.' : 'Brief cues for changed closed-bar states and new live paper fills.';
  }

  function cue(symbol, kind) {
    if (!initialized || root.dataset.motion !== 'live' || document.hidden) return;
    const card = Array.from(document.querySelectorAll('.asset[data-sym]')).find(el => el.dataset.sym === symbol);
    const target = card || (currentView === 'asset:' + symbol ? document.getElementById('assetHead') : null);
    if (!target) return;
    clearTimeout(cueTimers.get(target));
    target.classList.add(kind === 'fill' ? 'experience-fill-cue' : 'experience-cue');
    cueTimers.set(target, setTimeout(() => target.classList.remove('experience-cue', 'experience-fill-cue'), 700));
  }

  function update(data, view) {
    currentView = view;
    if (uptime !== null && Number(data.uptime_sec) < uptime) { snapshots.clear(); fillSnapshots.clear(); }
    uptime = Number(data.uptime_sec);
    const active = new Set();
    for (const asset of data.assets || []) {
      active.add(asset.symbol);
      const state = asset.state || {};
      const next = {ready: asset.warm === true && !asset.rewarming, bar: asset.bar_index,
        signature: JSON.stringify([state.rate_uptrend, state.rate_regime_str, state.pulse_state, asset.position])};
      const previous = snapshots.get(asset.symbol);
      if (previous && previous.ready && next.ready && next.bar > previous.bar && next.signature !== previous.signature) cue(asset.symbol, 'state');
      if (!next.ready || (previous && next.bar < previous.bar)) fillSnapshots.delete(asset.symbol);
      snapshots.set(asset.symbol, next);
    }
    for (const symbol of snapshots.keys()) if (!active.has(symbol)) { snapshots.delete(symbol); fillSnapshots.delete(symbol); }
  }

  function chart(data, windowSize) {
    const rows = data.fills || [];
    const key = fill => JSON.stringify([fill.ts, fill.bar, fill.id, fill.side, fill.qty, fill.price, fill.kind, fill.comment, fill.profit, fill.pos]);
    const previous = fillSnapshots.get(data.symbol);
    const sameWindow = previous && previous.liveFrom === data.live_from && previous.windowSize === windowSize;
    const latest = Math.max(0, ...rows.map(fill => Number(fill.ts) || 0));
    const ready = snapshots.get(data.symbol)?.ready;
    if (ready && sameWindow && rows.some(fill =>
      fill.live === true && fill.ts >= previous.latest && !previous.keys.has(key(fill)))) cue(data.symbol, 'fill');
    // First response, a different requested history window and a new process establish a baseline.
    fillSnapshots.set(data.symbol, {liveFrom: data.live_from, windowSize, latest: sameWindow ? Math.max(latest, previous.latest) : latest,
      keys: new Set(rows.map(key))});
  }

  function init({onThemeChanged} = {}) {
    if (initialized) return;
    initialized = true;
    root.dataset.theme = allowedTheme(read('icarus-theme', 'dark'));
    const controls = document.createElement('div');
    controls.className = 'experience-controls';
    controls.innerHTML = `<details class="experience-settings"><summary aria-label="Appearance and motion settings">Style</summary><div>
      <label>Theme<select id="experienceTheme"></select></label>
      <label>Motion<select id="experienceMotion"><option value="system">Follow system</option><option value="off">No motion</option></select></label>
      <p id="experienceMotionNote"></p><p>Anime palettes are original colors; no character art.</p>
      </div></details><button class="icon-btn" id="experienceMusicToggle" aria-expanded="false" aria-controls="experienceMusic">Music</button>`;
    document.getElementById('btnTheme').insertAdjacentElement('afterend', controls);
    const select = document.getElementById('experienceTheme');
    for (const [id, label] of themes) { const option = document.createElement('option'); option.value = id; option.textContent = label; select.appendChild(option); }
    select.value = root.dataset.theme;
    select.addEventListener('change', () => {
      root.dataset.theme = allowedTheme(select.value);
      save('icarus-theme', root.dataset.theme);
      onThemeChanged?.();
    });
    document.getElementById('btnTheme').addEventListener('click', () => { select.value = allowedTheme(root.dataset.theme); });
    const motionSelect = document.getElementById('experienceMotion');
    motionSelect.value = read('icarus-motion', 'system') === 'off' ? 'off' : 'system';
    motionSelect.addEventListener('change', () => { save('icarus-motion', motionSelect.value); motion(); });
    reduced.addEventListener('change', motion);
    motion();

    const panel = document.createElement('section');
    panel.id = 'experienceMusic'; panel.className = 'experience-music'; panel.hidden = true;
    panel.setAttribute('aria-label', 'Dreambound music player');
    panel.innerHTML = `<header><h2>Dreambound</h2><button class="sm" id="experienceMusicClose">Close &amp; stop</button></header>
      <div class="experience-player" id="experiencePlayer"><button id="experienceMusicLoad">Load public playlist</button></div>
      <p><a href="https://www.youtube.com/@Dreambound/videos" target="_blank" rel="noopener noreferrer">Official channel and full public catalog</a>
      &middot; <a href="https://www.youtube.com/playlist?list=UUo9OXAWEwN6nnX5c3hL0OaA" target="_blank" rel="noopener noreferrer">Open uploads on YouTube</a></p>
      <p id="experienceMusicNote">Loads YouTube only when you choose the playlist. Use the player's play, pause, volume and playlist controls.</p>
      <p>Availability is controlled by YouTube and the uploaders. Private, deleted, age- or region-restricted, and embed-blocked videos may not play here. If the player is blank or unavailable, open the uploads on YouTube.</p>`;
    document.body.appendChild(panel);
    const toggle = document.getElementById('experienceMusicToggle');
    const player = document.getElementById('experiencePlayer');
    const load = document.getElementById('experienceMusicLoad');
    const close = () => {
      player.querySelector('iframe')?.remove();
      player.appendChild(load); load.hidden = false; panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false'); toggle.focus();
    };
    toggle.addEventListener('click', () => {
      if (!panel.hidden) { close(); return; }
      panel.hidden = false; toggle.setAttribute('aria-expanded', 'true');
      document.getElementById('experienceMusicClose').focus();
    });
    document.getElementById('experienceMusicClose').addEventListener('click', close);
    panel.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } });
    load.addEventListener('click', () => {
      const iframe = document.createElement('iframe');
      iframe.title = 'Dreambound public uploads - YouTube player';
      iframe.referrerPolicy = 'strict-origin-when-cross-origin';
      iframe.allow = 'encrypted-media; fullscreen; picture-in-picture';
      iframe.allowFullscreen = true;
      iframe.src = 'https://www.youtube-nocookie.com/embed/videoseries?list=UUo9OXAWEwN6nnX5c3hL0OaA&listType=playlist&autoplay=0&playsinline=1';
      player.replaceChildren(iframe);
    });
  }

  window.IcarusExperience = Object.freeze({init, update, chart});
})();
