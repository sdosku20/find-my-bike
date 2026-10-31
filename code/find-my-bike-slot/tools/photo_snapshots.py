"""Turn rack photos into website snapshots, using the BikeFit detection program unchanged.

For each rack in photos.json:
  1. scale the photo to at most 1920 px (the same limit as the live camera path),
  2. run BikeFit's analyze_colour + export (full results go to --results, which stays local),
  3. blur number plates (boxes in photos.json, in original-photo pixels) and any detected people,
  4. draw BikeFit's gap overlay on top and save a web-sized JPEG to web/photos/<rack>.jpg,
  5. write web/photos/snapshots.js with the bike count, top five gaps and free-slot estimate.

Free slots = gap area ÷ bike_area_px2 (one bike's gap area in that photo). Set it per photo when racks are
photographed from different distances: pick a gap that is exactly one free slot and use its area.

Run it with the BikeFit runtime, which has OpenCV and the model:
  <BikeFit>\\runtime\\python.exe tools\\photo_snapshots.py --bikefit <BikeFit folder> --images <photo folder>
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MAX_SIDE = 1920    # live frames are capped at this size, so areas stay comparable
WEB_WIDTH = 1280   # published image width


def blur(image, box):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.shape[1], x1), min(image.shape[0], y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    region = image[y0:y1, x0:x1]
    small = cv2.resize(region, (max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), interpolation=cv2.INTER_AREA)
    image[y0:y1, x0:x1] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR), (0, 0), 6)


def taken_at(name):
    m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', name)
    return '{}-{}-{}T{}:{}:{}'.format(*m.groups()) if m else None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bikefit', type=Path, required=True, help='BikeFit tool folder (contains colour_gap_top5.py)')
    parser.add_argument('--images', type=Path, required=True, help='folder with the original photos')
    parser.add_argument('--config', type=Path, default=HERE / 'photos.json')
    parser.add_argument('--web', type=Path, default=HERE.parent / 'web')
    parser.add_argument('--results', type=Path, default=HERE / 'results', help='full BikeFit output per rack (local only)')
    args = parser.parse_args()

    sys.path.insert(0, str(args.bikefit.resolve()))
    from colour_gap_top5 import analyze_colour, composite, export
    from semantic_evidence import BicycleSegmenter

    config = json.loads(args.config.read_text(encoding='utf-8'))
    detector = BicycleSegmenter(args.bikefit / 'models' / 'yolov8s-seg.onnx')
    (args.web / 'photos').mkdir(parents=True, exist_ok=True)
    snapshots = {}

    for rack, entry in config['photos'].items():
        source = args.images / entry['file']
        original = cv2.imdecode(np.fromfile(str(source), np.uint8), cv2.IMREAD_COLOR)
        if original is None:
            raise SystemExit(f'Cannot read {source}')
        scale = min(1.0, MAX_SIDE / max(original.shape[:2]))
        image = cv2.resize(original, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else original

        result = analyze_colour(image, detector)
        export(image, result, args.results / rack, source)

        private = image.copy()
        for box in entry.get('blur', []):
            blur(private, [v * scale for v in box])
        for person in (p for p in detector.infer(image) if p['class'] == 0):
            blur(private, person['box'])
        annotated = composite(private, result['overlay'])
        web_scale = WEB_WIDTH / annotated.shape[1]
        annotated = cv2.resize(annotated, None, fx=web_scale, fy=web_scale, interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise SystemExit(f'Cannot encode the image for {rack}')
        jpg.tofile(str(args.web / 'photos' / f'{rack}.jpg'))

        width, bikes = image.shape[1], result['instances']
        bike_area = entry.get('bike_area_px2', config['bike_area_px2'])
        gaps = [dict(rank=g['rank'], area_px2=g['area_px2'], pos=round(g['target_xy'][0] / width, 2),
                     fits=int(g['area_px2'] // bike_area)) for g in result['ranking']]
        free = sum(g['fits'] for g in gaps)
        # With fewer than two bikes nothing is enclosed, so the photo itself can't tell the capacity.
        snapshots[rack] = dict(photo=f'photos/{rack}.jpg', taken_at=taken_at(entry['file']), bikes=bikes,
                               free_estimate=free, capacity=bikes + free if bikes >= 2 else None,
                               bike_area_px2=bike_area, gaps=gaps)
        print(f"{rack:6} {entry['file']}: {bikes} bikes, {len(result['ranked'])} gaps, "
              f"top five {[g['area_px2'] for g in gaps]} px² ÷ {bike_area} → ~{free} free")

    (args.web / 'photos' / 'snapshots.js').write_text(
        '// Generated by tools/photo_snapshots.py from tools/photos.json. Do not edit by hand.\n'
        f'// Photos scaled to {MAX_SIDE} px, analysed with BikeFit colour_gap_top5; free slots = gap area ÷ bike_area_px2.\n'
        'export const SNAPSHOTS = ' + json.dumps(snapshots, indent=2, ensure_ascii=False) + ';\n', encoding='utf-8')


if __name__ == '__main__':
    main()
