// Find my Bike Slot · configuration

// Supabase project (Project Settings → API). The anon key is meant to be public:
// the Row Level Security rules in supabase/schema.sql only let visitors read.
// Leave both empty to run the site with sample data.
export const SUPABASE_URL = 'https://zfznmkgfbttkimjenoez.supabase.co';
export const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inpmem5ta2dmYnR0a2ltamVub2V6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMzOTUzOTEsImV4cCI6MjEwODk3MTM5MX0.6QLP60DF3ESC3l9Ipk-ifJwe41d_m2rPS-MhDXPipt0';

// Servers that help the live video find a direct path to the station. If some networks never get
// HD video, add a TURN server here and in the station's BIKESLOT_STATION.iceServers.
export const ICE_SERVERS = [{ urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] }];

// Site plan, in metres. x grows to the right, y grows downwards, (0,0) is the top-left corner.
export const SITE = {
  name: 'Company site',
  // The area the map shows when it opens (all racks fit in it); the rest can be explored by zooming and dragging.
  view: { x: 0, y: 0, w: 175, h: 216 },
  // Where one plan point sits in the real world. Placeholder: pick the main building's centre
  // in Google Maps (right-click → copy coordinates) and set lat/lng and bearing.
  anchor: { x: 67, y: 34, lat: 47.5596, lng: 7.5886 },
  bearing: 0, // compass direction the top of the plan faces (0 = north, 90 = east)
  fence: { x: 13, y: 5, w: 118, h: 113 },
  // Areas you can walk around in; inside them directions join the nearest walkway.
  grounds: [{ x: 13, y: 5, w: 118, h: 113 }, { x: 2, y: 134, w: 76, h: 80 }, { x: 91, y: 134, w: 82, h: 80 }, { x: 150, y: 74, w: 26, h: 20 }],
  // Buildings are rectangles (x, y, w, h) or outlines (points); `floors` sets their height in 3D.
  buildings: [
    { label: 'Main building', x: 30, y: 22, w: 74, h: 24, floors: 3 },
    { label: 'Lab', points: [[84, 70], [110, 68], [117, 83], [111, 100], [88, 102], [80, 86]], tone: 'alt', floors: 2 },
    // The garage has a glass roof in 3D, so the bikes inside can be seen.
    { label: 'Bike garage', x: 100, y: 188, w: 35, h: 24, labelAt: [117.5, 193], floors: 1, glassRoof: true },
    { label: 'Clubhouse', x: 136, y: 140, w: 22, h: 14, floors: 1, tone: 'alt' },
  ],
  // The first gate is the main one: Google Maps directions lead there. `node` is its walkway point,
  // `street` where its path meets the road.
  gates: [
    { label: 'Main gate', x: 72, y: 118, node: 'gate', street: [72, 121] },
    { label: 'Side gate', x: 13, y: 96, node: 'wgate', street: [4.5, 96] },
    { label: 'East gate', x: 131, y: 80, node: 'egate', street: [140, 80] },
  ],
  // Three blocks on top, the park and the tennis club in the middle (split by Park road, which meets the main
  // road at a T-junction), and three neighbourhood blocks south of Park lane. Side road and East road stop at
  // the main road and start again south of Park lane.
  streets: [
    { x: -400, y: 121, w: 960, h: 9, label: 'Main road', labelAt: [14, 126.6] },
    { x: -400, y: 216, w: 960, h: 9, label: 'Park lane', labelAt: [14, 221.6] },
    { x: 0, y: -400, w: 9, h: 521, label: 'Side road', labelAt: [5.6, 60], vertical: true },
    { x: 0, y: 225, w: 9, h: 400, label: 'Side road', labelAt: [5.6, 252], vertical: true },
    { x: 140, y: -400, w: 9, h: 521, label: 'East road', labelAt: [145.6, 60], vertical: true },
    { x: 140, y: 225, w: 9, h: 400, label: 'East road', labelAt: [145.6, 252], vertical: true },
    { x: 80, y: 130, w: 9, h: 86, label: 'Park road', labelAt: [85.6, 196], vertical: true },
  ],
  crossings: [{ x: 66, y: 121, w: 12, h: 9 }, { x: 140, y: 75, w: 9, h: 10, vertical: true }, { x: 80, y: 146, w: 9, h: 10, vertical: true }],
  plaza: { x: 54, y: 85, r: 8 },
  park: { x: 6, y: 137, w: 70, h: 76, label: 'City park', labelAt: [62, 210.5], pond: { x: 40, y: 178, rx: 13, ry: 8 } },
  tennis: { x: 93, y: 137, w: 78, h: 46, label: 'Tennis club', courts: [{ x: 96, y: 140, w: 36, h: 18 }, { x: 96, y: 162, w: 36, h: 18 }] },
  // Trees: [x, y, radius, kind]; kind 'pine' draws a conifer, anything else a round tree.
  trees: [[30, 71, 2.8], [34, 81, 2.4, 'pine'], [70, 80, 2.6], [70, 93, 2.6, 'pine'], [72, 102, 2.2], [128, 72, 2.2, 'pine'],
    [128, 92, 2.2], [40, 18, 2], [94, 18, 2.2, 'pine'], [112, 30, 2.4], [114, 42, 2.2, 'pine'], [176, 86, 2.2],
    [30, 145, 2.4], [60, 160, 2.6], [61, 181, 2.2, 'pine'], [12, 175, 2.4, 'pine'], [12, 200, 2.2], [30, 208, 2],
    [72, 206, 2.4, 'pine'], [50, 140, 2], [165, 160, 2.2, 'pine'], [166, 177, 2.2], [145, 200, 2.4], [160, 206, 2.2, 'pine']],
  // Surroundings outside the plan: houses (1 or 2 floors, rectangles or outlines; tone 'grey' for the blocks
  // south of Park lane) and trees, kept off the streets.
  around: {
    houses: [
      { x: -46, y: 8, w: 30, h: 22, floors: 2 },
      { points: [[-50, 40], [-20, 40], [-20, 58], [-34, 58], [-34, 76], [-50, 76]], floors: 1 },
      { x: -44, y: 88, w: 26, h: 26, floors: 2 },
      { points: [[-50, 136], [-16, 136], [-16, 170], [-26, 170], [-26, 150], [-40, 150], [-40, 170], [-50, 170]], floors: 1 },
      { x: -44, y: 178, w: 28, h: 20, floors: 1 },
      { x: 156, y: 6, w: 34, h: 26, floors: 2 },
      { points: [[154, 42], [190, 42], [190, 58], [172, 58], [172, 72], [154, 72]], floors: 1 },
      { x: 158, y: 96, w: 30, h: 22, floors: 1 },
      { x: 178, y: 138, w: 28, h: 22, floors: 2 },
      { points: [[178, 170], [206, 170], [206, 186], [192, 186], [192, 210], [178, 210]], floors: 1 },
      { x: 16, y: -34, w: 40, h: 26, floors: 2 },
      { points: [[66, -38], [104, -38], [104, -22], [86, -22], [86, -8], [66, -8]], floors: 1 },
      { x: 112, y: -32, w: 24, h: 22, floors: 1 },
      { x: -46, y: 232, w: 32, h: 24, floors: 2, tone: 'grey' },
      { x: 18, y: 232, w: 38, h: 22, floors: 2, tone: 'grey' },
      { points: [[64, 232], [100, 232], [100, 250], [84, 250], [84, 268], [64, 268]], floors: 1, tone: 'grey' },
      { x: 108, y: 234, w: 26, h: 30, floors: 2, tone: 'grey' },
      { x: 20, y: 260, w: 30, h: 14, floors: 1, tone: 'grey' },
      { x: 156, y: 232, w: 34, h: 26, floors: 2, tone: 'grey' },
    ],
    trees: [[-26, 68, 3], [-12, 98, 2.6, 'pine'], [-8, 112, 2.4], [194, 66, 3, 'pine'], [196, 104, 2.6], [206, 40, 3],
      [-10, -18, 2.8, 'pine'], [126, -4, 2.4], [-60, 0, 3, 'pine'], [-8, 196, 2.6], [152, 198, 2.4, 'pine'], [214, 150, 2.6],
      [-30, 266, 2.6, 'pine'], [196, 268, 2.4], [56, 262, 2.2], [104, 270, 2.2, 'pine'], [-6, 150, 2.4], [-8, 186, 2.2, 'pine']],
  },
  // Walkways used for directions: named points and the straight paths between them.
  nodes: {
    nw: [21, 13], n: [67, 13], ne: [123, 13], en: [123, 42],
    wm: [21, 62], c: [72, 62], em: [123, 62], wg: [21, 96],
    sw: [21, 110], gs: [43, 110], s: [72, 110], se: [123, 110], p: [54, 85],
    ee: [123, 80], egate: [131, 80], ex: [152, 80], erk: [162, 80],
    gate: [72, 118], wgate: [13, 96], xs: [72, 134],
    pe: [70, 142], pa: [48, 150], pb: [22, 166], pc: [18, 190], pf: [42, 206], pd: [66, 194],
    pm: [78, 151], tw: [92, 151], t1: [92, 184], ge: [118, 184], t2: [134, 184], tsr: [134, 168],
  },
  paths: [
    ['nw', 'n'], ['n', 'ne'], ['nw', 'wm'], ['ne', 'en'], ['en', 'em'], ['wm', 'c'], ['c', 'em'],
    ['wm', 'wg'], ['wg', 'sw'], ['em', 'ee'], ['ee', 'se'], ['ee', 'egate'], ['egate', 'ex'], ['ex', 'erk'], ['sw', 'gs'], ['gs', 's'], ['s', 'se'],
    ['s', 'gate'], ['wg', 'wgate'], ['wg', 'p'], ['p', 'c'], ['p', 's'],
    ['gate', 'xs'], ['xs', 'pe'], ['pe', 'pa'], ['pa', 'pb'], ['pb', 'pc'], ['pc', 'pf'], ['pf', 'pd'], ['pd', 'pe'],
    ['pe', 'pm'], ['pm', 'tw'], ['tw', 't1'], ['t1', 'ge'], ['ge', 't2'], ['t2', 'tsr'],
  ],
};

// Parking areas. `id` matches a row in the Supabase `spots` table, `access` is the walkway
// point directions lead to, and `camera: true` marks the rack with a live camera.
// `roof` draws a shelter in 3D: curved (a cantilever roof rising from posts on the `back` side) or flat.
export const SPOTS = [
  { id: 'north', name: 'North rack', rack: { x: 53.5, y: 50, w: 27, h: 6 }, access: 'c', capacity: 20, camera: true, roof: { curved: true, back: 'n' } },
  { id: 'east', name: 'East rack', rack: { x: 152, y: 83, w: 19.5, h: 7 }, access: 'erk', capacity: 12, roof: { curved: true, back: 's' } },
  { id: 'gate', name: 'Gate rack', rack: { x: 32, y: 97.5, w: 22, h: 7 }, access: 'gs', capacity: 10 },
  { id: 'west', name: 'West rack', rack: { x: 10, y: 142, w: 10.5, h: 19 }, access: 'pb', capacity: 16 },
  { id: 'south', name: 'South rack', rack: { x: 136, y: 164, w: 24, h: 9 }, access: 'tsr', capacity: 20, roof: { curved: false } },
  { id: 'garage', name: 'Garage rack', rack: { x: 106, y: 197, w: 23, h: 12 }, access: 'ge', capacity: 30 },
];
