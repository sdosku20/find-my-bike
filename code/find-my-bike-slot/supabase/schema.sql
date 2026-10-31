-- Find my Bike Slot · Supabase setup
-- Run once in the Supabase dashboard: SQL Editor → New query → paste → Run.
-- Safe to run again.

create table if not exists public.spots (
  id            text primary key,              -- matches SPOTS[].id in web/config.js
  name          text not null,
  capacity      integer,                        -- bike slots in the rack
  has_camera    boolean not null default false,
  photo_url     text,                           -- optional picture for racks without a camera
  free_estimate integer,                        -- estimated free slots; null = unknown
  bikes         integer,                        -- bicycles the camera detected
  gaps          jsonb not null default '[]',    -- top five gaps: rank, area_px2, pos (0 = left … 1 = right), fits
  source        text not null default 'sample' check (source in ('camera', 'manual', 'sample')),
  updated_at    timestamptz
);

alter table public.spots enable row level security;
grant select on public.spots to anon, authenticated;
grant update on public.spots to authenticated;

-- Everyone may read the parking status.
drop policy if exists "Public can read spots" on public.spots;
create policy "Public can read spots" on public.spots
  for select to anon, authenticated
  using (true);

-- Only users marked as a station (app_metadata.station = true) may change it.
drop policy if exists "Stations can update spots" on public.spots;
create policy "Stations can update spots" on public.spots
  for update to authenticated
  using (coalesce((auth.jwt() -> 'app_metadata' ->> 'station')::boolean, false))
  with check (coalesce((auth.jwt() -> 'app_metadata' ->> 'station')::boolean, false));

-- Push row changes to the website as they happen.
do $$
begin
  alter publication supabase_realtime add table public.spots;
exception when duplicate_object then null;
end $$;

insert into public.spots (id, name, capacity, has_camera, free_estimate, source) values
  ('north', 'North rack', 20, true,  null, 'camera'),
  ('east',  'East rack',  16, false, 9,    'sample'),
  ('south', 'South rack', 20, false, 0,    'sample'),
  ('west',  'West rack',  16, false, 2,    'sample'),
  ('gate',  'Gate rack',  10, false, 5,    'sample')
on conflict (id) do nothing;

-- Station user: create it under Authentication → Users → Add user → Create new user
-- (tick "Auto Confirm User"), then replace the e-mail below and run this to mark it as a station:
--
-- update auth.users
--    set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"station": true}'::jsonb
--  where email = 'station@example.com';
