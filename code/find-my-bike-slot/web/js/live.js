// Live camera view. Video comes straight from the station over WebRTC, with Supabase relaying only the
// handshake. Until that connects, or when a network blocks it, the viewer joins a separate frames channel
// and shows the station's 10 fps JPEG frames instead; it leaves that channel as soon as HD video plays.
import { ICE_SERVERS } from '../config.js';

const HELLO_MS = 4000;    // ask the station for a video connection this often until one is up
const VIDEO_STALE_MS = 3000;
const OFFLINE_MS = 12000; // no picture at all after this long: the station is not sending

// onStatus(text, warn, picture): `picture` is false while nothing real is on screen yet.
export function openLive(sb, spotId, { stage, video, canvas, onStatus, onSize }) {
  const ctx = canvas.getContext('2d');
  const me = globalThis.crypto?.randomUUID?.() ?? String(Math.random()).slice(2);
  const opened = Date.now();
  let channel = null, pc = null, pending = [], overlay = null, marks = [], blurred = false, frames = null;
  let lastVideo = 0, lastFrame = 0, decoding = false, closed = false;
  const send = (event, payload = {}) => channel?.send({ type: 'broadcast', event, payload: { ...payload, from: me } });
  const failed = status => status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED';
  const hd = () => pc?.connectionState === 'connected' && video.videoWidth > 0 && Date.now() - lastVideo < VIDEO_STALE_MS;

  function fit(w, h) {
    if (canvas.width === w && canvas.height === h) return;
    canvas.width = w;
    canvas.height = h;
    onSize(w, h);
  }

  function drawMarks() {
    const r = Math.max(10, canvas.width * 0.022);
    ctx.font = `700 ${Math.round(r * 1.05)}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const m of marks) {
      const x = m.x * canvas.width, y = m.y * canvas.height;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(16, 28, 22, 0.88)';
      ctx.fill();
      ctx.lineWidth = Math.max(2, r * 0.22);
      ctx.strokeStyle = m.color || '#fff';
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.fillText(String(m.rank), x, y + 1);
    }
  }

  // In HD the canvas is a transparent layer over the video carrying the gap shapes and numbers.
  function drawOverlay() {
    if (!hd()) return;
    fit(video.videoWidth, video.videoHeight);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (overlay) ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height);
    drawMarks();
  }

  // Fallback frames cost Supabase bandwidth, so only viewers without HD video subscribe to them.
  function wantFrames(on) {
    if (on && !frames && !closed) {
      const ch = (frames = sb.channel(`live-${spotId}-frames`, { config: { presence: { key: me, enabled: true } } }));
      ch.on('presence', { event: 'sync' }, () => {})
        .on('broadcast', { event: 'frame' }, onFrame)
        .subscribe(status => {
          if (ch !== frames) return;
          if (status === 'SUBSCRIBED') ch.track({ viewing: true });
          else if (failed(status)) {
            frames = null; // the next tick joins again
            sb.removeChannel(ch);
          }
        });
    } else if (!on && frames) {
      const ch = frames;
      frames = null;
      sb.removeChannel(ch);
    }
  }

  function tick() {
    const live = hd();
    if (stage.classList.contains('is-hd') !== live) {
      stage.classList.toggle('is-hd', live);
      if (live) drawOverlay();
    }
    wantFrames(!live);
    const privacy = blurred ? ' · blurred for privacy' : '';
    const last = Math.max(lastVideo, lastFrame);
    if (live) onStatus(`Live · HD${privacy}`, false, true);
    else if (!last && Date.now() - opened > OFFLINE_MS) onStatus('Camera offline · the station is not sending a picture', true, false);
    else if (!last) onStatus('Connecting to the camera…', false, false);
    else if (Date.now() - lastFrame < 4000) onStatus(`Live · standard quality${privacy}`, false, true);
    else onStatus(`Paused · last picture ${Math.round((Date.now() - last) / 1000)} s ago`, true, true);
  }

  const onVideoFrame = () => {
    lastVideo = Date.now();
    stage.classList.add('has-video'); // from now on a pause keeps the last frame on screen
    if (!stage.classList.contains('is-hd')) tick();
    if (!closed && video.requestVideoFrameCallback) video.requestVideoFrameCallback(onVideoFrame);
  };
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(onVideoFrame);
  else video.addEventListener('timeupdate', onVideoFrame);
  video.addEventListener('resize', drawOverlay);

  function onOverlay(text) {
    let msg;
    try { msg = JSON.parse(text); } catch { return; }
    if (msg.type !== 'overlay') return;
    blurred = Boolean(msg.blurred);
    if (!msg.png) {
      overlay = null;
      marks = msg.marks || [];
      drawOverlay();
      return;
    }
    const img = new Image();
    img.onload = () => {
      overlay = img;
      marks = msg.marks || [];
      drawOverlay();
    };
    img.src = `data:image/png;base64,${msg.png}`;
  }

  function onFrame({ payload }) {
    if (hd() || decoding || !payload?.jpg) return;
    decoding = true;
    const img = new Image();
    img.onload = () => {
      decoding = false;
      if (closed || hd()) return;
      fit(img.naturalWidth, img.naturalHeight);
      ctx.drawImage(img, 0, 0);
      marks = payload.marks || [];
      blurred = Boolean(payload.blurred);
      drawMarks();
      lastFrame = Date.now();
      tick();
    };
    img.onerror = () => { decoding = false; };
    img.src = `data:image/jpeg;base64,${payload.jpg}`;
  }

  async function onOffer({ payload }) {
    if (payload?.to !== me || closed) return;
    pc?.close();
    pending = [];
    const conn = (pc = new RTCPeerConnection({ iceServers: ICE_SERVERS }));
    conn.onicecandidate = e => { if (e.candidate) send('ice', { to: 'station', candidate: e.candidate.toJSON() }); };
    conn.ontrack = e => {
      video.srcObject = e.streams[0] || new MediaStream([e.track]);
      video.play().catch(() => {});
    };
    conn.ondatachannel = e => { e.channel.onmessage = m => onOverlay(m.data); };
    await conn.setRemoteDescription(payload.sdp);
    for (const c of pending.splice(0)) conn.addIceCandidate(c).catch(() => {});
    await conn.setLocalDescription(await conn.createAnswer());
    send('answer', { sdp: conn.localDescription.toJSON() });
  }

  function onIce({ payload }) {
    if (payload?.to !== me || !payload.candidate) return;
    if (pc?.remoteDescription) pc.addIceCandidate(payload.candidate).catch(() => {});
    else pending.push(payload.candidate);
  }

  const hello = () => { if (!closed && pc?.connectionState !== 'connected') send('hello'); };

  // Signalling channel; when it drops, it is rebuilt after a short pause instead of staying dead.
  function join() {
    const old = channel;
    const ch = (channel = sb.channel(`live-${spotId}`, { config: { presence: { key: me, enabled: true } } }));
    if (old) sb.removeChannel(old);
    ch.on('presence', { event: 'sync' }, () => {})
      .on('broadcast', { event: 'offer' }, m => onOffer(m).catch(() => {}))
      .on('broadcast', { event: 'ice' }, onIce)
      .subscribe(status => {
        if (ch !== channel || closed) return;
        if (status === 'SUBSCRIBED') {
          ch.track({ viewing: true });
          hello();
          tick();
        } else if (failed(status)) {
          onStatus('Connection lost · retrying', true, hd() || lastFrame > 0);
          setTimeout(() => { if (ch === channel && !closed) join(); }, 3000);
        }
      });
  }

  join();
  wantFrames(true);
  const timers = [setInterval(tick, 1000), setInterval(hello, HELLO_MS)];
  return () => {
    closed = true;
    timers.forEach(clearInterval);
    wantFrames(false);
    pc?.close();
    video.srcObject = null;
    if (channel) sb.removeChannel(channel);
  };
}
