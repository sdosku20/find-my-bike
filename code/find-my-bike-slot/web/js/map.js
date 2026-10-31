// Bird's-eye site plan drawn as SVG in plan units (metres).
import { SITE, SPOTS } from '../config.js';
import { center } from './geo.js';

const NS = 'http://www.w3.org/2000/svg';
// Wi-Fi positions on laptops can be off by 50 m or more; a ring that large would cover half the plan.
const MAX_RING_M = 9;

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
  const v = SITE.view, f = SITE.fence;
  // Land well beyond the plan, so wide or tall screens show surroundings instead of empty space.
  el('rect', { x: v.x - 400, y: v.y - 400, width: v.w + 800, height: v.h + 800, class: 'm-land' }, g);
  for (const [x, y, w, h] of SITE.around?.blocks || []) el('rect', { x, y, width: w, height: h, rx: 2, class: 'm-block' }, g);
  for (const [cx, cy, r] of SITE.around?.trees || []) el('circle', { cx, cy, r, class: 'm-tree is-far' }, g);
  for (const st of SITE.streets) {
    el('rect', { ...box(st), class: 'm-street' }, g);
    const mid = st.vertical ? st.x + st.w / 2 : st.y + st.h / 2;
    if (st.vertical) line(g, [mid, st.y], [mid, st.y + st.h], 'm-street-line');
    else line(g, [st.x, mid], [st.x + st.w, mid], 'm-street-line');
  }
  el('rect', { ...box(f), rx: 4, class: 'm-site' }, g);
  const walk = el('g', { class: 'm-walk' }, g);
  for (const [a, b] of SITE.paths) line(walk, SITE.nodes[a], SITE.nodes[b]);
  for (const gate of SITE.gates) line(walk, [gate.x, gate.y], gate.street);
  if (SITE.plaza) {
    const { x, y, r } = SITE.plaza;
    el('circle', { cx: x, cy: y, r, class: 'm-plaza' }, g);
    el('circle', { cx: x, cy: y, r: r * 0.38, class: 'm-fountain' }, g);
  }
  for (const [cx, cy, r] of SITE.trees || []) el('circle', { cx, cy, r, class: 'm-tree' }, g);
  for (const b of SITE.buildings) {
    shape(g, b, 'm-shadow', 0.9, 1.3);
    shape(g, b, `m-building${b.tone ? ` is-${b.tone}` : ''}`);
    const [bx, by] = center(b);
    label(g, bx, by + 1.3, b.label, 'm-building-label');
  }
  for (const st of SITE.streets) {
    const [x, y] = st.labelAt;
    const t = label(g, x, y, st.label.toUpperCase(), 'm-street-label', st.vertical ? 'middle' : 'start');
    if (st.vertical) t.setAttribute('transform', `rotate(-90 ${x} ${y})`);
  }
  for (const gate of SITE.gates) {
    const { x, y } = gate, [sx, sy] = gate.street;
    const turn = (Math.atan2(y - sy, x - sx) * 180) / Math.PI; // the arrow points into the site
    el('path', { d: 'M-2.4 -3.2L2.8 0L-2.4 3.2Z', class: 'm-gate', transform: `translate(${x} ${y}) rotate(${turn})` }, g);
    // A gate on the top or bottom fence is labelled just outside it, one on a side fence just inside.
    const vertical = Math.abs(x - sx) < 1;
    label(g, vertical ? x + 3.6 : x + 3.2, vertical ? y + 3.5 : y - 4, gate.label.toUpperCase(), 'm-gate-label', 'start');
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
  let main, sub = null;
  if (horizontal) {
    const t = el('text', { x: cx, y: cy + 1.6, class: 'm-ztext', 'text-anchor': 'middle' }, g);
    el('tspan', { class: 'm-zname' }, t).textContent = `${name} · `;
    main = el('tspan', { class: 'm-zcount' }, t);
  } else {
    label(g, cx, cy - 7.5, name, 'm-ztext m-zname');
    main = label(g, cx, cy + 2.6, '–', 'm-ztext m-zbig');
    sub = label(g, cx, cy + 8, '', 'm-ztext m-zsub');
  }
  const live = spot.camera ? el('circle', { cx: rack.x + rack.w - 2.8, cy: rack.y + 2.8, r: 1.6, class: 'm-live' }, g) : null;

  g.addEventListener('click', () => onSelect(spot.id));
  g.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(spot.id);
    }
  });
  return { g, main, sub, live };
}

export function createMap(svg, onSelect) {
  svg.replaceChildren();
  drawGround(svg);
  const routeLayer = el('g', { class: 'm-route' }, svg);
  const spots = new Map(SPOTS.map(spot => [spot.id, drawSpot(svg, spot, onSelect)]));
  const userLayer = el('g', { class: 'm-user' }, svg);

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

    // Show the whole site, widened to include any extra points (e.g. the user nearby).
    fit(extra = []) {
      let { x, y, w, h } = SITE.view;
      let x2 = x + w, y2 = y + h;
      for (const [px, py] of extra) {
        x = Math.min(x, px - 10); y = Math.min(y, py - 10);
        x2 = Math.max(x2, px + 10); y2 = Math.max(y2, py + 10);
      }
      svg.setAttribute('viewBox', `${x} ${y} ${x2 - x} ${y2 - y}`);
    },
  };
}
