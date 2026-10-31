// 3D view of the same site plan, drawn with three.js. Plan units are metres: plan (x, y) is world (x, height, y).
// It offers the same calls as the 2D map (update, setRoute, setUser, fit, reset, zoom, focus, ...).
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
import { SITE, SPOTS } from '../config.js';
import { center, outline, pondOutline } from './geo.js';

const FLOOR_M = 3.4;
const FOV = 38;
const DRAG_PX = 5;
const MIN_DIST = 14, MAX_DIST = 900;
const MIN_PITCH = 0.42, MAX_PITCH = 1.45; // radians above the ground
const MAX_RING_M = 9;
const BIKE_COLOURS = ['#1b1f24', '#2c3e5e', '#e3e7ea', '#c0392b', '#2f5d46', '#8a5a44', '#33403a', '#1b1f24', '#5b6b7a'];

// Strongly separated colours per theme: the light theme keeps darker walls and roads so nothing washes out.
const PALETTE = {
  light: {
    sky: '#dbe6ee', land: '#c3d2b8', site: '#d6e2c9', road: '#8994a0', roadLine: '#f4f6f7', walk: '#f4efe2',
    park: '#9fca88', hedge: '#77a862', water: '#6fb0d2', waterDeep: '#2f76a6', shore: '#d8cba5', lily: '#4f9a3c', plaza: '#e8dfcc', fountain: '#7ab4d4',
    wall: '#a3afbd', roof: '#7f8c9b', wallAlt: '#c8ae92', roofAlt: '#a38a70', window: '#4b5f74',
    house: '#e2d6c4', houseRoof: '#bfb09c', npcWall: '#b7bec7', npcRoof: '#959ea8', tree: '#4c9644', treeFar: '#6c9f5f', pine: '#2c7440', trunk: '#76563a',
    clay: '#c4643a', courtLine: '#ffffff', net: '#2b3138', tennisLot: '#6fa25e', metal: '#59626c', glass: '#8fd0ee',
    shelter: '#a9cbe0', label: '#26313b', zebra: '#ffffff', fence: '#7a887e',
    hemi: 1.05, sun: 1.25, ambient: 0.25,
  },
  dark: {
    sky: '#0a0f15', land: '#17211a', site: '#1d2a21', road: '#343e48', roadLine: '#8c96a0', walk: '#3c4940',
    park: '#21402a', hedge: '#2e5a39', water: '#2a6788', waterDeep: '#123a55', shore: '#47432f', lily: '#356f2c', plaza: '#363e38', fountain: '#2f6f93',
    wall: '#56636f', roof: '#3d4853', wallAlt: '#65574a', roofAlt: '#4b4138', window: '#e3c27a',
    house: '#46514b', houseRoof: '#363f3a', npcWall: '#454e58', npcRoof: '#353d46', tree: '#2e6a39', treeFar: '#285532', pine: '#1e5430', trunk: '#5b4431',
    clay: '#9e4f2d', courtLine: '#d9dde1', net: '#c8ced4', tennisLot: '#2b4a31', metal: '#a9b3bc', glass: '#5fb2d6',
    shelter: '#5b86a0', label: '#dfe5ea', zebra: '#9aa3ab', fence: '#56645b',
    hemi: 0.55, sun: 0.75, ambient: 0.18,
  },
};

const V = (x, y, h = 0) => new THREE.Vector3(x, h, y);
const rectPts = r => [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];
const toShape = pts => new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, -y)));
const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

// Joins several geometries into one (positions and normals only), for instanced bikes and trees.
function merge(list) {
  const parts = list.map(g => (g.index ? g.toNonIndexed() : g));
  const count = parts.reduce((n, g) => n + g.attributes.position.count, 0);
  const pos = new Float32Array(count * 3), nor = new Float32Array(count * 3);
  let o = 0;
  for (const g of parts) {
    pos.set(g.attributes.position.array, o * 3);
    nor.set(g.attributes.normal.array, o * 3);
    o += g.attributes.position.count;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  return out;
}
function tube(a, b, r) {
  const d = new THREE.Vector3().subVectors(b, a), g = new THREE.CylinderGeometry(r, r, d.length(), 6);
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.clone().normalize()));
  g.translate((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2);
  return g;
}

// A city bike along local x, standing on y = 0, drawn about 1.35 times life size so it reads as a bike from
// the overview. Three parts so each can have its own colour: the painted frame, the black rubber and
// saddle, and the metal (rims, spokes, cranks, seat post, handlebar stem).
const BIKE_SCALE = 1.35;
function bikeGeometries() {
  const p = (x, y, z = 0) => new THREE.Vector3(x, y, z);
  const R = 0.34, rearHub = p(-0.54, R), frontHub = p(0.56, R), bb = p(-0.06, 0.3), seatTop = p(-0.24, 0.82);
  const headTop = p(0.4, 0.84), headLow = p(0.44, 0.7), seatPost = p(-0.29, 0.95), stemTop = p(0.37, 1.02);
  const frame = merge([
    tube(bb, seatTop, 0.034), tube(seatTop, headTop, 0.032), tube(bb, headLow, 0.04), tube(headLow, headTop, 0.036),
    tube(p(-0.54, R, 0.06), p(-0.06, 0.3, 0.03), 0.022), tube(p(-0.54, R, -0.06), p(-0.06, 0.3, -0.03), 0.022), // chain stays
    tube(p(-0.54, R, 0.06), p(-0.24, 0.82, 0.02), 0.02), tube(p(-0.54, R, -0.06), p(-0.24, 0.82, -0.02), 0.02), // seat stays
    tube(headLow, p(0.56, R, 0.05), 0.024), tube(headLow, p(0.56, R, -0.05), 0.024), // fork
    new THREE.TorusGeometry(R + 0.07, 0.012, 4, 14, Math.PI * 0.55).rotateZ(Math.PI * 0.25).translate(-0.54, R, 0), // rear mudguard
    new THREE.TorusGeometry(R + 0.07, 0.012, 4, 14, Math.PI * 0.55).rotateZ(Math.PI * 0.2).translate(0.56, R, 0), // front mudguard
  ]);
  const tyre = c => new THREE.TorusGeometry(R, 0.045, 6, 22).translate(c.x, c.y, 0);
  const dark = merge([
    tyre(rearHub), tyre(frontHub),
    new THREE.BoxGeometry(0.27, 0.06, 0.15).translate(-0.3, 0.99, 0), // saddle
    tube(p(0.34, 1.03, -0.3), p(0.34, 1.03, -0.22), 0.03), tube(p(0.34, 1.03, 0.22), p(0.34, 1.03, 0.3), 0.03), // grips
    new THREE.BoxGeometry(0.1, 0.03, 0.06).translate(-0.06, 0.12, 0.13), new THREE.BoxGeometry(0.1, 0.03, 0.06).translate(-0.06, 0.48, -0.13), // pedals
  ]);
  const spokes = c => Array.from({ length: 6 }, (_, i) => {
    const a = (i / 6) * Math.PI;
    return tube(p(c.x - Math.cos(a) * (R - 0.04), c.y - Math.sin(a) * (R - 0.04)), p(c.x + Math.cos(a) * (R - 0.04), c.y + Math.sin(a) * (R - 0.04)), 0.006);
  });
  const metal = merge([
    new THREE.TorusGeometry(R - 0.035, 0.014, 4, 22).translate(rearHub.x, rearHub.y, 0), new THREE.TorusGeometry(R - 0.035, 0.014, 4, 22).translate(frontHub.x, frontHub.y, 0),
    ...spokes(rearHub), ...spokes(frontHub),
    tube(seatTop, seatPost, 0.018), tube(headTop, stemTop, 0.02), tube(p(0.34, 1.03, -0.24), p(0.34, 1.03, 0.24), 0.017), // seat post, stem, bar
    new THREE.CylinderGeometry(0.09, 0.09, 0.02, 14).rotateX(Math.PI / 2).translate(-0.06, 0.3, 0.07), // chainring
    tube(p(-0.06, 0.3, 0.1), p(-0.06, 0.12, 0.13), 0.014), tube(p(-0.06, 0.3, -0.1), p(-0.06, 0.48, -0.13), 0.014), // cranks
  ]);
  for (const g of [frame, dark, metal]) g.scale(BIKE_SCALE, BIKE_SCALE, BIKE_SCALE);
  return { frame, dark, metal };
}

// The pond: a sandy shore, an outer ring of shallow water and a deeper middle.
function pondShapes(pond) {
  const ring = k => pondOutline(pond, k);
  return { shore: ring(1.16), shallow: ring(1), deep: ring(0.62) };
}

// Window pattern for office walls: one window per 4 m and per floor.
function windowTexture(wall, win) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = wall;
  g.fillRect(0, 0, 64, 64);
  g.fillStyle = win;
  g.fillRect(14, 18, 36, 26);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / 4, 1 / FLOOR_M);
  return t;
}

export async function createMap3D(container, onSelect, { insets = () => ({ top: 0, right: 0, bottom: 0, left: 0 }), onRotate = () => {} } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.append(renderer.domElement);
  const canvas = renderer.domElement;
  canvas.style.touchAction = 'none';

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 2, 3000);
  const mats = {};
  const mat = (key, extra = {}) => (mats[key] ||= new THREE.MeshStandardMaterial({ roughness: 0.92, metalness: 0, ...extra }));
  const themeKey = () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  let pal = PALETTE[themeKey()];

  // ---------- lights ----------
  const hemi = new THREE.HemisphereLight(0xffffff, 0x445544, pal.hemi);
  const ambient = new THREE.AmbientLight(0xffffff, pal.ambient);
  const sun = new THREE.DirectionalLight(0xffffff, pal.sun);
  sun.position.set(-90, 160, -40).add(V(68, 130));
  sun.target.position.copy(V(68, 130));
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -190, right: 190, top: 190, bottom: -190, near: 10, far: 520 });
  sun.shadow.bias = -0.0006;
  scene.add(hemi, ambient, sun, sun.target);

  // ---------- helpers that build the scene ----------
  const flat = (pts, h, key, extra) => {
    const m = new THREE.Mesh(new THREE.ShapeGeometry(toShape(pts)), mat(key, extra));
    m.rotation.x = -Math.PI / 2;
    m.position.y = h;
    m.receiveShadow = true;
    scene.add(m);
    return m;
  };
  const ellipsePts = (cx, cy, rx, ry, n = 40) => Array.from({ length: n }, (_, i) => [cx + Math.cos((i / n) * Math.PI * 2) * rx, cy + Math.sin((i / n) * Math.PI * 2) * ry]);
  const strip = (a, b, width, h, key, thick = 0.04) => {
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const m = new THREE.Mesh(new THREE.BoxGeometry(len, thick, width), mat(key));
    m.position.copy(V((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, h));
    m.rotation.y = -Math.atan2(b[1] - a[1], b[0] - a[0]);
    m.receiveShadow = true;
    scene.add(m);
    return m;
  };
  const block = (pts, height, sides, top, opts = {}) => {
    const shape = toShape(pts);
    for (const hole of opts.holes || []) shape.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, -y))));
    const g = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
    g.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(g, [top, sides]);
    m.castShadow = m.receiveShadow = true;
    scene.add(m);
    return m;
  };

  // A small text label that always faces the camera (buildings, park); rack pins are separate.
  const labels = [];
  function textSprite(text, x, y, h, size) {
    const c = document.createElement('canvas'), g = c.getContext('2d');
    c.width = 512; c.height = 96;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    // Kept soft and small: the racks are what people look for, buildings are only landmarks.
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0.72 }));
    s.position.copy(V(x, y, h));
    s.center.set(0.5, 0);
    s.userData = { draw: () => {
      g.clearRect(0, 0, 512, 96);
      g.font = '700 40px Figtree, system-ui, sans-serif';
      g.textAlign = 'center';
      g.lineWidth = 9;
      g.strokeStyle = pal === PALETTE.dark ? 'rgba(10,15,21,.85)' : 'rgba(255,255,255,.9)';
      g.fillStyle = pal.label;
      g.strokeText(text, 256, 62);
      g.fillText(text, 256, 62);
      tex.needsUpdate = true;
    }, size };
    s.userData.draw();
    scene.add(s);
    labels.push(s);
    return s;
  }

  // ---------- ground ----------
  const v = SITE.view;
  flat(rectPts({ x: v.x - 700, y: v.y - 700, w: v.w + 1400, h: v.h + 1400 }), 0, 'land');
  // Road centre dashes, all in one instanced mesh (within 320 m of the site; fog hides the rest).
  const dashes = [];
  for (const st of SITE.streets) {
    flat(rectPts(st), 0.04, 'road');
    const along = st.vertical ? st.h : st.w;
    for (let d = 2; d < along; d += 6) {
      const x = st.vertical ? st.x + st.w / 2 : st.x + d + 1.5, y = st.vertical ? st.y + d + 1.5 : st.y + st.h / 2;
      if (Math.abs(x - 68) < 320 && Math.abs(y - 130) < 320) dashes.push([x, y, st.vertical]);
    }
  }
  const dashMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(3, 0.02, 0.35), mat('roadLine'), dashes.length);
  dashes.forEach(([x, y, vertical], i) => dashMesh.setMatrixAt(i, new THREE.Matrix4().compose(V(x, y, 0.07),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(0, vertical ? Math.PI / 2 : 0, 0)), new THREE.Vector3(1, 1, 1))));
  dashMesh.receiveShadow = true;
  scene.add(dashMesh);
  flat(rectPts(SITE.fence), 0.02, 'site');
  if (SITE.park) {
    const p = SITE.park;
    flat(rectPts(p), 0.05, 'hedge');
    flat(rectPts({ x: p.x + 1.2, y: p.y + 1.2, w: p.w - 2.4, h: p.h - 2.4 }), 0.07, 'park');
    if (p.pond) {
      // Sandy shore, shallow water, a deeper glossy middle, lily pads and a few reeds.
      const pond = pondShapes(p.pond);
      flat(pond.shore, 0.09, 'shore');
      flat(pond.shallow, 0.11, 'water', { roughness: 0.15, metalness: 0.1 });
      flat(pond.deep, 0.13, 'waterDeep', { roughness: 0.05, metalness: 0.25 });
      const { x, y, rx, ry } = p.pond;
      for (const [dx, dy, r] of [[0.55, -0.3, 1.1], [0.68, 0.05, 0.8], [-0.62, 0.35, 0.95], [-0.5, 0.52, 0.7], [0.3, 0.55, 0.6]]) {
        const pad = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.05, 14, 1, false, 0.4, Math.PI * 1.85), mat('lily'));
        pad.position.copy(V(x + dx * rx, y + dy * ry, 0.16));
        scene.add(pad);
      }
      for (const a of [2.6, 2.9, 3.2, 5.9, 6.15, 4.5]) for (const [ox, h] of [[-0.3, 1.4], [0, 1.8], [0.35, 1.2]]) {
        const reed = new THREE.Mesh(new THREE.ConeGeometry(0.07, h, 4), mat('lily'));
        reed.position.copy(V(x + Math.cos(a) * rx * 1.07 + ox, y + Math.sin(a) * ry * 1.07, h / 2));
        reed.castShadow = true;
        scene.add(reed);
      }
    }
  }
  if (SITE.tennis) {
    const t = SITE.tennis;
    flat(rectPts(t), 0.05, 'tennisLot');
    for (const c of t.courts) {
      flat(rectPts(c), 0.09, 'clay');
      const ix = c.x + 2.5, iy = c.y + 2, iw = c.w - 5, ih = c.h - 4, cx = c.x + c.w / 2, cy = c.y + c.h / 2;
      const ln = (a, b) => strip(a, b, 0.18, 0.12, 'courtLine', 0.02);
      ln([ix, iy], [ix + iw, iy]); ln([ix, iy + ih], [ix + iw, iy + ih]); ln([ix, iy], [ix, iy + ih]); ln([ix + iw, iy], [ix + iw, iy + ih]);
      ln([ix, iy + 1.4], [ix + iw, iy + 1.4]); ln([ix, iy + ih - 1.4], [ix + iw, iy + ih - 1.4]);
      ln([cx - 6.4, iy + 1.4], [cx - 6.4, iy + ih - 1.4]); ln([cx + 6.4, iy + 1.4], [cx + 6.4, iy + ih - 1.4]); ln([cx - 6.4, cy], [cx + 6.4, cy]);
      const net = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.95, ih + 1.2), mat('net'));
      net.position.copy(V(cx, cy, 0.48));
      net.castShadow = true;
      scene.add(net);
    }
    if (t.label) textSprite(t.label, t.x + t.w / 2, t.y + t.h + 2, 0.3, 4);
  }
  for (const [a, b] of SITE.paths) strip(SITE.nodes[a], SITE.nodes[b], 3.4, 0.08, 'walk');
  for (const gate of SITE.gates) strip([gate.x, gate.y], gate.street, 3.4, 0.08, 'walk');
  for (const p of Object.values(SITE.nodes)) {
    const m = new THREE.Mesh(new THREE.CircleGeometry(1.7, 16), mat('walk'));
    m.rotation.x = -Math.PI / 2;
    m.position.copy(V(p[0], p[1], 0.085));
    m.receiveShadow = true;
    scene.add(m);
  }
  for (const c of SITE.crossings || []) {
    flat(rectPts(c), 0.09, 'road');
    if (c.vertical) for (let y = c.y + 0.5; y < c.y + c.h; y += 2) flat(rectPts({ x: c.x + 0.6, y, w: c.w - 1.2, h: 1 }), 0.11, 'zebra');
    else for (let x = c.x + 0.5; x < c.x + c.w; x += 2) flat(rectPts({ x, y: c.y + 0.6, w: 1, h: c.h - 1.2 }), 0.11, 'zebra');
  }
  if (SITE.plaza) {
    const { x, y, r } = SITE.plaza;
    flat(ellipsePts(x, y, r, r), 0.1, 'plaza');
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.42, r * 0.45, 0.5, 24), mat('plaza'));
    rim.position.copy(V(x, y, 0.25));
    const water = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.36, r * 0.36, 0.52, 24), mat('fountain', { roughness: 0.2 }));
    water.position.copy(V(x, y, 0.27));
    rim.castShadow = true;
    scene.add(rim, water);
  }

  // ---------- buildings and houses ----------
  const winTex = {};
  const officeWall = alt => mat(alt ? 'officeWallAlt' : 'officeWall', { color: 0xffffff, map: (winTex[alt ? 'alt' : 'main'] = windowTexture(alt ? pal.wallAlt : pal.wall, pal.window)) });
  for (const b of SITE.buildings) {
    const pts = outline(b), height = (b.floors || 1) * FLOOR_M;
    if (b.glassRoof) {
      // Garage: thin walls and a glass roof, so the parked bikes inside stay visible.
      const t = 0.6, inner = [[b.x + t, b.y + t], [b.x + b.w - t, b.y + t], [b.x + b.w - t, b.y + b.h - t], [b.x + t, b.y + b.h - t]];
      block(pts, height, mat(b.tone ? 'roofAlt' : 'wall'), mat('roof'), { holes: [inner] });
      flat(inner, 0.12, 'plaza');
      const glass = new THREE.Mesh(new THREE.BoxGeometry(b.w, 0.1, b.h), mat('glass', { transparent: true, opacity: 0.22, roughness: 0.05, depthWrite: false }));
      glass.position.copy(V(b.x + b.w / 2, b.y + b.h / 2, height));
      scene.add(glass);
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(glass.geometry), new THREE.LineBasicMaterial({ color: pal.metal }));
      edge.position.copy(glass.position);
      edge.userData.themed = 'metal';
      scene.add(edge);
    } else {
      block(pts, height, b.label === 'Clubhouse' ? mat('wallAlt') : officeWall(Boolean(b.tone)), mat(b.tone ? 'roofAlt' : 'roof'));
    }
    const [cx, cy] = b.labelAt || center(b);
    textSprite(b.label, cx, cy, height + 0.6, 3.2);
  }
  for (const h of SITE.around?.houses || []) {
    const grey = h.tone === 'grey';
    block(outline(h), (h.floors || 1) * FLOOR_M, mat(grey ? 'npcWall' : 'house'), mat(grey ? 'npcRoof' : 'houseRoof'));
  }
  if (SITE.park?.label) textSprite(SITE.park.label, ...SITE.park.labelAt, 0.3, 3.6);

  // ---------- trees: round crowns and pines, instanced ----------
  const allTrees = [...(SITE.trees || []).map(t => [...t, false]), ...(SITE.around?.trees || []).map(t => [...t, true])];
  const round = allTrees.filter(t => t[3] !== 'pine'), pines = allTrees.filter(t => t[3] === 'pine');
  const trunkGeo = new THREE.CylinderGeometry(0.22, 0.3, 1, 6).translate(0, 0.5, 0);
  const crownGeo = new THREE.IcosahedronGeometry(1, 1);
  const coneGeo = merge([new THREE.ConeGeometry(1, 1.5, 7).translate(0, 0.75, 0), new THREE.ConeGeometry(0.74, 1.2, 7).translate(0, 1.35, 0)]);
  const trunks = new THREE.InstancedMesh(trunkGeo, mat('trunk'), allTrees.length);
  const crowns = new THREE.InstancedMesh(crownGeo, mat('treeCrown', { flatShading: true, color: 0xffffff }), Math.max(1, round.length));
  const cones = new THREE.InstancedMesh(coneGeo, mat('pineCrown', { flatShading: true, color: 0xffffff }), Math.max(1, pines.length));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3();
  allTrees.forEach(([x, y, r, kind], i) => {
    const trunkH = kind === 'pine' ? r * 0.7 : r * 0.9;
    trunks.setMatrixAt(i, m4.compose(V(x, y), q, sc.set(r * 0.5, trunkH, r * 0.5)));
  });
  const paintTrees = () => {
    round.forEach(([x, y, r, , far], i) => {
      crowns.setMatrixAt(i, m4.compose(V(x, y, r * 0.9 + r * 0.85), q.setFromEuler(new THREE.Euler(0, i, 0)), sc.set(r * 1.05, r * 0.95, r * 1.05)));
      crowns.setColorAt(i, new THREE.Color(far ? pal.treeFar : pal.tree));
    });
    pines.forEach(([x, y, r, , far], i) => {
      cones.setMatrixAt(i, m4.compose(V(x, y, r * 0.55), q.identity(), sc.set(r * 0.95, r * 1.7, r * 0.95)));
      cones.setColorAt(i, new THREE.Color(far ? pal.treeFar : pal.pine));
    });
    for (const im of [crowns, cones]) {
      im.instanceMatrix.needsUpdate = true;
      if (im.instanceColor) im.instanceColor.needsUpdate = true;
    }
  };
  paintTrees();
  for (const im of [trunks, crowns, cones]) {
    im.castShadow = true;
    scene.add(im);
  }

  // ---------- racks: status pad, stands, bikes, shelters, pins ----------
  const bikeGeo = bikeGeometries();
  const hoopGeo = new THREE.TorusGeometry(0.36, 0.035, 5, 14, Math.PI);
  const racks = new Map();
  const hits = [];
  const statusColour = lvl => getComputedStyle(document.documentElement).getPropertyValue(`--${lvl}`).trim() || '#98a2ad';

  function slotsFor(spot) {
    const r = spot.rack, horizontal = r.w >= r.h, long = horizontal ? r.w : r.h, short = horizontal ? r.h : r.w;
    const cols = spot.capacity / (long / 1.2) > 1.3 && short >= 10 ? 2 : 1;
    const per = Math.ceil(spot.capacity / cols), out = [];
    for (let c = 0; c < cols; c++) for (let i = 0; i < per && out.length < spot.capacity; i++) {
      const along = (i + 0.5) * long / per, across = (c + 0.5) * short / cols;
      out.push(horizontal ? { x: r.x + along, y: r.y + across, rot: Math.PI / 2 } : { x: r.x + across, y: r.y + along, rot: 0 });
    }
    return out;
  }

  for (const spot of SPOTS) {
    const r = spot.rack, [cx, cy] = center(r), slots = slotsFor(spot);
    const pad = new THREE.Mesh(new THREE.BoxGeometry(r.w + 1.4, 0.06, r.h + 1.4), new THREE.MeshStandardMaterial({ transparent: true, opacity: 0.55, depthWrite: false }));
    pad.position.copy(V(cx, cy, 0.15));
    scene.add(pad);
    const hoops = new THREE.InstancedMesh(hoopGeo, mat('metal', { metalness: 0.4, roughness: 0.5 }), slots.length);
    slots.forEach((s, i) => hoops.setMatrixAt(i, m4.compose(V(s.x, s.y, 0.15), q.setFromEuler(new THREE.Euler(0, s.rot, 0)), sc.setScalar(BIKE_SCALE))));
    hoops.castShadow = true;
    scene.add(hoops);
    const frames = new THREE.InstancedMesh(bikeGeo.frame, mat('bikeFrame', { color: 0xffffff, roughness: 0.45, metalness: 0.15 }), slots.length);
    const wheels = new THREE.InstancedMesh(bikeGeo.dark, mat('tyre', { color: '#15191d', roughness: 0.8 }), slots.length);
    const metals = new THREE.InstancedMesh(bikeGeo.metal, mat('chrome', { color: '#b8c0c8', roughness: 0.3, metalness: 0.7 }), slots.length);
    frames.count = wheels.count = metals.count = 0;
    frames.castShadow = wheels.castShadow = metals.castShadow = true;
    scene.add(frames, wheels, metals);
    if (spot.roof?.curved) curvedShelter(r, spot.roof.back);
    else if (spot.roof) {
      const horizontal = r.w >= r.h, ox = horizontal ? 1 : 2.6, oy = horizontal ? 2.6 : 1, zr = 2.7;
      const fx = r.x - ox, fy = r.y - oy, fw = r.w + 2 * ox, fh = r.h + 2 * oy;
      const roof = new THREE.Mesh(new THREE.BoxGeometry(fw, 0.08, fh), mat('shelter', { transparent: true, opacity: 0.42, roughness: 0.3, depthWrite: false }));
      roof.position.copy(V(fx + fw / 2, fy + fh / 2, zr));
      roof.castShadow = true;
      scene.add(roof);
      const n = Math.max(2, Math.round((horizontal ? fw : fh) / 10) + 1);
      for (let i = 0; i < n; i++) for (const side of [0, 1]) {
        const t = i / (n - 1);
        const px = horizontal ? fx + t * fw : fx + side * fw, py = horizontal ? fy + side * fh : fy + t * fh;
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, zr, 6), mat('metal'));
        post.position.copy(V(px, py, zr / 2));
        post.castShadow = true;
        scene.add(post);
      }
    }
    // An invisible box over the rack makes the whole rack easy to tap.
    const hit = new THREE.Mesh(new THREE.BoxGeometry(r.w + 3, 4, r.h + 3), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    hit.position.copy(V(cx, cy, 2));
    hit.userData.id = spot.id;
    scene.add(hit);
    hits.push(hit);
    // Pin: a small coloured disc with the free count and the rack name, floating above the rack.
    const pc = document.createElement('canvas');
    pc.width = 256; pc.height = 230;
    const ptex = new THREE.CanvasTexture(pc);
    ptex.colorSpace = THREE.SRGBColorSpace;
    const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: ptex, transparent: true, depthTest: false }));
    pin.center.set(0.5, 0);
    pin.renderOrder = 10;
    pin.position.copy(V(cx, cy, spot.roof ? 4.2 : 2.6));
    pin.userData.id = spot.id;
    scene.add(pin);
    hits.push(pin);
    racks.set(spot.id, { spot, slots, pad, frames, wheels, metals, pin, pc, ptex, item: null, bikes: -1, selected: false });
  }

  // A typical bike shelter: posts along the back, and a roof that rises from them and curves forward over the bikes.
  function curvedShelter(r, back) {
    const horizontal = back === 'n' || back === 's';
    const length = (horizontal ? r.w : r.h) + 1, depth = (horizontal ? r.h : r.w) + 1.2;
    const f = { n: [0, 0, 1], s: [0, 0, -1], e: [-1, 0, 0], w: [1, 0, 0] }[back]; // forward: from the back towards the bikes
    const forward = new THREE.Vector3(...f), up = new THREE.Vector3(0, 1, 0), along = new THREE.Vector3().crossVectors(forward, up);
    const [cx, cy] = center(r);
    const backMid = V(cx, cy).addScaledVector(forward, -depth / 2);
    const lift = u => 2.35 + 0.55 * Math.sin((Math.PI * 0.85 * u) / depth); // rises, then dips at the front edge
    const top = [], bottom = [];
    for (let i = 0; i <= 18; i++) {
      const u = (i / 18) * depth;
      top.push(new THREE.Vector2(u, lift(u)));
      bottom.unshift(new THREE.Vector2(u, lift(u) - 0.07));
    }
    const geo = new THREE.ExtrudeGeometry(new THREE.Shape([...top, ...bottom]), { depth: length, bevelEnabled: false });
    const roof = new THREE.Mesh(geo, mat('shelter', { transparent: true, opacity: 0.5, roughness: 0.3, depthWrite: false, side: THREE.DoubleSide }));
    roof.matrixAutoUpdate = false;
    roof.matrix.makeBasis(forward, up, along).setPosition(backMid.clone().addScaledVector(along, -length / 2));
    roof.castShadow = true;
    scene.add(roof);
    const posts = Math.max(2, Math.round(length / 4) + 1);
    for (let i = 0; i < posts; i++) {
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, lift(0), 8), mat('metal'));
      post.position.copy(backMid).addScaledVector(along, -length / 2 + (i / (posts - 1)) * length).setY(lift(0) / 2);
      post.castShadow = true;
      scene.add(post);
    }
    const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, length, 6), mat('metal'));
    rail.quaternion.setFromUnitVectors(up, along);
    rail.position.copy(backMid).setY(0.9);
    scene.add(rail);
  }

  function drawPin(node) {
    const { pc, ptex, item, spot, selected } = node, g = pc.getContext('2d');
    g.clearRect(0, 0, 256, 230);
    const lvl = item?.level || 'off', colour = statusColour(lvl);
    const text = !item || item.level === 'off' ? '–' : item.level === 'full' ? 'Full' : String(item.free ?? '–');
    g.beginPath();
    g.moveTo(128, 150); g.lineTo(112, 118); g.lineTo(144, 118); g.closePath();
    g.fillStyle = colour; g.fill();
    g.beginPath(); g.arc(128, 78, 52, 0, Math.PI * 2);
    g.fillStyle = colour; g.fill();
    g.lineWidth = selected ? 10 : 7;
    g.strokeStyle = selected ? getComputedStyle(document.documentElement).getPropertyValue('--me').trim() : '#ffffff';
    g.stroke();
    g.fillStyle = lvl === 'filling' ? '#2b2200' : '#ffffff';
    g.font = `800 ${text.length > 2 ? 40 : 54}px Figtree, system-ui, sans-serif`;
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, 128, 80);
    g.font = '800 38px Figtree, system-ui, sans-serif';
    g.lineWidth = 8;
    g.strokeStyle = pal === PALETTE.dark ? 'rgba(10,15,21,.85)' : 'rgba(255,255,255,.92)';
    g.fillStyle = pal.label;
    g.strokeText(spot.name, 128, 200);
    g.fillText(spot.name, 128, 200);
    ptex.needsUpdate = true;
    node.pad.material.color.set(colour);
  }

  // Bikes in the stands: the share of stands the camera or photo found taken, at stable pseudo-random places.
  function placeBikes(node) {
    const { spot, slots, frames, wheels, metals, item } = node;
    const n = Math.round(slots.length * (item?.occupancy ?? 0));
    if (n === node.bikes) return;
    node.bikes = n;
    const rand = rng(spot.id.charCodeAt(0) * 977 + spot.capacity), order = slots.map((_, i) => i);
    for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
    order.slice(0, n).forEach((slot, k) => {
      const s = slots[slot], wobble = (rand() - 0.5) * 0.18;
      m4.compose(V(s.x, s.y, 0.15), q.setFromEuler(new THREE.Euler(0, s.rot + wobble, 0)), sc.set(1, 1, 1));
      for (const im of [frames, wheels, metals]) im.setMatrixAt(k, m4);
      frames.setColorAt(k, new THREE.Color(BIKE_COLOURS[(slot * 7 + spot.capacity) % BIKE_COLOURS.length]));
    });
    frames.count = wheels.count = metals.count = n;
    for (const im of [frames, wheels, metals]) im.instanceMatrix.needsUpdate = true;
    if (frames.instanceColor) frames.instanceColor.needsUpdate = true;
  }

  // ---------- route and you ----------
  const routeGroup = new THREE.Group(), userGroup = new THREE.Group();
  scene.add(routeGroup, userGroup);
  const meMat = new THREE.MeshBasicMaterial();
  const whiteMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const meSoft = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.18, depthWrite: false });

  // ---------- theme ----------
  function applyTheme() {
    pal = PALETTE[themeKey()];
    scene.background = new THREE.Color(pal.sky);
    scene.fog = new THREE.Fog(pal.sky, 420, 1100);
    hemi.intensity = pal.hemi;
    sun.intensity = pal.sun;
    ambient.intensity = pal.ambient;
    for (const [key, m] of Object.entries(mats)) if (pal[key]) m.color.set(pal[key]);
    mats.officeWall?.map && (mats.officeWall.map = winTex.main = windowTexture(pal.wall, pal.window), mats.officeWall.needsUpdate = true);
    mats.officeWallAlt?.map && (mats.officeWallAlt.map = winTex.alt = windowTexture(pal.wallAlt, pal.window), mats.officeWallAlt.needsUpdate = true);
    mats.treeCrown.color.set(0xffffff);
    mats.pineCrown.color.set(0xffffff);
    mats.bikeFrame.color.set(0xffffff);
    mats.tyre.color.set(pal === PALETTE.dark ? '#0b0e11' : '#15191d');
    mats.officeWall && mats.officeWall.color.set(0xffffff);
    mats.officeWallAlt && mats.officeWallAlt.color.set(0xffffff);
    const me = getComputedStyle(document.documentElement).getPropertyValue('--me').trim();
    meMat.color.set(me);
    meSoft.color.set(me);
    scene.traverse(o => { if (o.userData.themed) o.material.color.set(pal[o.userData.themed]); });
    paintTrees();
    labels.forEach(l => l.userData.draw());
    racks.forEach(drawPin);
    request();
  }

  // ---------- camera ----------
  let content = { ...v };
  const cam = { tx: 0, tz: 0, dist: 300, yaw: 0, pitch: 0.95 };
  let moved = false, anim = null, back = null;
  const size = () => [container.clientWidth || 1, container.clientHeight || 1];

  function homeCam() {
    const [W, H] = size(), i = insets();
    const aw = Math.max(80, W - i.left - i.right), ah = Math.max(80, H - i.top - i.bottom);
    const pitch = 0.95, yaw = -0.18, t = Math.tan((FOV * Math.PI) / 360);
    // Ground depth looks shorter when tilted; widths are seen at full length.
    const needH = (content.h * Math.sin(pitch) * 0.62 + 12) / t, needW = (content.w * 0.56) / (t * (aw / ah));
    const dist = clamp(Math.max(needH, needW) * (H / ah), MIN_DIST, MAX_DIST);
    // Shift the target so the content sits in the middle of the free area between the panels.
    const shift = ((i.top - i.bottom) / 2 / H) * 2 * dist * t;
    return { tx: content.x + content.w / 2, tz: content.y + content.h / 2 - shift * 0.8, dist, yaw, pitch };
  }

  function placeCamera() {
    const { tx, tz, dist, yaw, pitch } = cam;
    camera.position.set(tx + dist * Math.cos(pitch) * Math.sin(yaw), dist * Math.sin(pitch), tz + dist * Math.cos(pitch) * Math.cos(yaw));
    camera.lookAt(tx, 0, tz);
    onRotate((cam.yaw * 180) / Math.PI);
  }

  function setCam(next) {
    Object.assign(cam, next);
    cam.dist = clamp(cam.dist, MIN_DIST, MAX_DIST);
    cam.pitch = clamp(cam.pitch, MIN_PITCH, MAX_PITCH);
    cam.tx = clamp(cam.tx, v.x - 160, v.x + v.w + 160);
    cam.tz = clamp(cam.tz, v.y - 160, v.y + v.h + 160);
    request();
  }

  function animateTo(to, ms, done) {
    const from = { ...cam };
    let dy = to.yaw - from.yaw;
    dy = Math.atan2(Math.sin(dy), Math.cos(dy)); // turn the short way round
    anim = { from, to: { ...to, yaw: from.yaw + dy }, start: performance.now(), ms, done };
    request();
  }

  // ---------- render on demand ----------
  let raf = 0;
  function request() { if (!raf) raf = requestAnimationFrame(frame); }
  function frame(now) {
    raf = 0;
    if (anim) {
      const t = clamp((now - anim.start) / anim.ms, 0, 1), k = ease(t);
      const next = {};
      for (const key of ['tx', 'tz', 'dist', 'yaw', 'pitch']) next[key] = anim.from[key] + (anim.to[key] - anim.from[key]) * k;
      Object.assign(cam, next);
      if (t >= 1) { const done = anim.done; anim = null; done?.(); }
    }
    placeCamera();
    // Pins and labels keep the same size on screen whatever the zoom (pins about 74 px wide, labels 9 px text).
    const perPx = (2 * Math.tan((FOV * Math.PI) / 360)) / size()[1];
    for (const node of racks.values()) {
      const s = Math.max(1.2, camera.position.distanceTo(node.pin.position) * perPx * 74);
      node.pin.scale.set(s, s * (230 / 256), 1);
    }
    for (const l of labels) {
      const h = camera.position.distanceTo(l.position) * perPx * 21;
      l.scale.set(h * (512 / 96), h, 1);
    }
    renderer.render(scene, camera);
    if (anim) request();
  }

  function resize() {
    const [W, H] = size();
    renderer.setSize(W, H, false);
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    if (!moved && !anim) Object.assign(cam, homeCam());
    request();
  }
  new ResizeObserver(resize).observe(container);

  // ---------- gestures: drag pans, right-drag / two fingers rotate and tilt, wheel / pinch zoom ----------
  const pointers = new Map();
  let drag = null, pinch = null;
  const local = e => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const metresPerPx = () => (2 * cam.dist * Math.tan((FOV * Math.PI) / 360)) / size()[1];
  function panBy(dx, dy) {
    const m = metresPerPx(), s = Math.sin(cam.yaw), c = Math.cos(cam.yaw), fy = 1 / Math.max(0.45, Math.sin(cam.pitch));
    moved = true;
    setCam({ tx: cam.tx - (dx * c + dy * s * fy) * m, tz: cam.tz - (-dx * s + dy * c * fy) * m });
  }
  function zoomBy(f) { moved = true; setCam({ dist: cam.dist / f }); }
  const twoState = () => {
    const [a, b] = [...pointers.values()];
    return { mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], dist: Math.hypot(a[0] - b[0], a[1] - b[1]), angle: Math.atan2(b[1] - a[1], b[0] - a[0]) };
  };
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('pointerdown', e => {
    anim = null;
    pointers.set(e.pointerId, local(e));
    if (pointers.size === 1) drag = { id: e.pointerId, start: local(e), last: local(e), active: false, rotate: e.button === 2 || e.shiftKey || e.ctrlKey };
    else if (pointers.size === 2) { drag = null; pinch = twoState(); }
  });
  canvas.addEventListener('pointermove', e => {
    if (!pointers.has(e.pointerId)) return;
    const p = local(e);
    pointers.set(e.pointerId, p);
    if (pinch && pointers.size === 2) {
      const now = twoState();
      if (pinch.dist) zoomBy(now.dist / pinch.dist);
      // The map turns with the fingers: turning them clockwise turns the map clockwise.
      setCam({ yaw: cam.yaw + (now.angle - pinch.angle), pitch: cam.pitch + (now.mid[1] - pinch.mid[1]) * 0.004 });
      panBy(now.mid[0] - pinch.mid[0], 0);
      pinch = now;
    } else if (drag && e.pointerId === drag.id) {
      if (!drag.active && Math.hypot(p[0] - drag.start[0], p[1] - drag.start[1]) > DRAG_PX) {
        drag.active = true;
        try { canvas.setPointerCapture(e.pointerId); } catch { /* already released */ }
      }
      if (drag.active) {
        const dx = p[0] - drag.last[0], dy = p[1] - drag.last[1];
        if (drag.rotate) { moved = true; setCam({ yaw: cam.yaw - dx * 0.006, pitch: cam.pitch + dy * 0.005 }); }
        else panBy(dx, dy);
      }
      drag.last = p;
    }
  });
  const raycaster = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick([x, y]) {
    const [W, H] = size();
    ndc.set((x / W) * 2 - 1, -(y / H) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const pins = raycaster.intersectObjects(hits.filter(h => h.isSprite), false);
    if (pins.length) return pins[0].object.userData.id;
    const boxes = raycaster.intersectObjects(hits.filter(h => !h.isSprite), false);
    return boxes[0]?.object.userData.id;
  }
  const release = e => {
    if (!pointers.has(e.pointerId)) return;
    const wasTap = drag && !drag.active && e.pointerId === drag.id && e.type === 'pointerup' && pointers.size === 1;
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) drag = null;
    if (wasTap) {
      const id = pick(local(e));
      if (id) onSelect(id);
    }
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    zoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)));
  }, { passive: false });
  canvas.addEventListener('dblclick', e => { if (!pick(local(e))) zoomBy(1.8); });

  applyTheme();
  resize();

  return {
    // items: [{ id, level, free, bikes, text, label, live, flash }]
    update(items, highlightId) {
      for (const item of items) {
        const node = racks.get(item.id);
        if (!node) continue;
        node.item = item;
        node.selected = item.id === highlightId;
        drawPin(node);
        placeBikes(node);
      }
      request();
    },
    setRoute(points) {
      routeGroup.clear();
      if (points) {
        for (let i = 1; i < points.length; i++) {
          const a = points[i - 1], b = points[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]), ang = -Math.atan2(b[1] - a[1], b[0] - a[0]);
          for (const [w, h, m] of [[2.6, 0.2, whiteMat], [1.6, 0.22, meMat]]) {
            const s = new THREE.Mesh(new THREE.BoxGeometry(len + w, 0.04, w), m);
            s.position.copy(V((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, h));
            s.rotation.y = ang;
            routeGroup.add(s);
          }
        }
        const end = points[points.length - 1], dot = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.4, 0.4, 20), meMat);
        dot.position.copy(V(end[0], end[1], 0.3));
        routeGroup.add(dot);
      }
      request();
    },
    setUser(pos, accuracy) {
      userGroup.clear();
      if (pos) {
        const [x, y] = pos;
        if (accuracy > 2.5) {
          const ring = new THREE.Mesh(new THREE.CircleGeometry(Math.min(accuracy, MAX_RING_M), 32), meSoft);
          ring.rotation.x = -Math.PI / 2;
          ring.position.copy(V(x, y, 0.25));
          userGroup.add(ring);
        }
        const rim = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 1.6, 0.5, 24), whiteMat);
        const dot = new THREE.Mesh(new THREE.CylinderGeometry(1.15, 1.15, 0.6, 24), meMat);
        rim.position.copy(V(x, y, 0.35));
        dot.position.copy(V(x, y, 0.4));
        userGroup.add(rim, dot);
      }
      request();
    },
    fit(extra = []) {
      let x = v.x, y = v.y, x2 = v.x + v.w, y2 = v.y + v.h;
      for (const [px, py] of extra) { x = Math.min(x, px - 10); y = Math.min(y, py - 10); x2 = Math.max(x2, px + 10); y2 = Math.max(y2, py + 10); }
      content = { x, y, w: x2 - x, h: y2 - y };
      if (!moved && !anim) { Object.assign(cam, homeCam()); request(); }
    },
    reset() { moved = false; back = null; animateTo(homeCam(), 600); },
    zoom(f) { zoomBy(f); },
    relayout() { if (!moved && !anim) { Object.assign(cam, homeCam()); request(); } },
    // A camera looking straight down at the same area as the flat 2D map shows, so 2D can turn into 3D seamlessly.
    topDown(view) {
      return { tx: view.x + view.w / 2, tz: view.y + view.h / 2, dist: view.h / 2 / Math.tan((FOV * Math.PI) / 360), yaw: 0, pitch: Math.PI / 2 - 0.01 };
    },
    // Flies down to a rack over `ms`, then calls done (which opens the rack's full-screen page).
    // `from` starts the flight from a given camera, e.g. topDown() of the 2D map.
    focus(id, done, { from = null, ms = 2000 } = {}) {
      const node = racks.get(id);
      if (!node || matchMedia('(prefers-reduced-motion: reduce)').matches) return done();
      const r = node.spot.rack, [cx, cy] = center(r);
      if (from) {
        anim = null;
        Object.assign(cam, from);
      }
      back = { cam: { ...cam }, moved: from ? true : moved };
      moved = true;
      const [W, H] = size(), pitch = 0.72;
      // On a portrait phone the rack must also fit the narrow width.
      const dist = clamp((Math.max(r.w, r.h) * 1.15 + 10) * Math.max(1, 1.1 / (W / H)), 18, 130);
      // Look from the side facing away from the buildings, so none of them blocks the view of the bikes.
      const near = SITE.buildings.filter(b => !b.glassRoof).map(b => center(b));
      const score = yaw => {
        const gx = cx + dist * 0.5 * Math.cos(pitch) * Math.sin(yaw), gy = cy + dist * 0.5 * Math.cos(pitch) * Math.cos(yaw);
        return Math.min(...near.map(([bx, by]) => Math.hypot(bx - gx, by - gy)));
      };
      const yaw = [-0.3, Math.PI / 2 - 0.3, Math.PI - 0.3, -Math.PI / 2 - 0.3].reduce((a, b) => (score(b) > score(a) + 4 ? b : a));
      animateTo({ tx: cx, tz: cy, dist, pitch, yaw }, ms, done);
      request();
    },
    // Back to where the camera was before focus(), then calls done.
    unfocus(done) {
      if (!back) return done?.();
      const { cam: to, moved: wasMoved } = back;
      back = null;
      moved = wasMoved;
      animateTo(wasMoved ? to : homeCam(), 1000, done);
    },
    setTheme: applyTheme,
    render: request,
    // Where a rack's pin is on screen, in px from the top-left of the map (for tests and debugging).
    pinOnScreen(id) {
      const node = racks.get(id), [W, H] = size();
      placeCamera();
      const p = node.pin.position.clone().project(camera);
      return [((p.x + 1) / 2) * W, ((1 - p.y) / 2) * H - node.pin.scale.y * 0.66 / ((2 * camera.position.distanceTo(node.pin.position) * Math.tan((FOV * Math.PI) / 360)) / H)];
    },
  };
}
