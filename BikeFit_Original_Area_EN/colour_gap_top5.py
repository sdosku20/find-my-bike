"""Separate visible areas enclosed by automatic bicycle y-extrema links."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
import cv2
import numpy as np
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from black_block_distance import analyze_black_blocks
from leg_boundary_lines import build_boundaries
from line_closed_white_areas import closed_white_regions, rank_regions
from semantic_evidence import BicycleSegmenter
from shadow_gap_grouping import compensate_shadows
from automatic_boundary import automatic_bounded_regions, automatic_boundary, render_boundary
from bicycle_recognition import recognise_bicycles, instance_records, render_instances
from paired_gap_grouping import group_pair_gaps, annotate_gap_parts
from side_gap_inference import supplement_side_gaps, draw_side_proposals
from vehicle_geometry import estimate_vehicle_geometry
from scene_layout import analyze_scene_masks
from scene_layout import parking_rows
from occupancy_review import covered_surface_review
ROOT = Path(__file__).resolve().parent
COLORS = [(60,205,95),(245,175,55),(70,200,245),(220,100,215),(70,125,245)]
RANKING_METRIC = 'middle_visible_area_side20_frame_alignment_trial'

def analyze_mask(bicycle_mask, observations=None):
    return analyze_scene_masks(bicycle_mask, observations or [])

def render_overlay(shape, ranked, limit=5):
    overlay = np.zeros((*shape, 4), np.uint8)
    rows = []
    for pocket in ranked[:limit]:
        display_rank = pocket.get('rank', pocket['area_rank'])
        a, b, c, d = pocket['box']
        mask = pocket['mask']
        colour = COLORS[(display_rank-1) % len(COLORS)]
        overlay[b:d, a:c][mask] = (*colour, 110)
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (*colour, 255), 2, offset=(a,b))
        if pocket.get('occlusion_inferred') and 'side' not in pocket.get('parallel_review', {}):
            polygon = pocket['parallel_review']['inferred_corridor_polygon_xy']
            for first,last in zip(polygon,polygon[1:]+polygon[:1]):
                p,q = np.asarray(first),np.asarray(last)
                length = float(np.linalg.norm(q-p))
                for start in np.arange(0,length,14):
                    lo=p+(q-p)*(start/max(1,length));hi=p+(q-p)*(min(start+8,length)/max(1,length))
                    cv2.line(overlay,tuple(np.rint(lo).astype(int)),tuple(np.rint(hi).astype(int)),
                             (*colour,255),2,cv2.LINE_AA)
        distance = cv2.distanceTransform(np.pad(mask.astype(np.uint8), 1), cv2.DIST_L2, 3)
        px, py = cv2.minMaxLoc(distance)[3]
        x, y = a+px-1, b+py-1
        if 'ground_interval_xy' in pocket:
            ground = sum(p[1] for p in pocket['ground_interval_xy'])/2
            h = pocket['local_height_px']
            yy = np.arange(distance.shape[0])[:,None]+b-1
            lower_distance = np.where((yy>=ground-.18*h)&(yy<=ground+.05*h),distance,0).astype(np.float32)
            if lower_distance.max()>0:
                px,py = cv2.minMaxLoc(lower_distance)[3]
                x,y = a+px-1,b+py-1
        cv2.circle(overlay, (x,y), 17, (20, 35, 25, 255), -1, cv2.LINE_AA)
        text = str(display_rank)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .65, 2)
        cv2.putText(overlay, text, (x-tw//2,y+th//2), cv2.FONT_HERSHEY_SIMPLEX, .65,
                    (255,255,255,255), 2, cv2.LINE_AA)
        rows.append(dict(rank=display_rank, area_id=pocket['area_id'], area_px2=pocket['area_px2'],
                         target_xy=[x,y], box=pocket['box'], color='#%02x%02x%02x' % colour[::-1]))
        if 'ranking_score' in pocket:
            rows[-1].update(ranking_score=pocket['ranking_score'],
                            visible_area_rank=pocket['area_rank'])
            if 'entry_connected_area_px2' in pocket:
                rows[-1]['entry_connected_area_px2'] = pocket['entry_connected_area_px2']
        if 'candidate_status' in pocket:
            rows[-1].update(candidate_status=pocket['candidate_status'],occlusion_inferred=pocket['occlusion_inferred'])
        if 'birdseye' in pocket:
            rows[-1].update(row_id=pocket['row_id'],ease_score=pocket['ranking_score'],
                            relative_clearance_bike_widths=round(pocket['birdseye']['width_in_bike_widths'],2),
                            angle_deg=pocket['birdseye']['angle_deg'],
                            physical_fit_verified=False)
    return overlay, rows

def composite(image, overlay):
    alpha = overlay[:,:,3:4].astype(np.float32)/255.
    return np.rint(image*(1-alpha) + overlay[:,:,:3]*alpha).astype(np.uint8)


def analyze_colour(image, detector, limit=5):
    started = time.perf_counter()
    detail_source = None
    source_size = list(image.shape[1::-1])
    if max(image.shape[:2]) > 1920:
        detail_source = image
        scale = 1920/max(image.shape[:2])
        image = cv2.resize(image, (round(image.shape[1]*scale),round(image.shape[0]*scale)))
    prepared, lighting = compensate_shadows(image)
    observations, recognition = recognise_bicycles(prepared, image, detector, detail_source=detail_source)
    for observation in observations:
        observation['geometry'] = estimate_vehicle_geometry(image, observation)
    mask = np.zeros(image.shape[:2], bool)
    for observation in observations:
        if observation['mask'].shape != mask.shape:
            raise ValueError('Bicycle mask must match the frame dimensions.')
        mask |= observation.get('obstacle_mask',observation['mask'])
        if 'scene_obstacle_mask' in observation:
            mask |= observation['scene_obstacle_mask']
    surface_review = dict(method='single_row_unchanged',withheld_pixels=0,surfaces=[])
    uncertain_surfaces = np.zeros(mask.shape,bool)
    if len(parking_rows(observations)[0]) > 1:
        uncertain_surfaces,surface_review = covered_surface_review(image,observations)
        mask |= uncertain_surfaces
    result = analyze_mask(mask, observations)
    result['boundaries'].setdefault('legs', [])  # the station server reports a leg count; the automatic boundary has none
    overlay, ranking = render_overlay(image.shape[:2], result['ranked'], limit)
    overlay, ranking = annotate_gap_parts(overlay, result['ranked'], ranking)
    displayed = np.zeros(mask.shape, bool)
    for pocket in result['ranked'][:limit]:
        a,b,c,d = pocket['box']
        displayed[b:d,a:c] |= pocket['mask']
    overlay[~displayed] = 0
    overlay, ranking = draw_side_proposals(overlay, result['ranked'], ranking, result['boundary_mask'], mask)
    all_overlay, all_ranking = render_overlay(image.shape[:2], result['ranked'], len(result['ranked']))
    all_overlay, all_ranking = annotate_gap_parts(all_overlay, result['ranked'], all_ranking)
    all_overlay[~result['free_mask']] = 0
    all_overlay, all_ranking = draw_side_proposals(all_overlay, result['ranked'], all_ranking, result['boundary_mask'], mask)
    pair_reviews={tuple(p['instance_ids']):p['reason'] for p in result['side_review']['pair_reviews']}
    for row in ranking+all_ranking:
        pair=tuple(row['gap_instance_ids'])
        row['direction_status']='supported' if all(observations[i-1]['geometry']['status']=='supported' for i in pair) else 'uncertain'
        row['direction_review']=pair_reviews.get(pair,'area_only')
        row['selection_status']='top_five' if row['rank']<=limit else 'outside_top_five'
    result.update(mask=mask, overlay=overlay, ranking=ranking, all_overlay=all_overlay, all_ranking=all_ranking, instances=len(observations),
                  boundary_overlay=render_boundary(image.shape[:2], result['boundaries']),
                  instances_overlay=render_instances(image.shape[:2], observations), recognition=recognition,
                  measurement_status='review_needed' if recognition['review_count'] or result['side_review']['accepted_count'] else 'estimate',
                  display_limit=limit, ranking_metric=RANKING_METRIC, lighting_compensation=lighting,
                  merged_gap_count=sum(p.get('merged_across_overlap',False) for p in result['ranked']),
                  detections=instance_records(observations),
                  analysis_image=image, source_resolution_wh=source_size,
                  uncertain_surface_mask=uncertain_surfaces, occupancy_review=surface_review,
                  elapsed_ms=round((time.perf_counter()-started)*1000))
    return result

def save(path, image):
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('Cannot encode the result image.')
    encoded.tofile(str(path))

def export(image, result, out, source):
    image = result.get('analysis_image', image)
    out.mkdir(parents=True, exist_ok=True)
    save(out/'original.png', image)
    save(out/'binary.png', result['binary'])
    save(out/'bicycle_mask.png', result['mask'].astype(np.uint8)*255)
    save(out/'uncertain_surfaces.png', result['uncertain_surface_mask'].astype(np.uint8)*255)
    save(out/'top5_overlay.png', result['overlay'])
    save(out/'all_candidates_overlay.png', result['all_overlay'])
    save(out/'all_candidates_on_original.png', composite(image,result['all_overlay']))
    save(out/'automatic_boundary.png', result['boundary_overlay'])
    save(out/'bicycle_review.png', result['instances_overlay'])
    save(out/'review_on_original.png', composite(composite(image, result['instances_overlay']), result['boundary_overlay']))
    save(out/'boundary_mask.png', result['boundary_mask'].astype(np.uint8)*255)
    save(out/'candidate_visible_mask.png', result['free_mask'].astype(np.uint8)*255)
    save(out/'top5_on_original.png', composite(composite(image, result['overlay']), result['boundary_overlay']))
    records = [{k:v for k,v in p.items() if k!='mask'} for p in result['regions']]
    metadata = dict(source=str(Path(source).resolve()), instances=result['instances'],
        frame_size_wh=[image.shape[1],image.shape[0]], ranking=result['ranking'],all_ranking=result['all_ranking'],
        ranking_metric=RANKING_METRIC, all_regions=records, area_count=len(records),
        eligible_area_count=len(result['ranked']), displayed_count=len(result['ranking']),
        boundaries=result['boundaries'], elapsed_ms=result['elapsed_ms'],
        lighting_compensation=result['lighting_compensation'], merged_gap_count=result['merged_gap_count'],
        total_visible_area_px2=result['total_visible_area_px2'],
        grouping=result['grouping'],
        side_review=result['side_review'],
        detections=result['detections'], recognition=result['recognition'],measurement_status=result['measurement_status'],
        source_resolution_wh=result.get('source_resolution_wh',[image.shape[1],image.shape[0]]),
        occupancy_review=result['occupancy_review'],
        physical_area_calibrated=False, physical_fit_verified=False)
    (out/'results.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    with (out/'area_ranking.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.writer(handle)
        writer.writerow(['Rank','Region ID','Visible area (pixels squared)','Displayed'])
        for p in records:
            writer.writerow([p.get('rank',p['area_rank']),p['area_id'],p['area_px2'],p.get('rank',p['area_rank'])<=len(result['ranking'])])
    return metadata

def main():
    parser=argparse.ArgumentParser(description='Rank the five largest enclosed white areas.')
    parser.add_argument('input',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    image=cv2.imdecode(np.fromfile(str(args.input),np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Cannot read the input image.')
    cv2.setNumThreads(4)
    result=analyze_colour(image,BicycleSegmenter(ROOT/'models/yolov8s-seg.onnx', classes=(1,3)))
    data=export(image,result,args.out,args.input)
    print(json.dumps({k:data[k] for k in ['instances','area_count','displayed_count','ranking','elapsed_ms']}))

if __name__=='__main__':
    main()
