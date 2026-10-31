// Zoom and pan for a photo or the live view: pinch, mouse wheel, drag, double-tap and the corner buttons.
// `frame` is the clipping box; its `.stage` child is what gets scaled.
const MAX_SCALE = 6;

export function attachZoom(frame) {
  const stage = frame.querySelector('.stage');
  if (!stage) return () => {};
  const pointers = new Map();
  let scale = 1, x = 0, y = 0, gesture = null, lastTap = 0;

  // Keep the stage covering its own box: no panning past the picture's edges.
  function apply() {
    const w = stage.offsetWidth, h = stage.offsetHeight;
    scale = Math.min(MAX_SCALE, Math.max(1, scale));
    x = Math.min(0, Math.max(w - w * scale, x));
    y = Math.min(0, Math.max(h - h * scale, y));
    stage.style.transform = scale === 1 ? '' : `translate(${x}px, ${y}px) scale(${scale})`;
    frame.classList.toggle('is-zoomed', scale > 1);
  }

  // Zoom by `factor` around a point in frame coordinates, keeping that point under the finger.
  function zoomAt(factor, fx, fy) {
    const sx = fx - stage.offsetLeft, sy = fy - stage.offsetTop;
    const next = Math.min(MAX_SCALE, Math.max(1, scale * factor));
    x = sx - (sx - x) * (next / scale);
    y = sy - (sy - y) * (next / scale);
    scale = next;
    apply();
  }

  function reset() {
    scale = 1;
    x = y = 0;
    apply();
  }

  const point = e => {
    const r = frame.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const pinchState = () => {
    const [a, b] = [...pointers.values()];
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.hypot(a[0] - b[0], a[1] - b[1])];
  };

  function down(e) {
    if (e.target.closest('.zoom-controls')) return;
    pointers.set(e.pointerId, point(e));
    try { frame.setPointerCapture(e.pointerId); } catch { /* synthetic or already released */ }
    gesture = pointers.size === 2 ? { pinch: pinchState() } : { start: point(e), moved: false, t: Date.now() };
  }

  function move(e) {
    const prev = pointers.get(e.pointerId);
    if (!prev || !gesture) return;
    const now = point(e);
    pointers.set(e.pointerId, now);
    if (pointers.size === 2 && gesture.pinch) {
      const [cx, cy, d] = pinchState(), [px, py, pd] = gesture.pinch;
      x += cx - px;
      y += cy - py;
      zoomAt(pd ? d / pd : 1, cx, cy);
      gesture.pinch = [cx, cy, d];
    } else if (pointers.size === 1 && gesture.start) {
      if (Math.hypot(now[0] - gesture.start[0], now[1] - gesture.start[1]) > 6) gesture.moved = true;
      if (scale > 1) {
        x += now[0] - prev[0];
        y += now[1] - prev[1];
        apply();
      }
    }
  }

  function up(e) {
    if (!pointers.delete(e.pointerId)) return;
    const tap = !pointers.size && gesture?.start && !gesture.moved && Date.now() - gesture.t < 300;
    if (tap && e.type === 'pointerup') {
      if (Date.now() - lastTap < 350) {
        lastTap = 0;
        if (scale > 1) reset();
        else zoomAt(2.5, ...point(e));
      } else {
        lastTap = Date.now();
      }
    }
    // One finger left after a pinch keeps panning, but never counts as a tap.
    gesture = pointers.size === 1 ? { start: [...pointers.values()][0], moved: true, t: 0 } : null;
  }

  function wheel(e) {
    e.preventDefault();
    zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), ...point(e));
  }

  function setFull(on) {
    frame.classList.toggle('is-full', on);
    document.body.classList.toggle('media-full', on);
    try {
      if (on) frame.requestFullscreen?.()?.catch?.(() => {});
      else if (document.fullscreenElement === frame) document.exitFullscreen()?.catch?.(() => {});
    } catch { /* the CSS full-screen view still works, e.g. on iPhone */ }
    reset();
  }

  function click(e) {
    const action = e.target.closest('[data-zoom]')?.dataset.zoom;
    if (!action) return;
    const cx = frame.clientWidth / 2, cy = frame.clientHeight / 2;
    if (action === 'in') zoomAt(1.6, cx, cy);
    else if (action === 'out') zoomAt(1 / 1.6, cx, cy);
    else setFull(!frame.classList.contains('is-full'));
  }

  const onKey = e => { if (e.key === 'Escape' && frame.classList.contains('is-full')) setFull(false); };
  const onFullscreen = () => { if (!document.fullscreenElement && frame.classList.contains('is-full')) setFull(false); };
  const resize = new ResizeObserver(apply);

  frame.addEventListener('pointerdown', down);
  frame.addEventListener('pointermove', move);
  frame.addEventListener('pointerup', up);
  frame.addEventListener('pointercancel', up);
  frame.addEventListener('wheel', wheel, { passive: false });
  frame.addEventListener('click', click);
  document.addEventListener('keydown', onKey);
  document.addEventListener('fullscreenchange', onFullscreen);
  resize.observe(frame);

  return () => {
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('fullscreenchange', onFullscreen);
    resize.disconnect();
    if (frame.classList.contains('is-full')) setFull(false);
  };
}
