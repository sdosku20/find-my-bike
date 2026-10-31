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
  view: { x: 0, y: 0, w: 136, h: 174 },
  // Where one plan point sits in the real world. Placeholder: pick the main building's centre
  // in Google Maps (right-click → copy coordinates) and set lat/lng and bearing.
  anchor: { x: 67, y: 46, lat: 47.5596, lng: 7.5886 },
  bearing: 0, // compass direction the top of the plan faces (0 = north, 90 = east)
  fence: { x: 13, y: 5, w: 118, h: 153 },
  // Buildings are rectangles (x, y, w, h) or outlines (points).
  buildings: [
    { label: 'Main building', x: 30, y: 33, w: 74, h: 27 },
    { label: 'Lab', points: [[82, 84], [114, 82], [121, 101], [115, 128], [88, 130], [79, 108]], tone: 'alt' },
  ],
  // The first gate is the main one: Google Maps directions lead there. `node` is its walkway point,
  // `street` where its path meets the road.
  gates: [
    { label: 'Main gate', x: 72, y: 158, node: 'gate', street: [72, 167.5] },
    { label: 'Side gate', x: 13, y: 128, node: 'wgate', street: [4.5, 128] },
  ],
  streets: [
    { x: -400, y: 163, w: 960, h: 9, label: 'Main road', labelAt: [14, 168.6] },
    { x: 0, y: -400, w: 9, h: 960, label: 'Side road', labelAt: [5.6, 64], vertical: true },
  ],
  plaza: { x: 50, y: 104, r: 10 },
  trees: [[63, 92, 2.6], [68, 111, 3], [71, 125, 2.3], [128, 94, 2.2], [128, 107, 2.4], [128, 120, 2.2],
    [18, 151, 2.6], [25, 153, 2], [31, 149, 2.2], [78, 152, 2.2], [126, 152, 2]],
  // Surroundings, drawn outside the site only: neighbouring blocks and trees.
  around: {
    blocks: [[-52, 8, 40, 44], [-48, 62, 36, 30], [-54, 104, 42, 36], [-50, 150, 38, 40], [-30, 180, 44, 30],
      [22, 180, 50, 28], [84, 180, 40, 30], [134, 180, 46, 28], [140, 10, 42, 46], [144, 66, 34, 30],
      [140, 106, 46, 34], [146, 150, 36, 22], [14, -44, 46, 36], [70, -40, 52, 32], [132, -42, 40, 34]],
    trees: [[-20, 56, 3], [-14, 98, 2.6], [-26, 144, 2.8], [150, 60, 3], [158, 100, 2.6], [192, 40, 3],
      [6, -18, 2.8], [126, -14, 2.6], [64, 214, 3], [-60, 0, 3], [138, 146, 2.4], [-8, 178, 2.6]],
  },
  // Walkways used for directions: named points and the straight paths between them.
  nodes: {
    nw: [21, 13], n: [67, 13], ne: [123, 13], en: [123, 46],
    wm: [21, 72], c: [72, 72], em: [123, 72], w2: [21, 95], wg: [21, 128],
    sw: [21, 138], gs: [53, 138], s: [72, 138], ss: [101, 138], se: [123, 138],
    p: [50, 104], gate: [72, 158], wgate: [13, 128],
  },
  paths: [
    ['nw', 'n'], ['n', 'ne'], ['nw', 'wm'], ['ne', 'en'], ['en', 'em'], ['wm', 'c'], ['c', 'em'],
    ['wm', 'w2'], ['w2', 'wg'], ['wg', 'sw'], ['em', 'se'], ['sw', 'gs'], ['gs', 's'], ['s', 'ss'], ['ss', 'se'],
    ['s', 'gate'], ['wg', 'wgate'], ['wg', 'p'], ['p', 'c'], ['p', 's'],
  ],
};

// Parking areas. `id` matches a row in the Supabase `spots` table, `access` is the walkway
// point directions lead to, and `camera: true` marks the rack with a live camera.
export const SPOTS = [
  { id: 'north', name: 'North rack', rack: { x: 42, y: 19, w: 50, h: 10 }, access: 'n', capacity: 20, camera: true },
  { id: 'east', name: 'East rack', rack: { x: 108, y: 30, w: 11, h: 32 }, access: 'en', capacity: 16 },
  { id: 'west', name: 'West rack', rack: { x: 25, y: 80, w: 12, h: 30 }, access: 'w2', capacity: 16 },
  { id: 'gate', name: 'Gate rack', rack: { x: 38, y: 143, w: 30, h: 10 }, access: 'gs', capacity: 10 },
  { id: 'south', name: 'South rack', rack: { x: 82, y: 143, w: 38, h: 10 }, access: 'ss', capacity: 20 },
];
