// Bird's-eye site plan drawn as SVG in plan units (metres), with zoom and pan.
import { SITE, SPOTS } from '../config.js';
import { center } from './geo.js';

const NS = 'http://www.w3.org/2000/svg';
// Wi-Fi positions on laptops can be off by 50 m or more; a ring that large would cover half the plan.
const MAX_RING_M = 9;
const MIN_VIEW_M = 30;   // closest zoom: about 30 m across the screen
const MAX_ZOOM_OUT = 1.8; // furthest zoom: this many times the opening view
const DRAG_PX = 5;       // a press that moves less than this is a tap

function el(tag, attrs, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  if (parent) parent.append(node);
  return node;
}
const box = r => ({ x: r.x, y: r.y, width: r.w, height: r.h });
const line = (parent, [x1, y1], [x2, y2], cls) => el('line', { x1, y1, x2, y2, ...(cls && { class: cls }) }, parent);
function label(parent, x, y, content, cls, anchor = 'middle') {
  const t = el('text', { x, y, class: cls, 'text-anchor': anchor }, parent);
  t.textContent = content;
  return t;
}

const shapeAttrs = r => (r.points ? { points: r.points.map(p => p.join(',')).join(' ') } : { ...box(r), rx: 2.5 });
const shape = (parent, r, cls, dx = 0, dy = 0) => {
  const node = el(r.points ? 'polygon' : 'rect', { ...shapeAttrs(r), class: cls }, parent);
  if (dx || dy) node.setAttribute('transform', `translate(${dx} ${dy})`);
  return node;
};

function drawGround(svg) {
  const g = el('g', {}, svg);
  const v = SITE.view;
  // Land well beyond the plan, so any screen shape and any pan shows surroundings instead of empty space.
  el('rect', { x: v.x - 600, y: v.y - 600, width: v.w + 1200, height: v.h + 1200, class: 'm-land' }, g);
  for (const [x, y, w, h] of SITE.around?.blocks || []) el('rect', { x, y, width: w, height: h, rx: 2, class: 'm-block' }, g);
  for (const [cx, cy, r] of SITE.around?.trees || []) el('circle', { cx, cy, r, class: 'm-tree is-far' }, g);
  for (const st of SITE.streets) {
    el('rect', { ...box(st), class: 'm-street' }, g);
    const mid = st.vertical ? st.x + st.w / 2 : st.y + st.h / 2;
    if (st.vertical) line(g, [mid, st.y], [mid, st.y + st.h], 'm-street-line');
    else line(g, [st.x, mid], [st.x + st.w, mid], 'm-street-line');
  }
  el('rect', { ...box(SITE.fence), rx: 4, class: 'm-site' }, g);
  if (SITE.park) {
    const { pond } = SITE.park;
    el('rect', { ...box(SITE.park), rx: 6, class: 'm-park' }, g);
    if (pond) el('ellipse', { cx: pond.x, cy: pond.y, rx: pond.rx, ry: pond.ry, class: 'm-pond' }, g);
  }
  const walk = el('g', { class: 'm-walk' }, g);
  for (const [a, b] of SITE.paths) line(walk, SITE.nodes[a], SITE.nodes[b]);
  for (const gate of SITE.gates) line(walk, [gate.x, gate.y], gate.street);
  // Zebra crossings: stripes across the road where a walkway crosses it.
  for (const c of SITE.crossings || []) {
    el('rect', { ...box(c), class: 'm-street' }, g);
    for (let x = c.x + 0.5; x < c.x + c.w; x += 2) el('rect', { x, y: c.y + 0.6, width: 1, height: c.h - 1.2, class: 'm-zebra' }, g);
  }
  if (SITE.plaza) {
    const { x, y, r } = SITE.plaza;
    el('circle', { cx: x, cy: y, r, class: 'm-plaza' }, g);
    el('circle', { cx: x, cy: y, r: r * 0.38, class: 'm-fountain' }, g);
  }
  for (const [cx, cy, r] of SITE.trees || []) el('circle', { cx, cy, r, class: 'm-tree' }, g);
  for (const b of SITE.buildings) {
    shape(g, b, 'm-shadow', 0.9, 1.3);
    shape(g, b, `m-building${b.tone ? ` is-${b.tone}` : ''}`);
    const [bx, by] = b.labelAt || [center(b)[0], center(b)[1] + 1.3];
    label(g, bx, by, b.label, 'm-building-label');
  }
  if (SITE.park?.label) label(g, ...SITE.park.labelAt, SITE.park.label.toUpperCase(), 'm-park-label');
  for (const st of SITE.streets) {
    const [x, y] = st.labelAt;
    const t = label(g, x, y, st.label.toUpperCase(), 'm-street-label', st.vertical ? 'middle' : 'start');
    if (st.vertical) t.setAttribute('transform', `rotate(-90 ${x} ${y})`);
  }
  for (const gate of SITE.gates) {
    const { x, y } = gate, [sx, sy] = gate.street;
    const turn = (Math.atan2(y - sy, x - sx) * 180) / Math.PI; // the arrow points into the site
    el('path', { d: 'M-2.4 -3.2L2.8 0L-2.4 3.2Z', class: 'm-gate', transform: `translate(${x} ${y}) rotate(${turn})` }, g);
    // Labelled just inside the fence, next to the arrow.
    const vertical = Math.abs(x - sx) < 1;
    label(g, vertical ? x + 3.6 : x + 3.2, vertical ? (sy > y ? y - 1.6 : y + 3.5) : y - 4, gate.label.toUpperCase(), 'm-gate-label', 'start');
  }
}

// A rack is a soft-coloured box with its name and free count inside, like a parking bay on a site plan.
function drawSpot(svg, spot, onSelect) {
  const { rack } = spot;
  const horizontal = rack.w >= rack.h;
  const name = spot.name.replace(/\s+rack$/i, '');
  const g = el('g', { class: 'm-spot st-off', tabindex: 0, role: 'button', 'data-id': spot.id }, svg);
  el('rect', { x: rack.x - 1.8, y: rack.y - 1.8, width: rack.w + 3.6, height: rack.h + 3.6, rx: 3.6, class: 'm-sel' }, g);
  el('rect', { ...box(rack), rx: 2.4, class: 'm-rack' }, g);
  const [cx, cy] = center(rack);
  let main, sub = null, texts;
  if (horizontal) {
    const t = el('text', { x: cx, y: cy + 1.6, class: 'm-ztext', 'text-anchor': 'middle' }, g);
    el('tspan', { class: 'm-zname' }, t).textContent = `${name} · `;
    main = el('tspan', { class: 'm-zcount' }, t);
    texts = [[t, rack.w - 3, cy]];
  } else {
    const top = label(g, cx, cy - 7.5, name, 'm-ztext m-zname');
    main = label(g, cx, cy + 2.6, '–', 'm-ztext m-zbig');
    sub = label(g, cx, cy + 8, '', 'm-ztext m-zsub');
    texts = [[top, rack.w - 2, cy - 8.8], [main, rack.w - 2, cy], [sub, rack.w - 2, cy + 7]];
  }
  const live = spot.camera ? el('circle', { cx: rack.x + rack.w - 2.8, cy: rack.y + 2.8, r: 1.6, class: 'm-live' }, g) : null;

  g.addEventListener('click', () => onSelect(spot.id));
  g.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(spot.id);
    }
  });
  return { g, main, sub, live, texts: texts.map(([t, max, y]) => ({ t, max, x: cx, y })) };
}

// Shrinks a label that is wider than its rack (e.g. "Gate · 10 free" in a short box).
function fitText({ t, max, x, y }) {
  t.removeAttribute('transform');
  const length = t.getComputedTextLength();
  if (length > max) t.setAttribute('transform', `translate(${x} ${y}) scale(${max / length}) translate(${-x} ${-y})`);
}

// insets(): screen space taken by overlays ({ top, right, bottom, left } in px), kept clear in the opening view.
export function createMap(svg, onSelect, { insets = () => ({ top: 0, right: 0, bottom: 0, left: 0 }) } = {}) {
  svg.replaceChildren();
  drawGround(svg);
  const routeLayer = el('g', { class: 'm-route' }, svg);
  const spots = new Map(SPOTS.map(spot => [spot.id, drawSpot(svg, spot, onSelect)]));
  const userLayer = el('g', { class: 'm-user' }, svg);
  const v = SITE.view;
  const world = { x: v.x - 140, y: v.y - 140, w: v.w + 280, h: v.h + 280 }; // the view centre stays in here

  let content = { ...v }, view = null, moved = false;
  const size = () => [svg.clientWidth || 1, svg.clientHeight || 1];

  // The opening view: the content as large as possible in the space the overlays leave free.
  function homeView() {
    const [W, H] = size(), i = insets();
    const aw = Math.max(80, W - i.left - i.right), ah = Math.max(80, H - i.top - i.bottom);
    const s = Math.min(aw / content.w, ah / content.h);
    return {
      x: content.x - (i.left + (aw - content.w * s) / 2) / s,
      y: content.y - (i.top + (ah - content.h * s) / 2) / s,
      w: W / s,
      h: H / s,
    };
  }

  function show(next) {
    const [W, H] = size(), home = homeView();
    const w = Math.min(Math.max(next.w, MIN_VIEW_M), home.w * MAX_ZOOM_OUT), h = (w * H) / W;
    const cx = Math.min(world.x + world.w, Math.max(world.x, next.x + next.w / 2));
    const cy = Math.min(world.y + world.h, Math.max(world.y, next.y + next.h / 2));
    view = { x: cx - w / 2, y: cy - h / 2, w, h };
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
  }

  function zoomAt(factor, px, py) {
    const [W, H] = size();
    const ux = view.x + (px / W) * view.w, uy = view.y + (py / H) * view.h;
    const w = view.w / factor, h = view.h / factor;
    moved = true;
    show({ x: ux - (px / W) * w, y: uy - (py / H) * h, w, h });
  }

  function panBy(dx, dy) {
    const per = view.w / size()[0];
    moved = true;
    show({ ...view, x: view.x - dx * per, y: view.y - dy * per });
  }

  // ---------- gestures: drag to pan, wheel / pinch / double-click to zoom ----------
  const pointers = new Map();
  let drag = null, pinch = null, suppressClick = false;
  const local = e => {
    const r = svg.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const pinchState = () => {
    const [a, b] = [...pointers.values()];
    return { mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], dist: Math.hypot(a[0] - b[0], a[1] - b[1]) };
  };

  svg.addEventListener('pointerdown', e => {
    if (e.button > 0) return;
    pointers.set(e.pointerId, local(e));
    suppressClick = false;
    if (pointers.size === 1) drag = { id: e.pointerId, last: local(e), start: local(e), active: false };
    else if (pointers.size === 2) {
      drag = null;
      pinch = pinchState();
      for (const id of pointers.keys()) try { svg.setPointerCapture(id); } catch { /* already released */ }
    }
  });
  svg.addEventListener('pointermove', e => {
    if (!pointers.has(e.pointerId)) return;
    const p = local(e);
    pointers.set(e.pointerId, p);
    if (pinch && pointers.size === 2) {
      const now = pinchState();
      panBy(now.mid[0] - pinch.mid[0], now.mid[1] - pinch.mid[1]);
      if (pinch.dist) zoomAt(now.dist / pinch.dist, ...now.mid);
      pinch = now;
    } else if (drag && e.pointerId === drag.id) {
      if (!drag.active && Math.hypot(p[0] - drag.start[0], p[1] - drag.start[1]) > DRAG_PX) {
        drag.active = true;
        svg.classList.add('is-dragging');
        // Captured only once it is a drag, so a tap still reaches the rack under the finger.
        try { svg.setPointerCapture(e.pointerId); } catch { /* already released */ }
      }
      if (drag.active) panBy(p[0] - drag.last[0], p[1] - drag.last[1]);
      drag.last = p;
    }
  });
  const release = e => {
    if (!pointers.delete(e.pointerId)) return;
    if (drag?.active || pinch) suppressClick = true;
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) {
      drag = null;
      svg.classList.remove('is-dragging');
    }
  };
  svg.addEventListener('pointerup', release);
  svg.addEventListener('pointercancel', release);
  // A drag that ends on a rack must not open it.
  svg.addEventListener('click', e => {
    if (!suppressClick) return;
    suppressClick = false;
    e.stopPropagation();
    e.preventDefault();
  }, true);
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), ...local(e));
  }, { passive: false });
  svg.addEventListener('dblclick', e => {
    if (!e.target.closest('.m-spot')) zoomAt(2, ...local(e));
  });

  const fitLabels = () => spots.forEach(node => node.texts.forEach(fitText));
  new ResizeObserver(() => {
    if (!view || !moved) show(homeView());
    else show(view);
    fitLabels();
  }).observe(svg);
  document.fonts?.ready.then(fitLabels);

  return {
    // items: [{ id, level, free, text, label, live, flash }]
    update(items, highlightId) {
      for (const item of items) {
        const node = spots.get(item.id);
        if (!node) continue;
        const cls = `m-spot st-${item.level}${item.id === highlightId ? ' is-selected' : ''}${item.flash ? ' flash' : ''}`;
        if (node.g.getAttribute('class') !== cls) node.g.setAttribute('class', cls);
        node.g.setAttribute('aria-label', item.label);
        if (!node.sub) {
          node.main.textContent = item.text;
        } else {
          // Tall, narrow racks: the number large, with "free" underneath.
          const counted = item.free != null && item.level !== 'full';
          node.main.textContent = counted ? String(item.free) : item.level === 'full' ? 'Full' : '–';
          node.main.classList.toggle('is-word', !counted);
          node.sub.textContent = counted ? 'free' : item.level === 'full' ? '' : item.text.toLowerCase();
        }
        node.live?.classList.toggle('is-on', item.live);
        node.texts.forEach(fitText);
      }
    },

    setRoute(points, dashedStart) {
      routeLayer.replaceChildren();
      if (!points) return;
      const toAttr = pts => pts.map(p => p.join(',')).join(' ');
      const solid = dashedStart ? points.slice(1) : points;
      el('polyline', { points: toAttr(solid), class: 'm-route-casing' }, routeLayer);
      el('polyline', { points: toAttr(solid), class: 'm-route-line' }, routeLayer);
      if (dashedStart) el('polyline', { points: toAttr(points.slice(0, 2)), class: 'm-route-line is-dashed' }, routeLayer);
      const [ex, ey] = points[points.length - 1];
      el('circle', { cx: ex, cy: ey, r: 2.4, class: 'm-route-end' }, routeLayer);
    },

    setUser(pos, accuracy, headingDeg) {
      userLayer.replaceChildren();
      if (!pos) return;
      const [x, y] = pos;
      if (accuracy > 2.5) el('circle', { cx: x, cy: y, r: Math.min(accuracy, MAX_RING_M), class: 'm-accuracy' }, userLayer);
      if (headingDeg != null) {
        el('path', {
          d: 'M0 0 L-4.5 -11 A12 12 0 0 1 4.5 -11 Z',
          class: 'm-heading',
          transform: `translate(${x} ${y}) rotate(${headingDeg - SITE.bearing})`,
        }, userLayer);
      }
      el('circle', { cx: x, cy: y, r: 4.4, class: 'm-you-pulse' }, userLayer);
      el('circle', { cx: x, cy: y, r: 2, class: 'm-you' }, userLayer);
    },

    // The opening view covers the plan plus any extra points (e.g. you, nearby). It is only applied
    // while you have not zoomed or dragged yourself; reset() always returns to it.
    fit(extra = []) {
      let x = v.x, y = v.y, x2 = v.x + v.w, y2 = v.y + v.h;
      for (const [px, py] of extra) {
        x = Math.min(x, px - 10); y = Math.min(y, py - 10);
        x2 = Math.max(x2, px + 10); y2 = Math.max(y2, py + 10);
      }
      content = { x, y, w: x2 - x, h: y2 - y };
      if (!moved) show(homeView());
    },
    reset() {
      moved = false;
      show(homeView());
    },
    zoom(factor) {
      const [W, H] = size();
      zoomAt(factor, W / 2, H / 2);
    },
    relayout() {
      if (!moved) show(homeView());
    },
  };
}
