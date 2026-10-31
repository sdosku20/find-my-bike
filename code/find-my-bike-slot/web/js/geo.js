// Plan geometry: GPS <-> plan coordinates, and walking directions on the site.
import { SITE, SPOTS } from '../config.js';

const R = 6371008.8;
const RAD = Math.PI / 180;
const DEMO_KEY = 'bikeslot.demoAnchor';
const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];

let demoAnchor = null;
try { demoAnchor = JSON.parse(localStorage.getItem(DEMO_KEY)); } catch { /* storage unavailable */ }

export const anchor = () => demoAnchor || SITE.anchor;
export const isDemo = () => Boolean(demoAnchor);
export const distance = ([x1, y1], [x2, y2]) => Math.hypot(x2 - x1, y2 - y1);
export const outline = r => r.points || [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];
export function center(r) {
  if (!r.points) return [r.x + r.w / 2, r.y + r.h / 2];
  const n = r.points.length;
  return [r.points.reduce((t, p) => t + p[0], 0) / n, r.points.reduce((t, p) => t + p[1], 0) / n];
}
const inside = ([x, y], r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;

// A flat-earth approximation around the anchor; accurate to centimetres over a site this size.
export function toPlan(lat, lng, a = anchor()) {
  const e = (lng - a.lng) * RAD * R * Math.cos(a.lat * RAD);
  const n = (lat - a.lat) * RAD * R;
  const t = SITE.bearing * RAD;
  return [a.x + e * Math.cos(t) - n * Math.sin(t), a.y - e * Math.sin(t) - n * Math.cos(t)];
}

export function toLatLng([x, y], a = anchor()) {
  const t = SITE.bearing * RAD, r = x - a.x, u = a.y - y;
  const e = r * Math.cos(t) + u * Math.sin(t);
  const n = u * Math.cos(t) - r * Math.sin(t);
  return { lat: a.lat + n / R / RAD, lng: a.lng + e / (R * Math.cos(a.lat * RAD)) / RAD };
}

// Demo mode: move the whole plan so the user stands at the main gate.
export function placeSiteAt(lat, lng) {
  const { x, y } = SITE.anchor, gate = SITE.gates[0];
  demoAnchor = { x, y, ...toLatLng([x, y], { x: gate.x, y: gate.y, lat, lng }) };
  try { localStorage.setItem(DEMO_KEY, JSON.stringify(demoAnchor)); } catch { /* storage unavailable */ }
}

export function resetSite() {
  demoAnchor = null;
  try { localStorage.removeItem(DEMO_KEY); } catch { /* storage unavailable */ }
}

// Compass direction of a step on the plan, e.g. "north-east".
export function heading([x1, y1], [x2, y2]) {
  const t = SITE.bearing * RAD, r = x2 - x1, u = y1 - y2;
  const e = r * Math.cos(t) + u * Math.sin(t);
  const n = u * Math.cos(t) - r * Math.sin(t);
  const deg = (Math.atan2(e, n) / RAD + 360) % 360;
  return COMPASS[Math.round(deg / 45) % 8];
}

const side = (a, b, p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
const EPS = 1e-6;
// True when the segments cross at a point inside both (merely touching does not count).
function cut(a, b, c, d) {
  const d1 = side(c, d, a), d2 = side(c, d, b), d3 = side(a, b, c), d4 = side(a, b, d);
  return ((d1 > EPS && d2 < -EPS) || (d1 < -EPS && d2 > EPS)) && ((d3 > EPS && d4 < -EPS) || (d3 < -EPS && d4 > EPS));
}
function within([x, y], poly) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}
// True when the segment passes through the inside of the shape (a rectangle or an outline).
function crosses(a, b, shape) {
  const poly = outline(shape);
  for (let i = 0; i < poly.length; i++) if (cut(a, b, poly[i], poly[(i + 1) % poly.length])) return true;
  return within([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], poly);
}

function nearestOn(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return [a[0] + t * dx, a[1] + t * dy];
}

const NEAR_RACK_M = 18; // this close, walk straight to the rack if nothing is in the way

// Shortest walk from `from` to the spot's rack along the walkways, never through a building
// or another rack.
export function route(from, spot) {
  const points = { ...SITE.nodes, start: from, dest: center(spot.rack) };
  const links = {};
  const link = (a, b) => {
    const d = distance(points[a], points[b]);
    (links[a] ||= []).push([b, d]);
    (links[b] ||= []).push([a, d]);
  };
  SITE.paths.forEach(([a, b]) => link(a, b));
  link(spot.access, 'dest');

  const onSite = inside(from, SITE.fence);
  if (onSite) {
    // Join the walkways at their nearest point, as a person would, instead of cutting across the grass.
    let join = null;
    for (const [a, b] of SITE.paths) {
      const p = nearestOn(from, SITE.nodes[a], SITE.nodes[b]);
      if (!join || distance(from, p) < distance(from, join.p)) join = { a, b, p };
    }
    points.join = join.p;
    link('start', 'join');
    link('join', join.a);
    link('join', join.b);
    const obstacles = [...SITE.buildings, ...SPOTS.map(s => s.rack)];
    const blocked = obstacles.some(r => r !== spot.rack && crosses(from, points.dest, r));
    if (distance(from, points.dest) < NEAR_RACK_M && !blocked) link('start', 'dest');
  } else {
    const gate = SITE.gates.reduce((a, b) => (distance(from, [a.x, a.y]) <= distance(from, [b.x, b.y]) ? a : b));
    link('start', gate.node);
  }

  const best = { start: 0 }, prev = {}, todo = new Set(Object.keys(points));
  while (todo.size) {
    let u = null;
    for (const k of todo) if (k in best && (u === null || best[k] < best[u])) u = k;
    if (u === null || u === 'dest') break;
    todo.delete(u);
    for (const [v, w] of links[u] || []) {
      if (todo.has(v) && !(best[v] <= best[u] + w)) {
        best[v] = best[u] + w;
        prev[v] = u;
      }
    }
  }
  if (!('dest' in best)) return null;
  const path = [];
  for (let k = 'dest'; k; k = prev[k]) {
    if (!path.length || distance(points[k], path[0]) > 0.5) path.unshift(points[k]); // skip repeated points
  }
  return { points: path, length: best.dest, fromOutside: !onSite };
}
