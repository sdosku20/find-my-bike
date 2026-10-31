"""Measure white regions enclosed by straight links and original black edges.

All legs participate, including legs on the same connected shadow. A region
must be closed, separated from the exterior, and touch at least one added line.
The original binary silhouette is never expanded to force a closure.
"""
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from black_shadow_center_distance import label
from leg_boundary_lines import build_boundaries
from white_gap_areas import area_scale_weights

OUT = ROOT / 'line_closed_white_areas_20261028'


def closed_white_regions(image, top_lines, bottom_lines):
    """Count white pixel centres after adding one-pixel LINE_8 barriers.

    Four-connected white complements eight-connected black/line barriers, so
    diagonally connected barriers cannot leak at their corners.
    """
    top = np.zeros(image.shape, np.uint8)
    bottom = np.zeros_like(top)
    for target, lines in ((top, top_lines), (bottom, bottom_lines)):
        for line in lines:
            p, q = line['endpoints_xy']
            if any(not (0 <= x < image.shape[1] and 0 <= y < image.shape[0]) for x, y in (p, q)):
                raise ValueError('Boundary endpoint outside image')
            if image[p[1], p[0]] >= 128 or image[q[1], q[0]] >= 128:
                raise ValueError('Every straight link must end on a black silhouette')
            cv2.line(target, tuple(p), tuple(q), 1, 1, cv2.LINE_8)
    free = ((image >= 128) & (top == 0) & (bottom == 0)).astype(np.uint8)
    n, components, stats, centroids = cv2.connectedComponentsWithStats(free, connectivity=4)
    exterior = set(np.unique(np.concatenate((components[0], components[-1], components[:, 0], components[:, -1]))))
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    near_top = cv2.dilate(top, cross) > 0
    near_bottom = cv2.dilate(bottom, cross) > 0
    pockets = []
    for number in range(1, n):
        if number in exterior:
            continue
        a, b, w, h, area = map(int, stats[number])
        mask = components[b:b+h, a:a+w] == number
        touches_top = bool(np.any(mask & near_top[b:b+h, a:a+w]))
        touches_bottom = bool(np.any(mask & near_bottom[b:b+h, a:a+w]))
        if not (touches_top or touches_bottom):
            continue
        pockets.append(dict(box=[a, b, a+w, b+h], area_px2=area,
                            center_xy=centroids[number].tolist(), mask=mask,
                            touches_top_line=touches_top, touches_bottom_line=touches_bottom))
    pockets.sort(key=lambda p: (p['area_px2'] < 10, p['center_xy'][0], p['center_xy'][1]))
    for number, pocket in enumerate(pockets, 1):
        pocket['area_id'] = number
    return pockets, top, bottom


def draw(image, pockets, boundaries):
    h, w = image.shape
    visible = [p for p in pockets if p['area_px2'] >= 10]
    micro = [p for p in pockets if p['area_px2'] < 10]
    out = np.full((h + 138 + math.ceil(len(visible)/3)*28, w, 3), 255, np.uint8)
    out[:h] = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    palette = [(235, 185, 100), (120, 205, 245), (175, 140, 230), (150, 220, 145), (225, 180, 210)]
    for pocket in pockets:
        a, b, c, d = pocket['box']
        out[b:d, a:c][pocket['mask']] = palette[(pocket['area_id']-1) % len(palette)]
    for line in boundaries['top_lines'] + boundaries['bottom_lines']:
        p, q = line['endpoints_xy']
        cv2.line(out, tuple(p), tuple(q), (65, 70, 235), 2, cv2.LINE_AA)
    for leg in boundaries['legs']:
        cv2.circle(out, tuple(leg['point_xy']), 3, (65, 70, 235), -1, cv2.LINE_AA)
    for pocket in visible:
        a, b, c, d = pocket['box']
        distance = cv2.distanceTransform(np.pad(pocket['mask'].astype(np.uint8), 1), cv2.DIST_L2, 3)
        px, py = cv2.minMaxLoc(distance)[3]
        x, y = a+px-1, b+py-1
        cv2.circle(out, (x, y), 12, (255, 255, 255), -1, cv2.LINE_AA)
        label(out, str(pocket['area_id']), (x-5, y+5), .47, background=False)
    label(out, 'COLOUR = white area enclosed by red straight links and the original black contour.', (20, h+28), .6)
    label(out, 'All leg links count. Same-shadow inter-leg white areas count when enclosed. Exterior stays white.', (20, h+55), .54)
    label(out, '%d numbered regions | %d leg tips | total %d px2 | image area, NOT square metres.' %
          (len(visible), len(boundaries['legs']), sum(p['area_px2'] for p in pockets)), (20, h+82), .56)
    label(out, '%d tiny raster regions (<10 px2, total %d px2) are included in the total and CSV; labels omitted.' %
          (len(micro), sum(p['area_px2'] for p in micro)), (20, h+109), .5)
    for i, pocket in enumerate(visible):
        label(out, '#%d: %d px2' % (pocket['area_id'], pocket['area_px2']),
              (20+(i % 3)*(w//3), h+144+(i//3)*28), .52)
    return out


def rank_regions(pockets):
    ranked = sorted(pockets, key=lambda p: (-p['area_px2'], p['center_xy'][0], p['center_xy'][1]))
    for rank, pocket in enumerate(ranked, 1):
        pocket['area_rank'] = rank
    return ranked


def draw_ranked(image, ranked, boundaries):
    """Place decreasing-area ranks on the original image-sized canvas."""
    out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    for pocket in ranked:
        a, b, c, d = pocket['box']
        rank = pocket['area_rank']
        hue = int((rank-1)*35 % 180)
        colour = cv2.cvtColor(np.uint8([[[hue, 95, 248]]]), cv2.COLOR_HSV2BGR)[0, 0]
        out[b:d, a:c][pocket['mask']] = colour
    for line in boundaries['top_lines'] + boundaries['bottom_lines']:
        p, q = line['endpoints_xy']
        cv2.line(out, tuple(p), tuple(q), (65, 70, 235), 2, cv2.LINE_AA)
    for pocket in ranked:
        if pocket['area_px2'] < 10:
            continue  # Subpixel-sized raster corners stay in the table.
        a, b, c, d = pocket['box']
        distance = cv2.distanceTransform(np.pad(pocket['mask'].astype(np.uint8), 1), cv2.DIST_L2, 3)
        px, py = cv2.minMaxLoc(distance)[3]
        point = (a+px-1, b+py-1)
        text = str(pocket['area_rank'])
        cv2.circle(out, point, 17, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(out, point, 17, (55, 55, 55), 1, cv2.LINE_AA)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .62, 2)
        cv2.putText(out, text, (point[0]-tw//2, point[1]+th//2),
                    cv2.FONT_HERSHEY_SIMPLEX, .62, (25, 25, 25), 2, cv2.LINE_AA)
    return out


def main():
    image = cv2.imdecode(np.fromfile(str(ROOT/'bicycle_black_background_white_20261028.png'), np.uint8), 0)
    frozen = json.loads((ROOT/'independent_leg_distances_20261028/results.json').read_text(encoding='utf-8'))
    prior = json.loads((ROOT/'black_shadow_center_distances_20261028/results.json').read_text(encoding='utf-8'))
    boundaries = build_boundaries(image, frozen)
    pockets, top, bottom = closed_white_regions(image, boundaries['top_lines'], boundaries['bottom_lines'])
    ranked = rank_regions(pockets)
    weights = area_scale_weights(image.shape[1], prior['perspective_scale_correction'])
    ownership = np.zeros(image.shape, np.int32)
    OUT.mkdir(exist_ok=True)
    records = []
    for pocket in pockets:
        a, b, c, d = pocket['box']
        mask = pocket['mask']
        assert np.all(image[b:d, a:c][mask] >= 128)
        assert not np.any(ownership[b:d, a:c][mask])
        ownership[b:d, a:c][mask] = pocket['area_id']
        pocket['corrected_area_ref_px2'] = round(float(np.sum(mask*weights[a:c][None, :])), 3)
        name = 'area_%02d.png' % pocket['area_id']
        full_mask = np.zeros(image.shape, np.uint8)
        full_mask[b:d, a:c][mask] = 255
        cv2.imencode('.png', full_mask)[1].tofile(str(OUT/name))
        records.append(dict({k: v for k, v in pocket.items() if k != 'mask'}, mask_file=name))
    assert np.count_nonzero(ownership) == sum(p['area_px2'] for p in pockets)
    assert not np.any(ownership[(top | bottom) > 0])
    cv2.imencode('.png', draw(image, pockets, boundaries))[1].tofile(str(OUT/'annotated.png'))
    ranked_image = draw_ranked(image, ranked, boundaries)
    assert ranked_image.shape[:2] == image.shape
    cv2.imencode('.png', ranked_image)[1].tofile(str(OUT/'ranked_on_original.png'))
    cv2.imencode('.png', (ownership > 0).astype(np.uint8)*255)[1].tofile(str(OUT/'measured_white_mask.png'))
    cv2.imencode('.png', ((top | bottom) > 0).astype(np.uint8)*255)[1].tofile(str(OUT/'boundary_lines.png'))
    result = dict(areas=records, area_count=len(records), total_area_px2=sum(p['area_px2'] for p in records),
                  ranking_metric='original_white_area_px2_descending; ties_by_center_xy',
                  ranking_area_ids=[p['area_id'] for p in ranked],
                  area_definition='white_pixel_centres_in_closed_regions_touching_added_straight_links',
                  same_shadow_interleg_areas_included=True, exterior_background_excluded=True,
                  boundary_raster='one_pixel_LINE_8; line_pixels_excluded; white_4_connected',
                  preview_label_min_area_px2=10,
                  boundaries=boundaries, perspective_scale_correction=prior['perspective_scale_correction'],
                  physical_area_calibrated=False,
                  limitations='Upper endpoints and leg branches are silhouette geometry estimates. refpx2 is approximate scale compensation, not metric ground area.')
    (OUT/'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    with (OUT/'areas.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['区域编号', '白色面积_像素平方', '近似尺度补偿面积_参考像素平方', '接触上连线', '接触下连线'])
        for pocket in records:
            writer.writerow([pocket['area_id'], pocket['area_px2'], pocket['corrected_area_ref_px2'],
                             pocket['touches_top_line'], pocket['touches_bottom_line']])
    with (OUT/'area_ranking.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['面积排名', '原区域编号', '白色面积_像素平方', '近似尺度补偿面积_参考像素平方'])
        for pocket in ranked:
            writer.writerow([pocket['area_rank'], pocket['area_id'], pocket['area_px2'], pocket['corrected_area_ref_px2']])
    print(json.dumps(dict(area_count=len(records), total_area_px2=result['total_area_px2'],
                         legs=len(boundaries['legs']), areas=[p['area_px2'] for p in records])))


if __name__ == '__main__':
    main()
