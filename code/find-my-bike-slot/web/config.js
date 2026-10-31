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
  // The area the map shows when it opens; the plan around it can be explored by zooming and dragging.
  view: { x: 0, y: 0, w: 136, h: 200 },
  // Where one plan point sits in the real world. Placeholder: pick the main building's centre
  // in Google Maps (right-click → copy coordinates) and set lat/lng and bearing.
  anchor: { x: 67, y: 42, lat: 47.5596, lng: 7.5886 },
  bearing: 0, // compass direction the top of the plan faces (0 = north, 90 = east)
  fence: { x: 13, y: 5, w: 118, h: 113 },
  // Areas you can walk around in; inside them directions join the nearest walkway.
  grounds: [{ x: 13, y: 5, w: 118, h: 113 }, { x: 13, y: 134, w: 118, h: 66 }],
  // Buildings are rectangles (x, y, w, h) or outlines (points).
  buildings: [
    { label: 'Main building', x: 30, y: 31, w: 74, h: 23 },
    { label: 'Lab', points: [[84, 70], [110, 68], [117, 83], [111, 100], [88, 102], [80, 86]], tone: 'alt' },
    { label: 'Bike garage', x: 99, y: 150, w: 26, h: 35, labelAt: [112, 155.6] },
  ],
  // The first gate is the main one: Google Maps directions lead there. `node` is its walkway point,
  // `street` where its path meets the road.
  gates: [
    { label: 'Main gate', x: 72, y: 118, node: 'gate', street: [72, 121] },
    { label: 'Side gate', x: 13, y: 96, node: 'wgate', street: [4.5, 96] },
  ],
  streets: [
    { x: -400, y: 121, w: 960, h: 9, label: 'Main road', labelAt: [14, 126.6] },
    { x: -400, y: 203, w: 960, h: 9, label: 'Park lane', labelAt: [14, 208.6] },
    { x: 0, y: -400, w: 9, h: 960, label: 'Side road', labelAt: [5.6, 60], vertical: true },
    { x: 140, y: -400, w: 9, h: 960, label: 'East road', labelAt: [145.6, 60], vertical: true },
  ],
  crossings: [{ x: 66, y: 121, w: 12, h: 9 }],
  plaza: { x: 54, y: 85, r: 8 },
  park: { x: 13, y: 137, w: 80, h: 61, label: 'City park', labelAt: [76, 195], pond: { x: 56, y: 170, rx: 11, ry: 7 } },
  trees: [[30, 71, 2.8], [34, 81, 2.4], [70, 80, 2.6], [70, 93, 2.6], [72, 102, 2.2], [128, 72, 2.2], [128, 92, 2.2],
    [44, 146, 2.6], [84, 150, 2.4], [88, 163, 2.2], [83, 172, 2.2], [87, 189, 2.6], [66, 195, 2.2], [30, 194, 2.2],
    [16, 186, 2.2], [24, 174, 2], [134, 150, 2.2], [134, 166, 2.2], [134, 182, 2.2], [110, 190, 2.4], [121, 193, 2]],
  // Surroundings, drawn outside the plan only: neighbouring blocks and trees.
  around: {
    blocks: [[-52, 8, 40, 44], [-48, 62, 36, 30], [-54, 104, 42, 36], [-50, 150, 38, 40], [-30, 218, 44, 30],
      [22, 218, 50, 28], [84, 218, 40, 30], [134, 218, 46, 28], [154, 8, 40, 46], [156, 66, 34, 30],
      [154, 106, 46, 34], [158, 150, 36, 40], [14, -44, 46, 36], [70, -40, 52, 32], [132, -42, 40, 34]],
    trees: [[-20, 56, 3], [-14, 98, 2.6], [-26, 144, 2.8], [164, 60, 3], [172, 100, 2.6], [206, 40, 3],
      [6, -18, 2.8], [126, -14, 2.6], [64, 254, 3], [-60, 0, 3], [-8, 196, 2.6], [152, 198, 2.4]],
  },
  // Walkways used for directions: named points and the straight paths between them.
  nodes: {
    nw: [21, 13], n: [67, 13], ne: [123, 13], en: [123, 42],
    wm: [21, 62], c: [72, 62], em: [123, 62], wg: [21, 96],
    sw: [21, 110], gs: [43, 110], s: [72, 110], se: [123, 110], p: [54, 85],
    gate: [72, 118], wgate: [13, 96], xs: [72, 134], ssn: [112, 134], gn: [128, 134], ge: [128, 158],
    pe: [70, 142], pa: [54, 150], pb: [40, 164], pc: [32, 182], pf: [54, 192], pd: [76, 180],
  },
  paths: [
    ['nw', 'n'], ['n', 'ne'], ['nw', 'wm'], ['ne', 'en'], ['en', 'em'], ['wm', 'c'], ['c', 'em'],
    ['wm', 'wg'], ['wg', 'sw'], ['em', 'se'], ['sw', 'gs'], ['gs', 's'], ['s', 'se'],
    ['s', 'gate'], ['wg', 'wgate'], ['wg', 'p'], ['p', 'c'], ['p', 's'],
    ['gate', 'xs'], ['xs', 'ssn'], ['ssn', 'gn'], ['gn', 'ge'],
    ['xs', 'pe'], ['pe', 'pa'], ['pa', 'pb'], ['pb', 'pc'], ['pc', 'pf'], ['pf', 'pd'], ['pd', 'pe'],
  ],
};

// Parking areas. `id` matches a row in the Supabase `spots` table, `access` is the walkway
// point directions lead to, and `camera: true` marks the rack with a live camera.
export const SPOTS = [
  { id: 'north', name: 'North rack', rack: { x: 42, y: 18, w: 50, h: 9 }, access: 'n', capacity: 20, camera: true },
  { id: 'east', name: 'East rack', rack: { x: 108, y: 28, w: 11, h: 28 }, access: 'en', capacity: 16 },
  { id: 'gate', name: 'Gate rack', rack: { x: 28, y: 97.5, w: 30, h: 8 }, access: 'gs', capacity: 10 },
  { id: 'west', name: 'West rack', rack: { x: 18, y: 143, w: 12, h: 24 }, access: 'pb', capacity: 16 },
  { id: 'south', name: 'South rack', rack: { x: 99, y: 138, w: 26, h: 9 }, access: 'ssn', capacity: 20 },
  { id: 'garage', name: 'Garage rack', rack: { x: 105, y: 161, w: 14, h: 21 }, access: 'ge', capacity: 30 },
];
