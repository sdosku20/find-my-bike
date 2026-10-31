// Parking status from Supabase: initial load plus live row updates.
import { SUPABASE_URL, SUPABASE_ANON_KEY } from '../config.js';

const SUPABASE_JS = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.101.0/+esm';

export async function connect(onRow, onStatus) {
  const { createClient } = await import(SUPABASE_JS);
  const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, { auth: { persistSession: false } });
  // The table is tiny, so it is simply read again whenever live updates may have been missed:
  // after every (re)connection and when the page comes back from the background.
  const load = async () => {
    const { data, error } = await sb.from('spots').select('*');
    if (error) throw new Error(error.message);
    data.forEach(onRow);
  };
  await load();
  sb.channel('spots-status')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'spots' }, ({ new: row }) => {
      if (row?.id) onRow(row);
    })
    .subscribe(status => {
      if (status === 'SUBSCRIBED') load().catch(() => {});
      onStatus(status);
    });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') load().catch(() => {});
  });
  return sb;
}
