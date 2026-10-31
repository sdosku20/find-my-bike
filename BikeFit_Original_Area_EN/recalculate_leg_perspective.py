"""Approximate local image-scale compensation, not metric ground rectification.

Reuse frozen leg points and exclusions. Infer relative scale from comparable
bicycle silhouette heights in the same scene. Integrate reference-height /
local-height along each image segment; never divide absolute point coordinates.
"""
import copy
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from black_block_distance import draw_result,draw_distance_matrix


def corrected_distance(p,q,sample_x,sample_height,reference_height):
    p,q = np.asarray(p,float),np.asarray(q,float)
    length = float(np.linalg.norm(q-p))
    dx = q[0]-p[0]
    cuts = [0.,1.]
    if abs(dx)>1e-12:
        cuts += [float((x-p[0])/dx) for x in sample_x if 0<(x-p[0])/dx<1]
    cuts = sorted(cuts)
    integral = 0.
    for ta,tb in zip(cuts,cuts[1:]):
        ha,hb = np.interp([p[0]+dx*ta,p[0]+dx*tb],sample_x,sample_height)
        if min(ha,hb,reference_height)<=0:
            raise ValueError('Local and reference scales must be positive')
        inv_mean = 1/ha if abs(hb-ha)<1e-10 else math.log(hb/ha)/(hb-ha)
        integral += (tb-ta)*inv_mean
    return length*reference_height*integral


def apply_correction(frozen,scale):
    result = copy.deepcopy(frozen)
    lookup = {}
    for row in result['distances']:
        value = corrected_distance(*row['endpoints_xy'],scale['sample_x_px'],scale['sample_height_px'],scale['reference_height_px'])
        row['corrected_distance_ref_px'] = round(value,3)
        raw = math.dist(*row['endpoints_xy'])
        row['scale_correction_factor'] = value/raw if raw else 1.
        lookup[tuple(row['leg_ids'])] = row
    result['neighbour_distances'] = [lookup[tuple(row['leg_ids'])] for row in result['neighbour_distances']]
    result['perspective_scale_correction'] = scale
    result['distance_unit'] = 'reference_pixel_after_approximate_local_scale_compensation'
    result['physical_distance_calibrated'] = False
    result['ground_plane_rectified'] = False
    return result


def scale_from_detections(detections,image_size):
    if detections['frame_size_wh'] != list(image_size):
        raise ValueError('Scale evidence belongs to a different image size')
    samples = []
    excluded = []
    for point in detections['points']:
        a,b,c,d = point['box']
        if point['confidence'] < .5:
            excluded.append(dict(bicycle_id=point['bicycle_id'],reason='low_detection_confidence_for_scale_only'))
            continue
        if a<=1 or c>=image_size[0]-1 or b<=1 or d>=image_size[1]-1:
            excluded.append(dict(bicycle_id=point['bicycle_id'],reason='image_edge_truncation_for_scale_only'))
            continue
        samples.append(dict(bicycle_id=point['bicycle_id'],x=(a+c-1)/2,height=d-b,
                            confidence=point['confidence']))
    if len(samples)<3:
        raise ValueError('At least three reliable bicycle-height samples are required')
    samples.sort(key=lambda s:s['x'])
    xs = np.array([s['x'] for s in samples],float)
    heights = np.array([s['height'] for s in samples],float)
    smooth = [float(np.median(heights[np.argsort(abs(xs-x))[:3]])) for x in xs]
    return dict(method='relative_local_bicycle_height_scale_proxy',
        sample_x_px=xs.tolist(),sample_height_px=smooth,reference_height_px=float(np.median(heights)),
        raw_height_observations=samples,excluded_scale_observations=excluded,
        smoothing='median_of_three_nearest_bicycle_height_observations',
        segment_distance_method='integral_of_reference_height_over_local_height_along_image_segment',
        calibrated=False,ground_plane_rectified=False,
        assumption='Comparable physical bicycle heights; local scale is approximated as isotropic and varies only with image x.',
        limitations='Not full camera-perspective inversion. Bike shape, leaning, occlusion and non-ground leg tips can bias results. No real distance unit is known.')


def main():
    source = ROOT/'independent_leg_distances_20261028/results.json'
    detection_source = ROOT/'bottom_point_individual_20261028/far_clean/results.json'
    image_source = ROOT/'bicycle_black_background_white_20261028.png'
    out = ROOT/'independent_leg_perspective_20261028'
    frozen = json.loads(source.read_text(encoding='utf-8'))
    detections = json.loads(detection_source.read_text(encoding='utf-8'))
    image = cv2.imdecode(np.fromfile(str(image_source),np.uint8),cv2.IMREAD_GRAYSCALE)
    # Match the binary image to the retained mask behind the scale scene.
    original_mask = cv2.imdecode(np.fromfile(str(ROOT/'bicycle_color_background_gray_20261028/far_clean/bicycle_mask.png'),np.uint8),0)
    assert np.array_equal(image<128,original_mask>0)
    scale = scale_from_detections(detections,(image.shape[1],image.shape[0]))
    scale['detection_source'] = str(detection_source)
    result = apply_correction(frozen,scale)
    assert result['legs'] == frozen['legs']
    assert result['excluded_same_component_pairs'] == frozen['excluded_same_component_pairs']
    assert len(result['distances']) == len(frozen['distances'])
    assert all(r['block_ids'][0] != r['block_ids'][1] for r in result['distances'])
    out.mkdir(exist_ok=True)
    cv2.imencode('.png',draw_result(image,result))[1].tofile(str(out/'annotated.png'))
    cv2.imencode('.png',draw_distance_matrix(result))[1].tofile(str(out/'distance_matrix.png'))
    (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (out/'distances.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['编号','腿点1','腿点2','黑影1','黑影2','原始距离_像素','尺度近似修正距离_参考像素','修正系数'])
        for row in result['distances']:
            writer.writerow([row['gap_id'],*row['leg_ids'],*row['block_ids'],row['distance_px'],row['corrected_distance_ref_px'],row['scale_correction_factor']])
    print(json.dumps(dict(leg_points_unchanged=True,valid_pairs=len(result['distances']),excluded_same_component_pairs=len(result['excluded_same_component_pairs']),
        reference_height_px=scale['reference_height_px'],local_height_min=min(scale['sample_height_px']),local_height_max=max(scale['sample_height_px']),
        neighbours=[dict(leg_ids=r['leg_ids'],raw_px=r['distance_px'],corrected_ref_px=r['corrected_distance_ref_px']) for r in result['neighbour_distances']])),flush=True)


if __name__ == '__main__':
    main()
