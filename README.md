# Find my Bike Slot · BaselHack 2026 (Endress+Hauser challenge)

A website that shows which bike racks on the site have free space: a live camera view, analysed photos, a
bird's-eye map and walking directions. It works on phones and laptops, with no app to install.

| Folder | What it is |
|---|---|
| `find-my-bike/` | The GitHub repository that Vercel deploys: the website (`code/find-my-bike-slot/web`), the Supabase database setup (`supabase/schema.sql`), the photo analysis tool and the documentation. Its README explains the setup step by step. |
| `BikeFit_Original_Area_EN/` | The camera station: the BikeFit gap-detection program with its own Python runtime and model. It runs on the laptop or Jetson Nano that has the camera. |

## How it works

1. The station page (`BikeFit_Original_Area_EN/Start_Tool.cmd`) opens the camera and detects the gaps between parked bikes.
2. It sends the free-spot counts to Supabase, and streams the live video straight to viewers' browsers over WebRTC.
3. The website shows each rack's status in colour on the map. Open a rack to see the live view or its photo, the free spots and the gaps, largest first.

## Run it

- **Station (Windows):** double-click `BikeFit_Original_Area_EN/Start_Tool.cmd`, turn on the camera, and keep that window visible.
- **Website locally:** in `find-my-bike/code/find-my-bike-slot/web`, run `python -m http.server 8000` and open http://localhost:8000.
- **Website online:** deployed by Vercel from the GitHub repository.

## Privacy

Detection runs on the station. Only the counts are stored, the live view is never recorded, and number plates
in the photos are blurred.
