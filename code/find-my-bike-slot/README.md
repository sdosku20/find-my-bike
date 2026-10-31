# Find my Bike Slot

A website that shows bicycle parking availability on a bird's-eye plan of the site, with a live
camera view and walking directions from your GPS position.

```
Camera ─▶ Jetson Nano: BikeFit station page (detects gaps between bikes)
              │  within ~1 s of a change (heartbeat every 15 s): free slots + top-5 gaps → Supabase table "spots"
              │  live view: HD video straight to each viewer (WebRTC; Supabase only relays the handshake)
              │  fallback for blocked networks: 10 fps JPEG frames → Supabase Realtime (not stored)
              ▼
        Website on Vercel (this folder) ─▶ any phone or computer browser
```

- `web/`: the website. Plain HTML, CSS and JavaScript with no build step. On a phone it shows the total, the
  plan and the rack list, one below the other; opening a rack gives the picture the whole width, with the free
  count and the gaps (largest first) underneath. From 900 px wide (laptops) the rack list stays on the left and
  the plan or the open rack fills the rest. Fonts (Figtree, IBM Plex Mono, SIL Open Font License) are in `web/fonts/`.
- `supabase/schema.sql`: the database table and access rules.
- The station changes live in `BikeFit_Original_Area_EN/tool/app.html` (the "Online sharing" box) and one
  line in `tool/camera.js`. The Python backend is unchanged.

## 1. Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. **SQL Editor → New query**: paste `supabase/schema.sql` and run it.
3. **Authentication → Users → Add user → Create new user**: create the station user
   (e.g. `station@yourteam.ch`) with a strong password and tick *Auto Confirm User*.
4. Run the `update auth.users …` statement at the bottom of `schema.sql` with that e-mail address.
   Only this user can now change the parking status.
5. **Authentication → Sign In / Providers**: turn off *Allow new users to sign up*.
6. **Project Settings → API**: copy the *Project URL* and the *anon public* key.

## 2. Website

Open `web/config.js` and paste `SUPABASE_URL` and `SUPABASE_ANON_KEY`. The anon key is meant to be public;
the database rules only let visitors read.

While you are there, set the real position of the site:
- `SITE.anchor.lat/lng`: the GPS position of the building centre (in Google Maps, right-click → copy the coordinates).
- `SITE.bearing`: the compass direction the top of the plan faces (0 = north, 90 = east).

Racks, buildings (rectangles or outlines with any angles), gates, roads, the plaza, trees and the walkways
are all in `config.js`, in metres. `around` holds the neighbouring blocks drawn outside the site, so a wide
laptop screen or a tall phone shows surroundings instead of empty space.

Try it locally (from the `web` folder): `python -m http.server 8000`, then open <http://localhost:8000>.
Without Supabase details the site runs on sample data.

## 3. Station (Jetson Nano)

1. Copy `tool/app.html` and `tool/camera.js` from this computer to the Jetson's copy of the BikeFit tool.
2. In `tool/app.html`, fill in `window.BIKESLOT_STATION`: Supabase URL, anon key, the station user's e-mail and
   password, and `websiteUrl`. `spotId: 'north'` is the rack this camera watches.
3. Start the tool as usual and turn on the camera. The *Online sharing* box should say
   `Publishing to "north" · … live viewers`. The Jetson needs internet access.
4. Calibrate once: when gap 1 on screen is exactly one bike wide, press **Gap 1 = one bike**.
   Free slots are estimated from gap area divided by that value.

The station page must stay open and visible in the browser, because browsers slow down background tabs.
While sharing, it keeps the screen from going to sleep (a sleeping computer stops the camera). If the camera
is switched off and on again, viewers get the live view back by themselves within a few seconds.
The station password sits in `app.html` on the Jetson, which the tool only serves to that machine itself (`127.0.0.1`).

## 4. Deploy to Vercel

1. Push this `find-my-bike-slot` folder to a GitHub repository.
2. On [vercel.com](https://vercel.com): **Add New → Project →** import the repository.
3. Set **Root Directory** to `web` and **Framework Preset** to *Other*. Leave the build command empty.
4. Deploy. Every push to GitHub redeploys the site.

## Photos for racks without a camera

Racks without a camera show a photo analysed with the BikeFit program (`tools/photo_snapshots.py`):

1. List the photos in `tools/photos.json`: which file belongs to which rack, blur boxes for number plates
   (in original-photo pixels), and `bike_area_px2`, the gap area of one free slot in that photo.
2. Run with the BikeFit runtime:
   ```
   <BikeFit>\runtime\python.exe tools\photo_snapshots.py --bikefit <BikeFit folder> --images <photo folder>
   ```
3. It writes `web/photos/<rack>.jpg` (blurred, gaps marked) and `web/photos/snapshots.js`. Commit both.
   The full BikeFit output goes to `tools/results/`, which stays local because it contains the unblurred originals.

Keep the original photos out of the public repository: they show readable number plates.
A live camera row in Supabase always takes priority over a photo, and a photo over the sample data.
With at most one bike and no gaps the rack counts as empty, because the program measures gaps between bikes.

## Useful links

| Link | What it does |
|---|---|
| `/#north` | Opens a rack directly; the browser's back button returns to the plan |
| `/?spot=north` | Also opens a rack, e.g. from a QR code on the rack |
| `/?go=north` | Starts directions to a rack |
| `/?sim=20,60` | Simulates your position on the plan (x,y in metres), useful for demos on a laptop |

When you are more than 400 m away, a slim bar on the plan offers Google Maps directions to the main gate.
**Demo here** places the plan around your current position, so you can walk the route anywhere;
open the site with `?demo=off` to put it back at the real location.

GPS readings are smoothed, so a laptop's Wi-Fi position (often 50 m off and jumping) settles to a steady dot.
The ring around the dot is capped at 9 m so it never covers the plan.

## Privacy

- The station sends only numbers (free slots, gap sizes and positions) to the database.
- The live video goes directly from the station to the viewer's browser and is never stored. Fallback frames go
  over Supabase Realtime only to viewers without a direct connection, and are never stored either.
- Supabase free plan: 2 million Realtime messages and 5 GB transfer a month. HD video uses none of it; each fallback
  viewer uses about 1.6 GB per hour (lower `FRAME_MS` / `FRAME_BUDGET` in the station's `app.html` if needed).
- *Blur the shared camera image* on the station is off by default. Turn it on so faces are not recognisable in
  the live view; the gap overlay stays sharp.
- No accounts or tracking for visitors. GPS stays in the visitor's browser.

## Later

- More cameras: one station per camera, each with its own `spotId`, and set `camera: true` for that rack in `config.js`.
- Hardening: Realtime broadcast channels are public in this version (anyone with the anon key could send
  frames). Switch to private channels with Realtime Authorization before a real rollout.
