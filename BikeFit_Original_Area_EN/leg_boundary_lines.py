"""Straight links through all lower branches and facing upper shadow edges.

Retained black components reuse the frozen analysis; every supported lower
branch is scanned. Upper points are silhouette estimates, not verified
anatomical handlebars. Area measurements live in line_closed_white_areas.py.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from black_shadow_center_distance import label
from black_block_distance import lowest_pixel

OUT = ROOT / 'all_leg_boundary_lines_20261028'


def connect_all_legs(legs):
    ordered = sorted(legs, key=lambda item: (*item['point_xy'], item['leg_id']))
    return [dict(leg_ids=[first['leg_id'], second['leg_id']],
                 block_ids=[first['block_id'], second['block_id']],
                 endpoints_xy=[first['point_xy'], second['point_xy']],
                 same_shadow=first['block_id'] == second['block_id'])
            for first, second in zip(ordered, ordered[1:])]


def all_leg_tips(image, blocks):
    """Continue past the first branch split so shorter nested legs survive."""
    _, components = cv2.connectedComponents((image < 128).astype(np.uint8), 8)
    legs = []
    for block in blocks:
        a, b, c, d = block['box']
        mask = components[b:d, a:c] == block['component_label']
        h, w = mask.shape
        area = int(mask.sum())
        tips = {}
        for cut in range(int(h * .50), int(h * .85) + 1):
            n, labels, stats, _ = cv2.connectedComponentsWithStats(mask[cut:].astype(np.uint8), 8)
            for number in range(1, n):
                x, y, bw, bh, pixels = map(int, stats[number])
                if pixels < max(6, area * .01) or bh < max(3, h * .10):
                    continue
                px, py = lowest_pixel(labels == number)
                py += cut
                if py >= h * .65:
                    tips.setdefault((a + px, b + py), b + cut)
        if not tips:
            px, py = lowest_pixel(mask)
            tips[(a + px, b + py)] = None
        for point, cut in sorted(tips.items()):
            legs.append(dict(block_id=block['block_id'], component_label=block['component_label'],
                             point_xy=list(point), first_supported_cut_y=cut))
    legs.sort(key=lambda item: (*item['point_xy'], item['block_id']))
    for number, leg in enumerate(legs, 1):
        leg['leg_id'] = number
    return legs


def upper_points(image, blocks):
    _, components = cv2.connectedComponents((image < 128).astype(np.uint8), 8)
    typical_height = float(np.median([b['box'][3] - b['box'][1] for b in blocks])) if blocks else 0.
    points = []
    for block in blocks:
        a, b, c, d = block['box']
        # A short detached ground fragment supplies no upper / handlebar
        # evidence. Its frozen leg still participates in the bottom polyline.
        if d - b < .35 * typical_height:
            continue
        mask = components[b:d, a:c] == block['component_label']
        # A lower neighbouring bicycle may only enter the initial band by a
        # few pixels. Continue downwards until it has enough depth to count,
        # before it joins the taller silhouette. Keep each branch's earliest
        # supported extrema so later shoulder growth cannot move its cap.
        supported = {}
        for cut in range(max(1, int((d-b)*.23)), max(1, int((d-b)*.31))+1):
            band = mask[:cut]
            n, labels, stats, _ = cv2.connectedComponentsWithStats(band.astype(np.uint8), 8)
            known = {int(labels[y,x]) for x,y in supported}
            for number in range(1, n):
                if number in known:
                    continue
                if stats[number, cv2.CC_STAT_AREA] < max(6, int(mask.sum()) * .001):
                    continue
                reaches_high = stats[number, cv2.CC_STAT_TOP] <= (d - b) * .10
                substantial_depth = stats[number, cv2.CC_STAT_HEIGHT] >= max(3, (d - b) * .08)
                if not (reaches_high or substantial_depth):
                    continue
                yy, xx = np.nonzero(labels == number)
                y = int(yy.min())
                xs = xx[yy == y]
                px = int(xs[np.argmin(abs(xs - np.median(xs)))])
                supported.setdefault((px,y),(yy,xx))
        for (px,y),(yy,xx) in supported.items():
            # Prefer protrusions near the top; pure x extrema can select a
            # shoulder lower down instead of the upper bar-like silhouette.
            left = int(np.argmin(xx + 2 * yy))
            right = int(np.argmax(xx - 2 * yy))
            points.append(dict(block_id=block['block_id'], point_xy=[a + px, b + y],
                               facing_left_xy=[a + int(xx[left]), b + int(yy[left])],
                               facing_right_xy=[a + int(xx[right]), b + int(yy[right])],
                               source='persistent_upper_branch_extrema_with_vertical_penalty_2',
                               handlebar_identity_verified=False))
    points.sort(key=lambda p: ((p['facing_left_xy'][0]+p['facing_right_xy'][0])/2, p['point_xy'][1]))
    return points


def build_boundaries(image, frozen):
    tops = upper_points(image, frozen['blocks'])
    legs = all_leg_tips(image, frozen['blocks'])
    return dict(source=frozen.get('source', 'current_frame_bicycle_mask'), legs=legs,
                upper_points=tops, bottom_lines=connect_all_legs(legs),
                top_lines=[dict(block_ids=[p['block_id'], q['block_id']],
                                endpoints_xy=[p['facing_right_xy'], q['facing_left_xy']])
                           for p, q in zip(tops, tops[1:])],
                bottom_rule='all_supported_lower_branch_tips_in_x_order_including_same_shadow_pairs',
                branch_rule='all_cuts_from_50_to_85_percent_height; branch_area_at_least_1_percent; height_at_least_10_percent',
                upper_rule='link_persistent_upper_branches_in_x_order; scan_cuts_23_to_31_percent; reaches_upper_10_percent_OR_depth_at_least_8_percent; earliest_supported_extrema_penalty_2y',
                upper_minimum_height_fraction_of_median=.35,
                excluded_upper_block_ids=[b['block_id'] for b in frozen['blocks']
                    if b['block_id'] not in {p['block_id'] for p in tops}],
                ignored_small_components=frozen['ignored_small_components'],
                physical_distance_calibrated=False)


def draw_lines(image, result):
    h, w = image.shape
    out = np.full((h + 110, w, 3), 255, np.uint8)
    out[:h] = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    for line in result['bottom_lines']:
        p, q = line['endpoints_xy']
        cv2.line(out, tuple(p), tuple(q), (35, 60, 230), 2, cv2.LINE_AA)
    for line in result['top_lines']:
        p, q = line['endpoints_xy']
        cv2.line(out, tuple(p), tuple(q), (220, 135, 20), 2, cv2.LINE_AA)
    for leg in result['legs']:
        p = tuple(leg['point_xy'])
        cv2.circle(out, p, 5, (35, 60, 230), -1, cv2.LINE_AA)
        label(out, 'P%d' % leg['leg_id'], (p[0] - 10, p[1] + 23), .45)
    for upper in result['upper_points']:
        p = tuple(upper['point_xy'])
        cv2.circle(out, p, 5, (220, 135, 20), -1, cv2.LINE_AA)
        label(out, 'B%d' % upper['block_id'], (p[0] - 10, p[1] - 15), .5)
    label(out, 'RED: every leg tip joined in left-to-right order, including legs of the same shadow.', (20, h + 30), .58)
    label(out, 'BLUE: adjacent upper silhouette / handlebar estimates joined by straight lines.', (20, h + 58), .58)
    label(out, '%d legs, %d lower segments. Area results: line_closed_white_areas_20261028.' %
          (len(result['legs']), len(result['bottom_lines'])), (20, h + 86), .56)
    return out


def main():
    frozen = json.loads((ROOT / 'independent_leg_distances_20261028/results.json').read_text(encoding='utf-8'))
    source = ROOT / 'bicycle_black_background_white_20261028.png'
    image = cv2.imdecode(np.fromfile(str(source), np.uint8), 0)
    result = build_boundaries(image, frozen)
    tops, bottom, top = result['upper_points'], result['bottom_lines'], result['top_lines']
    legs = result['legs']
    assert len(bottom) == max(0, len(legs) - 1)
    linked = {number for line in bottom for number in line['leg_ids']}
    if len(legs) > 1:
        assert linked == {leg['leg_id'] for leg in legs}
    for item in legs + tops:
        x, y = item['point_xy']
        assert image[y, x] < 128
    result['measurements_pending_definition'] = False
    OUT.mkdir(exist_ok=True)
    cv2.imencode('.png', draw_lines(image, result))[1].tofile(str(OUT / 'annotated.png'))
    (OUT / 'boundaries.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(legs=len(legs), lower_segments=len(bottom), upper_segments=len(top),
                          same_shadow_lower_segments=sum(line['same_shadow'] for line in bottom))))


if __name__ == '__main__':
    main()
