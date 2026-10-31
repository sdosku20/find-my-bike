import { SITE, SPOTS, SUPABASE_URL, SUPABASE_ANON_KEY } from '../config.js';
import { createMap } from './map.js';
import { anchor, placeSiteAt, resetSite, toPlan, toLatLng, route, heading, distance } from './geo.js';
import { connect } from './data.js';
import { openLive } from './live.js';
import { attachZoom } from './zoom.js';
import { SNAPSHOTS } from '../photos/snapshots.js';

const $ = id => document.getElementById(id);
const STALE_MS = 60_000; // camera data older than this counts as offline
const FAR_M = 400;       // further than this from the site, hand over to Google Maps
const WALK_MPS = 1.3;    // walking speed while pushing a bike
// Availability levels. Blue stays reserved for you, your route and the selected rack.
const LEVELS = { plenty: 'Plenty of space', filling: 'Filling up', almost: 'Almost full', full: 'Full', off: 'No data' };
// The colours BikeFit draws gaps 1–5 in (colour_gap_top5.COLORS), so the list matches the picture.
const GAP_COLORS = ['#5fcd3c', '#37aff5', '#f5c846', '#d764dc', '#f57d46'];
const SAMPLE = { north: 4, east: 9, south: 0, west: 2, gate: 5 };
const ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4.5 20.5 12 16.5l7.5 4z"/></svg>';
const params = new URLSearchParams(location.search);

const spots = new Map(SPOTS.map(s => [s.id, {
  ...s, has_camera: Boolean(s.camera), photo_url: null,
  free_estimate: null, bikes: null, gaps: [], source: 'sample', updated_at: null,
}]));
// Racks without a camera show the latest photo analysed by tools/photo_snapshots.py.
for (const [id, snap] of Object.entries(SNAPSHOTS)) {
  const s = spots.get(id);
  if (!s) continue;
  Object.assign(s, {
    photo_url: snap.photo, free_estimate: snap.free_estimate, bikes: snap.bikes, gaps: snap.gaps,
    capacity: snap.capacity ?? s.capacity, source: 'photo', updated_at: snap.taken_at,
  });
}
const state = {
  sb: null, selected: null, target: null, user: null, heading: null, watchId: null,
  compass: false, closeLive: null, pushed: false,
};

// ?demo=off puts the plan back at the real site after "Demo here" moved it.
if (params.get('demo') === 'off') resetSite();
// ?sim=x,y places a simulated user on the plan (metres), handy for demos on a laptop.
const sim = (params.get('sim') || '').split(',').map(Number);
if (sim.length === 2 && sim.every(Number.isFinite)) state.user = { plan: sim, accuracy: 3, simulated: true };

// On a phone the opening map view keeps the site clear of the floating panels at the top and bottom.
function mapInsets() {
  if (matchMedia('(min-width: 900px)').matches) return { top: 16, right: 16, bottom: 16, left: 16 };
  const box = $('home').getBoundingClientRect();
  const dock = $('dock').getBoundingClientRect(), controls = document.querySelector('.controls').getBoundingClientRect();
  return {
    top: $('total').getBoundingClientRect().bottom - box.top + 8,
    right: 8,
    bottom: box.bottom - Math.min(dock.height ? dock.top : box.bottom, controls.top) + 8,
    left: 8,
  };
}
// Two views of the same plan: the 2D map is always there, the 3D one is loaded the first time it is opened.
const map2d = createMap($('map'), selectRack, { insets: mapInsets });
let map3d = null, mode = '2d';
const active = () => (mode === '3d' && map3d ? map3d : map2d);
const both = () => (map3d ? [map2d, map3d] : [map2d]);
const map = {
  update: (...a) => both().forEach(m => m.update(...a)),
  setRoute: (...a) => both().forEach(m => m.setRoute(...a)),
  setUser: (...a) => both().forEach(m => m.setUser(...a)),
  fit: (...a) => both().forEach(m => m.fit(...a)),
  relayout: () => both().forEach(m => m.relayout()),
  reset: () => active().reset(),
  zoom: f => active().zoom(f),
};

// ?debug exposes both maps to the browser console (and to the tests).
if (params.has('debug')) window.__maps = { map2d, get map3d() { return map3d; } };

// Tapping a rack on the map: the camera flies in, then the rack's photo or live view opens full screen.
function selectRack(id) {
  if (state.selected) return openSpot(id);
  active().focus(id, () => openSpot(id));
}

// ---------- status ----------

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function ago(iso) {
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (s < 5) return 'just now';
  if (s < 90) return `${s} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

const when = iso => new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const offline = s => s.source === 'camera' && (!s.updated_at || Date.now() - Date.parse(s.updated_at) > STALE_MS);
const measured = s => (s.source === 'camera' || s.source === 'photo') && !offline(s);
const isLive = s => s.has_camera && s.source === 'camera' && !offline(s);
// Gaps only exist between bikes, so at most one bike and no gaps means the rack is empty.
const empty = s => measured(s) && s.bikes != null && s.bikes <= 1 && !(s.gaps || []).length;
const position = pos => (pos == null ? 'Gap' : pos < 1 / 3 ? 'Left side' : pos < 2 / 3 ? 'Middle' : 'Right side');
const gapColor = g => g.color || GAP_COLORS[(g.rank - 1) % GAP_COLORS.length];
const fmtM = m => (m < 1000 ? `${Math.max(5, Math.round(m / 5) * 5)} m` : `${(m / 1000).toFixed(1)} km`);
const minutes = m => Math.max(1, Math.round(m / WALK_MPS / 60));

function level(s) {
  if (offline(s)) return 'off';
  if (empty(s)) return 'plenty';
  if (s.free_estimate == null) return 'off';
  if (s.free_estimate <= 0) return 'full';
  const p = s.capacity ? s.free_estimate / s.capacity : null;
  if (p === null) return s.free_estimate >= 6 ? 'plenty' : s.free_estimate >= 3 ? 'filling' : 'almost';
  return p >= 0.3 ? 'plenty' : p >= 0.15 ? 'filling' : 'almost';
}

function freeCount(s) {
  if (level(s) === 'off') return null;
  return empty(s) ? s.capacity ?? null : Math.max(0, s.free_estimate);
}

function freeText(s) {
  const lvl = level(s), n = freeCount(s);
  if (lvl === 'off') return offline(s) ? 'Offline' : 'No data';
  if (lvl === 'full') return 'Full';
  return n == null ? 'Empty' : `${n} free`;
}

function sourceText(s) {
  if (s.has_camera) {
    if (s.source !== 'camera') return state.sb ? 'Live camera · waiting for data' : 'Live camera · sample data';
    return offline(s) ? `Camera offline · last seen ${ago(s.updated_at)}` : 'Live camera';
  }
  if (s.source === 'photo') return `Photo · ${when(s.updated_at)}`;
  return s.source === 'manual' && s.updated_at ? `Reported ${ago(s.updated_at)}` : 'Sample data';
}

const totalFree = () => [...spots.values()].reduce((t, s) => t + (freeCount(s) ?? 0), 0);

function applyRow(row) {
  const s = spots.get(row.id);
  if (!s) return;
  if (s.source === 'photo' && row.source !== 'camera') return; // a photo beats sample data; a live camera beats a photo
  for (const k of ['name', 'capacity', 'has_camera', 'photo_url']) if (row[k] != null) s[k] = row[k];
  for (const k of ['free_estimate', 'bikes', 'gaps', 'source', 'updated_at']) if (k in row) s[k] = row[k];
  renderAll();
}

function useSample() {
  for (const [id, free] of Object.entries(SAMPLE)) {
    const s = spots.get(id);
    if (s && s.source !== 'photo') Object.assign(s, { free_estimate: free, source: 'sample' });
  }
}

// A short message when a rack fills up or frees up, and a flash on the plan.
const prevLevel = {}, flashing = new Set();
let tracking = false;
function trackChanges() {
  for (const s of spots.values()) {
    const now = level(s), before = prevLevel[s.id];
    prevLevel[s.id] = now;
    if (!tracking || !before || before === now || before === 'off' || now === 'off') continue;
    flashing.add(s.id);
    setTimeout(() => { flashing.delete(s.id); renderMap(); }, 2600);
    if (now === 'full') toast(`<b>${esc(s.name)} is now full.</b> ${plural(totalFree(), 'free spot')} left on the site.`);
    else if (before === 'full') toast(`<b>${esc(s.name)} has space again:</b> ${esc(freeText(s))}.`, 'info');
  }
}

function toast(html, kind = '') {
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.innerHTML = `<i></i><span>${html}</span>`;
  $('toasts').append(t);
  setTimeout(() => t.remove(), 5000);
}

// ---------- location helpers ----------

const anchorPlan = () => [anchor().x, anchor().y];
const userPlan = () => state.user.plan || toPlan(state.user.lat, state.user.lng);
// Your position on the plan, or null when unknown or too far away for the plan to help.
function userNear() {
  const pos = state.user && userPlan();
  return pos && distance(pos, anchorPlan()) <= FAR_M ? pos : null;
}
function walkTo(s) {
  const pos = userNear();
  return pos ? route(pos, s) : null;
}

// ---------- rendering ----------

function renderTotal() {
  const list = [...spots.values()], total = totalFree();
  const known = list.filter(s => level(s) !== 'off').length;
  $('totalN').textContent = total;
  $('totalL').textContent = `free bike spot${total === 1 ? '' : 's'}`;
  $('totalS').textContent = known === list.length ? `across ${plural(list.length, 'parking rack')}` : `across ${known} of ${list.length} racks`;
}

function renderLegend() {
  $('legend').innerHTML = Object.entries(LEVELS)
    .map(([k, text]) => `<span class="st-${k}"><i></i>${text}</span>`).join('')
    + '<span><i class="live"></i>Live camera</span><span><i class="you"></i>You</span>';
}

let listHtml = '';
function renderList() {
  if (!$('zlist')) return; // the rack list is hidden for now (commented out in index.html)
  const html = [...spots.values()].map(s => {
    const lvl = level(s), n = freeCount(s), walk = walkTo(s), open = s.id === state.selected;
    const pct = lvl === 'off' || !s.capacity ? 0 : Math.max(3, Math.round(Math.min(1, (n ?? 0) / s.capacity) * 100));
    return `<button type="button" class="zrow st-${lvl}${open ? ' is-selected' : ''}" data-zone="${esc(s.id)}"${open ? ' aria-current="true"' : ''}>
      <span class="zchip" aria-hidden="true">${esc(s.name[0])}</span>
      <span class="zmeta"><b>${esc(s.name)}</b>
        <small>${isLive(s) ? '<span class="livedot"></span>' : ''}${esc(sourceText(s))}${walk ? ` · ${fmtM(walk.length)}` : ''}</small>
        <span class="bar"><span style="width:${pct}%"></span></span></span>
      <span class="zfree">${esc(freeText(s))}</span><span class="chev" aria-hidden="true">›</span>
    </button>`;
  }).join('');
  if (html !== listHtml) $('zlist').innerHTML = listHtml = html;
}

function renderMap() {
  map.update([...spots.values()].map(s => ({
    id: s.id,
    level: level(s),
    free: freeCount(s),
    text: freeText(s),
    // Share of the stands taken, for the bikes drawn in 3D.
    occupancy: s.capacity && freeCount(s) != null ? Math.min(1, Math.max(0, 1 - freeCount(s) / s.capacity)) : 0,
    label: `${s.name}: ${freeText(s)}, ${sourceText(s)}`,
    live: isLive(s),
    flash: flashing.has(s.id),
  })), state.target ?? state.selected);
}

// "Nearest rack with space" once we know where you are, with one tap to get there.
function renderNear() {
  const el = $('near'), pos = userNear();
  if (!pos || state.target) {
    el.hidden = true;
    return;
  }
  const best = [...spots.values()]
    .filter(s => (freeCount(s) ?? 0) > 0)
    .map(s => [s, route(pos, s)])
    .filter(([, r]) => r)
    .sort((a, b) => a[1].length - b[1].length)[0];
  el.innerHTML = best
    ? `<i></i><span>Nearest rack with space: <b>${esc(best[0].name)}</b> · ${fmtM(best[1].length)}</span>
       <button type="button" class="link" data-go="${esc(best[0].id)}">Directions</button>`
    : '<i></i><span>No rack has space right now.</span>';
  el.hidden = false;
}

function renderAll() {
  trackChanges();
  renderTotal();
  renderList();
  renderMap();
  renderNear();
  renderZone();
}

// ---------- open rack ----------

const ZOOM_BUTTONS = `<div class="zoom-controls">
  <button type="button" data-zoom="out" aria-label="Zoom out">−</button>
  <button type="button" data-zoom="in" aria-label="Zoom in">+</button>
  <button type="button" data-zoom="full" aria-label="Full screen">⛶</button>
</div>`;

// Another rack to try when this one is full or offline: the nearest one with space, else the emptiest.
function alternative(s, reason) {
  const others = [...spots.values()].filter(o => o.id !== s.id && (freeCount(o) ?? 0) > 0);
  const pos = userNear();
  const len = o => route(pos, o)?.length ?? Infinity;
  others.sort(pos ? (a, b) => len(a) - len(b) : (a, b) => freeCount(b) - freeCount(a));
  const alt = others[0];
  return `<span class="rk warn">!</span><span><small>${esc(reason)}</small>${alt
    ? `<b>Try <button type="button" class="link" data-zone="${esc(alt.id)}">${esc(alt.name)} · ${esc(freeText(alt))}</button></b>`
    : '<b>All racks are full right now</b>'}</span>`;
}

function zoneDetails(s) {
  const lvl = level(s), n = freeCount(s), gaps = measured(s) ? s.gaps || [] : [];
  const top = gaps.find(g => g.fits > 0);
  let best = '';
  if (lvl === 'off') best = alternative(s, offline(s) ? 'The camera is offline' : 'No data for this rack yet');
  else if (empty(s)) best = '<span class="rk ok">✓</span><span><small>Whole rack is free</small><b>No bikes detected · park anywhere</b></span>';
  else if (lvl === 'full') best = alternative(s, 'No space here');
  else if (top) best = `<span class="rk" style="--rk:${gapColor(top)}">${esc(top.rank)}</span><span><small>Best spot</small><b>${position(top.pos)} · fits about ${plural(top.fits, 'bike')}</b></span>`;

  const rows = gaps.map(g => `<div class="rrow"><span class="rk" style="--rk:${gapColor(g)}">${esc(g.rank)}</span>
      <div><b>${position(g.pos)}</b><span>${g.fits > 0 ? `Fits about ${plural(g.fits, 'bike')}` : 'Too small for a bike'}</span></div>
      ${g.area_px2 ? `<code>${Number(g.area_px2).toLocaleString('en-GB')} px²</code>` : ''}</div>`).join('');
  const none = lvl === 'off' ? 'Gaps appear here when the camera is back.'
    : empty(s) ? 'No bikes in view, so there are no gaps to measure.'
    : measured(s) ? 'No gaps between the bikes right now.'
    : 'Gaps appear here once the camera or a photo has been analysed.';
  const how = s.source === 'camera' ? 'The count updates within about a second of a change.' : s.source === 'photo' ? 'Analysed from the photo above.' : '';

  return `<section class="card zsum st-${lvl}">
      <div class="zsum-main">
        <div class="zsum-n">${n ?? '–'}</div>
        <div class="zsum-t"><div class="zsum-l">free spot${n === 1 ? '' : 's'}${s.capacity ? ` <small>of ${esc(s.capacity)}</small>` : ''}</div>
          <span class="pill">${lvl === 'off' && offline(s) ? 'Camera offline' : LEVELS[lvl]}</span></div>
        <button type="button" class="go" data-go="${esc(s.id)}">${ARROW}Directions</button>
      </div>
      ${best ? `<div class="zsum-best">${best}</div>` : ''}
    </section>
    <section class="card rlist">
      <h3 class="rl-h">Gaps found, largest first</h3>
      ${rows || `<p class="rempty">${none}</p>`}
    </section>
    <p class="foot">Free spots are estimated from the space between parked bikes. Left and right as seen in the picture. ${how}</p>`;
}

let zoneHtml = '';
function renderZone() {
  const s = spots.get(state.selected);
  if (!s || !$('zdyn')) return;
  const bikes = measured(s) && s.bikes != null ? ` · ${plural(s.bikes, 'bike')} detected` : '';
  $('zsub').innerHTML = `${isLive(s) ? '<span class="livedot"></span>' : ''}${esc(sourceText(s) + bikes)}`;
  $('ztag')?.classList.toggle('is-off', !isLive(s));
  const html = zoneDetails(s);
  if (html !== zoneHtml) $('zdyn').innerHTML = zoneHtml = html;
}

function openZone(id) {
  const s = spots.get(id);
  closeLive();
  state.selected = id;
  zoneHtml = '';
  const live = Boolean(s.has_camera && state.sb);
  let stage = '', msg = '';
  if (live) {
    stage = `<div class="stage">
        <video id="liveVideo" class="live-video" playsinline muted autoplay></video>
        <canvas id="liveCanvas" class="live-canvas" aria-label="Live camera view of ${esc(s.name)}"></canvas>
      </div>`;
    msg = 'Connecting to the camera…';
  } else if (s.photo_url) {
    stage = `<div class="stage"><img class="photo" src="${esc(s.photo_url)}" alt="Photo of ${esc(s.name)} with the largest gaps marked"></div>`;
  } else {
    msg = s.has_camera ? 'The live view appears here once the site is connected to Supabase.' : 'No camera at this rack yet. A photo will be added soon.';
  }
  const tag = s.has_camera ? '<span class="tag tag-live" id="ztag"><i></i>LIVE</span>' : s.photo_url ? '<span class="tag tag-photo">PHOTO</span>' : '';
  const zone = $('zone');
  zone.style.setProperty('--ar', s.photo_url && !live ? '1.3333' : '1.7778');
  zone.innerHTML = `<div class="zone-inner">
      <header class="zh">
        <button type="button" class="back" data-back aria-label="Back to the map">‹</button>
        <div class="zt"><h2>${esc(s.name)}</h2><p id="zsub"></p></div>${tag}
      </header>
      <div class="media${stage ? '' : ' is-empty'}" id="media">${stage}
        ${live ? '<span class="media-chip" id="liveStatus" hidden><i></i><span></span></span>' : ''}
        <div class="media-msg" id="mediaMsg"${msg ? '' : ' hidden'}>${esc(msg)}</div>
        ${stage ? ZOOM_BUTTONS : ''}
      </div>
      <div class="zdyn" id="zdyn"></div>
    </div>
    <p class="privacy">The live view is never recorded and only the counts are stored. Number plates in the photos are blurred.</p>`;
  $('home').inert = true; // the map stays underneath, out of reach of the keyboard
  zone.hidden = false;
  document.body.classList.add('zone-open');

  const setAspect = ratio => { if (ratio > 0) zone.style.setProperty('--ar', ratio.toFixed(4)); };
  const photo = zone.querySelector('.photo');
  if (photo) {
    const sized = () => setAspect(photo.naturalWidth / photo.naturalHeight);
    if (photo.complete && photo.naturalWidth) sized();
    else photo.addEventListener('load', sized, { once: true });
  }
  const closers = stage ? [attachZoom($('media'))] : [];
  if (live) {
    closers.push(openLive(state.sb, id, {
      stage: zone.querySelector('.stage'),
      video: $('liveVideo'),
      canvas: $('liveCanvas'),
      onSize: (w, h) => setAspect(w / h),
      onStatus: (text, warn, picture) => {
        const chip = $('liveStatus'), box = $('mediaMsg');
        if (!chip) return;
        chip.lastChild.textContent = text;
        chip.classList.toggle('warn', Boolean(warn));
        chip.classList.toggle('is-live', !warn && picture);
        chip.hidden = !picture;
        box.textContent = text;
        box.hidden = picture;
      },
    }));
  }
  state.closeLive = () => closers.forEach(close => close());
  renderAll();
  zone.scrollTop = 0;
  zone.focus({ preventScroll: true });
}

function closeLive() {
  state.closeLive?.();
  state.closeLive = null;
}

function closeZone() {
  closeLive();
  state.selected = null;
  $('zone').hidden = true;
  $('zone').replaceChildren();
  $('home').inert = false;
  document.body.classList.remove('zone-open');
  renderAll();
  active().unfocus();
}

// ---------- navigation: #<rack id> opens a rack, so the phone's back button closes it ----------

function spotFromHash() {
  const id = decodeURIComponent(location.hash.slice(1));
  return spots.has(id) ? id : null;
}

function show() {
  const id = spotFromHash();
  if (id && id !== state.selected) openZone(id);
  else if (!id && state.selected) closeZone();
}

function openSpot(id) {
  if (spotFromHash() === id) return show();
  if (state.selected) {
    location.replace(`#${id}`); // switching racks should not pile up history entries
  } else {
    state.pushed = true;
    location.hash = id;
  }
}

function goHome() {
  if (state.pushed && spotFromHash()) {
    history.back();
    return;
  }
  const url = new URL(location.href);
  url.hash = '';
  url.searchParams.delete('spot');
  history.replaceState(null, '', url.pathname + url.search);
  show();
}

// ---------- location & directions ----------

function setLocateState(kind) {
  $('locate').dataset.state = kind;
  $('locate').setAttribute('aria-pressed', String(kind !== 'off'));
  $('locateText').textContent = { off: 'Locate me', searching: 'Locating…', on: 'Located' }[kind];
}

// Only when you are far from the site: one slim line with Google Maps, or the demo that moves the plan to you.
let bannerHtml = '';
function renderBanner() {
  let html = '';
  const pos = state.user && userPlan();
  const away = pos ? distance(pos, anchorPlan()) : 0;
  if (away > FAR_M) {
    const km = away / 1000, gate = toLatLng([SITE.gates[0].x, SITE.gates[0].y]);
    const maps = `https://www.google.com/maps/dir/?api=1&destination=${gate.lat.toFixed(6)},${gate.lng.toFixed(6)}&travelmode=bicycling`;
    html = `<span>${km < 10 ? km.toFixed(1) : Math.round(km)} km away</span>
      <a class="link" href="${maps}" target="_blank" rel="noopener">Google Maps</a>
      <button type="button" class="link" data-action="demo">Demo here</button>`;
  }
  if (html === bannerHtml) return;
  bannerHtml = html;
  $('banner').innerHTML = html;
  $('banner').hidden = !html;
}

function renderUser() {
  const pos = userNear();
  map.setUser(pos, state.user?.accuracy, state.heading ?? state.user?.gpsHeading ?? null);
  map.fit(pos ? [pos] : []);
  renderBanner();
}

function updateRoute() {
  const s = spots.get(state.target), card = $('routeCard');
  if (!s) {
    map.setRoute(null);
    card.hidden = true;
    renderNear();
    return;
  }
  const pos = state.user && userPlan();
  const r = userNear() ? route(pos, s) : null;
  let title, detail;
  if (!pos) {
    title = `Directions to ${s.name}`;
    detail = 'Finding your location…';
  } else if (!r) {
    title = `Get to ${SITE.name} first`;
    detail = 'Use the Google Maps link on the plan';
  } else {
    const metres = Math.round(r.length);
    // The first legs are often just short steps onto the footpath; the direction to tell is the first real walk.
    const i = Math.max(0, r.points.findIndex((p, k) => k + 1 < r.points.length && distance(p, r.points[k + 1]) >= 8));
    title = metres < 8 ? `You have arrived at ${s.name}` : `Head ${heading(r.points[i], r.points[i + 1] ?? r.points[i])}`;
    detail = `${fmtM(r.length)} · about ${minutes(r.length)} min to ${s.name} · ${freeText(s)}`;
  }
  map.setRoute(r?.points ?? null, r?.fromOutside);
  card.innerHTML = `${ARROW}<div><strong>${esc(title)}</strong><span>${esc(detail)}</span></div>
    <button type="button" class="icon" data-end aria-label="End directions">✕</button>`;
  card.hidden = false;
  renderNear();
}

function startDirections(id) {
  state.target = id;
  if (!state.user) startLocating();
  updateRoute();
  renderMap();
  map.reset(); // show the whole route, even if the map was zoomed somewhere else
  if (state.selected) goHome();
}

function endDirections() {
  state.target = null;
  updateRoute();
  renderMap();
}

let headingQueued = false;
function onHeading(deg) {
  state.heading = deg;
  if (headingQueued) return;
  headingQueued = true;
  requestAnimationFrame(() => {
    headingQueued = false;
    if (state.user) renderUser();
  });
}

// Compass: iOS asks for permission (must happen inside a tap), Android reports absolute alpha.
function enableCompass() {
  if (state.compass) return;
  state.compass = true;
  const listen = () => {
    const absolute = 'ondeviceorientationabsolute' in window;
    window.addEventListener(absolute ? 'deviceorientationabsolute' : 'deviceorientation', e => {
      const raw = e.webkitCompassHeading ?? (e.absolute && e.alpha != null ? 360 - e.alpha : null);
      if (raw != null) onHeading((raw + (screen.orientation?.angle || 0)) % 360);
    });
  };
  const DOE = window.DeviceOrientationEvent;
  if (typeof DOE?.requestPermission === 'function') DOE.requestPermission().then(r => r === 'granted' && listen()).catch(() => {});
  else if (DOE) listen();
}

function startLocating() {
  if (state.user?.simulated || state.watchId !== null) return;
  if (!navigator.geolocation) {
    toast('This browser cannot share your location.', 'info');
    return;
  }
  enableCompass();
  setLocateState('searching');
  state.watchId = navigator.geolocation.watchPosition(onPosition, onPositionError, {
    enableHighAccuracy: true, maximumAge: 3000, timeout: 20000,
  });
}

function stopLocating() {
  if (state.user?.simulated) return;
  if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
  state.watchId = null;
  state.user = null;
  setLocateState('off');
  renderUser();
  updateRoute();
  renderList();
}

// Readings are blended with a small Kalman filter: each one counts by how precise it claims to be, and the
// estimate is allowed to drift at walking pace between readings. A laptop's Wi-Fi position that jumps by tens of
// metres settles down, while a walking phone with a good GPS fix still follows closely.
const DRIFT_M2_PER_S = 2;
function onPosition({ coords, timestamp }) {
  const prev = state.user?.lat != null ? state.user : null;
  let lat = coords.latitude, lng = coords.longitude, variance = Math.max(coords.accuracy || 50, 1) ** 2;
  if (prev) {
    const before = prev.variance + DRIFT_M2_PER_S * Math.max(0, (timestamp - prev.time) / 1000);
    const k = before / (before + variance);
    lat = prev.lat + k * (lat - prev.lat);
    lng = prev.lng + k * (lng - prev.lng);
    variance = (1 - k) * before;
  }
  state.user = {
    lat, lng, variance, time: timestamp, accuracy: Math.sqrt(variance),
    gpsHeading: coords.speed > 0.7 && Number.isFinite(coords.heading) ? coords.heading : null,
  };
  setLocateState('on');
  renderUser();
  updateRoute();
  renderList();
}

function onPositionError(err) {
  if (err.code === err.PERMISSION_DENIED) {
    stopLocating();
    toast('Location access was denied. Allow it in your browser settings to see where you are.', 'info');
  } else if (!state.user) {
    toast('Still looking for a GPS signal… Being outdoors helps.', 'info');
  }
}

// ---------- light / dark ----------

const THEME_KEY = 'bikeslot.theme';
const savedTheme = () => { try { return localStorage.getItem(THEME_KEY); } catch { return null; } };
function setTheme(theme, save) {
  const dark = theme === 'dark';
  document.documentElement.dataset.theme = theme;
  $('theme').textContent = dark ? '☀️' : '🌙';
  $('theme').setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  document.querySelector('meta[name="theme-color"]').content = dark ? '#0f141a' : '#f3f5f8';
  if (save) try { localStorage.setItem(THEME_KEY, theme); } catch { /* storage unavailable */ }
  map3d?.setTheme();
}

// ---------- 2D / 3D ----------

const MODE_KEY = 'bikeslot.mode';
async function setMode(next, save) {
  const button = $('mode');
  if (next === '3d' && !map3d) {
    button.disabled = true;
    $('map3d').hidden = false;
    try {
      const { createMap3D } = await import('./map3d.js');
      map3d = await createMap3D($('map3d'), selectRack, {
        insets: mapInsets,
        onRotate: deg => { if (mode === '3d') $('compass').style.setProperty('--rot', `${deg - SITE.bearing}deg`); },
      });
      renderMap();
      renderUser();
      updateRoute();
    } catch (err) {
      $('map3d').hidden = true;
      button.disabled = false;
      toast('The 3D view could not start on this device.', 'info');
      return;
    }
    button.disabled = false;
  }
  mode = next;
  const three = mode === '3d';
  $('map3d').hidden = !three;
  $('map').hidden = three;
  button.textContent = three ? '2D' : '3D';
  button.setAttribute('aria-label', three ? 'Show the flat map' : 'Show the map in 3D');
  if (!three) $('compass').style.setProperty('--rot', `${-SITE.bearing}deg`);
  else map3d.render();
  if (save) try { localStorage.setItem(MODE_KEY, mode); } catch { /* storage unavailable */ }
}
$('mode').addEventListener('click', () => setMode(mode === '3d' ? '2d' : '3d', true));
$('theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true));
// Until the visitor picks one, follow the device setting.
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
  if (!savedTheme()) setTheme(e.matches ? 'dark' : 'light', false);
});

// ---------- wiring ----------

document.querySelector('.zoombox').addEventListener('click', e => {
  const action = e.target.closest('[data-map]')?.dataset.map;
  if (action === 'in') map.zoom(1.5);
  else if (action === 'out') map.zoom(1 / 1.5);
  else if (action === 'home') map.reset();
});
// The opening view depends on the panels' size (e.g. when the route card appears).
new ResizeObserver(() => map.relayout()).observe($('dock'));

document.addEventListener('click', e => {
  const t = e.target.closest('[data-zone], [data-back], [data-home], [data-go], [data-end], [data-action]');
  if (!t) return;
  const d = t.dataset;
  if (d.zone) openSpot(d.zone);
  else if ('back' in d || 'home' in d) {
    e.preventDefault();
    goHome();
  } else if (d.go) startDirections(d.go);
  else if ('end' in d) endDirections();
  else if (d.action === 'demo' && state.user?.lat != null) {
    placeSiteAt(state.user.lat, state.user.lng);
    renderUser();
    updateRoute();
    renderList();
  }
});
$('locate').addEventListener('click', () => (state.watchId !== null ? stopLocating() : startLocating()));
window.addEventListener('hashchange', () => {
  if (!spotFromHash()) state.pushed = false;
  show();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && state.selected && !document.querySelector('.media.is-full')) goHome();
});

async function init() {
  setTheme(document.documentElement.dataset.theme, false);
  $('compass').style.setProperty('--rot', `${-SITE.bearing}deg`);
  let savedMode = null;
  try { savedMode = localStorage.getItem(MODE_KEY); } catch { /* storage unavailable */ }
  if (savedMode === '3d' || params.get('view') === '3d') setMode('3d', false);
  renderLegend();
  map.fit();
  if (state.user) {
    setLocateState('on');
    renderUser();
  }
  renderAll();
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    useSample();
  } else {
    try {
      state.sb = await connect(applyRow, () => {});
    } catch (err) {
      useSample();
      toast(`Could not load live data (${esc(err.message)}). Showing sample data.`, 'info');
    }
  }
  renderAll();
  tracking = true;
  const go = params.get('go'), open = params.get('spot');
  if (spots.has(go)) startDirections(go);
  else if (spots.has(open) && !spotFromHash()) history.replaceState(null, '', `#${open}`);
  show();
  setInterval(renderAll, 5000);
}

init();
