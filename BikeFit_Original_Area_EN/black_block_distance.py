"""Measure every lower-tip pair belonging to different black components.

No bicycle detector, silhouette merging, or anatomical wheel inference is used.
Multi-leg decisions are geometric and kept in the exported records.
"""
import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np


def lowest_pixel(mask):
    yy,xx = np.nonzero(mask)
    if not len(xx):
        raise ValueError('Cannot take the lowest pixel of an empty component')
    bottom = int(yy.max())
    xs = np.flatnonzero(mask[bottom])
    x = int(xs[np.argmin(np.abs(xs-np.median(xs)))])
    return [x,bottom]


def branch_tips(mask):
    """Look for substantial disconnected branches in the lower half.

    Scan cuts from 50% to 85% of height. A leg must contain at least 1% of
    the block area, extend 10% of height below the cut, and reach its bottom
    35% of height. Tips must be separated by at least 15% of block width.
    Prefer the earliest valid separation, preserving unequal-length legs.
    """
    h,w = mask.shape
    area = int(mask.sum())
    for cut in range(int(h*.50),max(int(h*.50)+1,int(h*.85)+1)):
        n,labels,stats,_ = cv2.connectedComponentsWithStats(mask[cut:].astype(np.uint8),8)
        tips = []
        for label in range(1,n):
            x,y,bw,bh,pixels = map(int,stats[label])
            if pixels < max(6,area*.01) or bh < max(3,h*.10):
                continue
            local = labels == label
            tip = lowest_pixel(local)
            tip[1] += cut
            if tip[1] < h*.65:
                continue
            tips.append(tip)
        tips.sort()
        if len(tips) >= 2 and tips[-1][0]-tips[0][0] >= max(4,w*.15):
            return tips,cut
    return [lowest_pixel(mask)],None


def analyze_black_blocks(image,min_area=None):
    grey = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    black = (grey < 128).astype(np.uint8)
    h,w = black.shape
    if min_area is None:
        min_area = max(20,round(h*w*.00002))
    n,labels,stats,_ = cv2.connectedComponentsWithStats(black,8)
    blocks,ignored = [],[]
    for label in range(1,n):
        x,y,bw,bh,pixels = map(int,stats[label])
        if pixels < min_area:
            ignored.append(dict(component_label=label,area_px=pixels,box=[x,y,x+bw,y+bh]))
            continue
        mask = labels[y:y+bh,x:x+bw] == label
        tips,cut = branch_tips(mask)
        global_tips = [[int(px+x),int(py+y)] for px,py in tips]
        low = lowest_pixel(mask)
        blocks.append(dict(component_label=label,box=[x,y,x+bw,y+bh],area_px=pixels,
            lowest_xy=[low[0]+x,low[1]+y],branch_tips_xy=global_tips,
            left_point_xy=global_tips[0],right_point_xy=global_tips[-1],
            multi_leg=len(tips)>1,branch_cut_y=None if cut is None else cut+y))
    blocks.sort(key=lambda b: ((b['box'][0]+b['box'][2])/2,b['box'][1],b['component_label']))
    for number,block in enumerate(blocks,1):
        block['block_id'] = number
    legs = []
    for block in blocks:
        for tip in block['branch_tips_xy']:
            legs.append(dict(block_id=block['block_id'],component_label=block['component_label'],point_xy=tip))
    legs.sort(key=lambda leg: (*leg['point_xy'],leg['block_id']))
    for number,leg in enumerate(legs,1):
        leg['leg_id'] = number
    distances,excluded = [],[]
    for i,left in enumerate(legs):
        for right in legs[i+1:]:
            if left['component_label'] == right['component_label']:
                excluded.append(dict(leg_ids=[left['leg_id'],right['leg_id']],
                    block_id=left['block_id'],reason='same_connected_black_component'))
                continue
            p,q = left['point_xy'],right['point_xy']
            distances.append(dict(gap_id=len(distances)+1,leg_ids=[left['leg_id'],right['leg_id']],
                block_ids=[left['block_id'],right['block_id']],endpoints_xy=[p,q],
                distance_px=round(math.dist(p,q),3),delta_x_px=q[0]-p[0],delta_y_px=q[1]-p[1]))
    # A readable overview shows only consecutive tips. The full matrix and CSV
    # contain every valid cross-component pair, with no missing long distances.
    lookup = {tuple(row['leg_ids']):row for row in distances}
    neighbours = [lookup[(left['leg_id'],right['leg_id'])] for left,right in zip(legs,legs[1:])
                  if left['component_label'] != right['component_label']]
    return dict(blocks=blocks,legs=legs,distances=distances,neighbour_distances=neighbours,
        excluded_same_component_pairs=excluded,ignored_small_components=ignored,
        minimum_component_area_px=min_area,connectivity=8,adjacency_axis='x',
        distance_unit='pixel',instance_grouping=False,physical_distance_calibrated=False,
        branch_rule='all_lower_branch_tips; single_tip_when_no_persistent_split',
        distance_rule='all_unordered_leg_pairs_except_same_connected_black_component')


def draw_result(image,result):
    grey = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    base = cv2.cvtColor(np.where(grey<128,0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR)
    h,w = base.shape[:2]
    rows = math.ceil(len(result['neighbour_distances'])/3)
    corrected = 'perspective_scale_correction' in result
    metric = 'corrected_distance_ref_px' if corrected else 'distance_px'
    unit = 'refpx' if corrected else 'px'
    output = np.full((h+90+rows*28,w,3),255,np.uint8)
    output[:h] = base

    def label(text,origin,colour=(35,35,35),scale=.48):
        (tw,th),_ = cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,scale,1)
        x = max(2,min(w-tw-3,int(origin[0])))
        y = max(th+4,min(output.shape[0]-5,int(origin[1])))
        cv2.rectangle(output,(x-2,y-th-3),(x+tw+2,y+3),(255,255,255),-1)
        cv2.putText(output,text,(x,y),cv2.FONT_HERSHEY_SIMPLEX,scale,colour,1,cv2.LINE_AA)

    for block in result['blocks']:
        a,b,c,d = block['box']
        label('B%d'%block['block_id'],((a+c)//2-10,b-12),scale=.6)
    for leg in result['legs']:
        point = leg['point_xy']
        colour = (200,95,20)
        cv2.circle(output,tuple(point),7,(255,255,255),-1,cv2.LINE_AA)
        cv2.circle(output,tuple(point),5,colour,-1,cv2.LINE_AA)
        label('P%d'%leg['leg_id'],(point[0]-10,point[1]-14),colour)
    for number,row in enumerate(result['neighbour_distances'],1):
        p,q = row['endpoints_xy']
        colour = (50,55,220)
        cv2.line(output,tuple(p),tuple(q),colour,2,cv2.LINE_AA)
        mx,my = (p[0]+q[0])/2,(p[1]+q[1])/2
        ty = min(h-8,round(my+38+24*(number%2)))
        cv2.line(output,(round(mx),round(my)),(round(mx),ty-13),colour,1,cv2.LINE_AA)
        label('%.1f%s'%(row[metric],unit),(round(mx)-25,ty),colour)
    label('Approximate local-scale correction only; reference pixels, NOT metres.' if corrected else
          'P = leg tip; B = connected black block. Tips in the SAME block are never measured.',(20,h+28),scale=.6)
    label('%d tips | %d valid pairs | %d same-block pairs excluded | Lines show adjacent valid pairs only.'%
          (len(result['legs']),len(result['distances']),len(result['excluded_same_component_pairs'])),(20,h+54),scale=.52)
    col_width = w//3
    for i,row in enumerate(result['neighbour_distances']):
        col,table_row = i%3,i//3
        text = 'P%d -> P%d : %.3f %s'%(*row['leg_ids'],row[metric],unit)
        label(text,(20+col*col_width,h+83+table_row*28),scale=.56)
    return output


def draw_distance_matrix(result):
    legs = result['legs']
    cell,left,top = 82,120,115
    n = len(legs)
    output = np.full((top+(n+1)*cell+80,left+(n+1)*cell+20,3),255,np.uint8)
    def text(message,x,y,scale=.48,colour=(35,35,35)):
        cv2.putText(output,message,(x,y),cv2.FONT_HERSHEY_SIMPLEX,scale,colour,1,cv2.LINE_AA)
    corrected = 'perspective_scale_correction' in result
    metric = 'corrected_distance_ref_px' if corrected else 'distance_px'
    text('APPROXIMATE SCALE-CORRECTED DISTANCES (reference pixels)' if corrected else
         'ALL LEG-TIP DISTANCES (pixels)',20,30,.65)
    text('SAME = same connected black block: excluded; - = self; values shown to 0.1 pixel',20,60,.52)
    lookup = {tuple(r['leg_ids']):r[metric] for r in result['distances']}
    for i,leg in enumerate(legs):
        x,y = left+i*cell,top+i*cell
        text('P%d'%leg['leg_id'],x+18,top-28,.55)
        text('B%d'%leg['block_id'],x+18,top-8,.42)
        text('P%d B%d'%(leg['leg_id'],leg['block_id']),8,y+cell//2,.48)
        for j,other in enumerate(legs):
            cx,cy = left+j*cell,top+i*cell
            same = leg['component_label'] == other['component_label']
            fill = (225,225,225) if same else (247,253,247)
            cv2.rectangle(output,(cx,cy),(cx+cell,cy+cell),fill,-1)
            cv2.rectangle(output,(cx,cy),(cx+cell,cy+cell),(195,195,195),1)
            value = '-' if i == j else ('SAME' if same else '%.1f'%lookup[tuple(sorted((leg['leg_id'],other['leg_id'])))])
            (tw,_),_ = cv2.getTextSize(value,cv2.FONT_HERSHEY_SIMPLEX,.43,1)
            text(value,cx+(cell-tw)//2,cy+cell//2+5,.43)
    text('%d unique valid pairs; %d within-block pairs excluded.'%
         (len(result['distances']),len(result['excluded_same_component_pairs'])),20,top+n*cell+40,.55)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'independent_leg_distances_20261028')
    args = parser.parse_args()
    image = cv2.imdecode(np.fromfile(str(args.input),np.uint8),cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError('Cannot read input image')
    result = analyze_black_blocks(image)
    # Geometry checks use the supplied image and do not rerun or tune analysis.
    for block in result['blocks']:
        for x,y in block['branch_tips_xy']:
            assert image[y,x] < 128
    leg_count = len(result['legs'])
    assert len(result['distances'])+len(result['excluded_same_component_pairs']) == leg_count*(leg_count-1)//2
    for row in result['distances']:
        assert row['block_ids'][0] != row['block_ids'][1]
        assert abs(math.dist(*row['endpoints_xy'])-row['distance_px']) <= .00051
    args.output.mkdir(parents=True,exist_ok=True)
    cv2.imencode('.png',draw_result(image,result))[1].tofile(str(args.output/'annotated.png'))
    cv2.imencode('.png',draw_distance_matrix(result))[1].tofile(str(args.output/'distance_matrix.png'))
    result['source'] = str(args.input.resolve())
    (args.output/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (args.output/'distances.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['编号','腿点1','腿点2','黑影1','黑影2','点1_X','点1_Y','点2_X','点2_Y','距离_像素'])
        for row in result['distances']:
            writer.writerow([row['gap_id'],*row['leg_ids'],*row['block_ids'],*row['endpoints_xy'][0],*row['endpoints_xy'][1],row['distance_px']])
    print(json.dumps(dict(blocks=len(result['blocks']),legs=leg_count,valid_pairs=len(result['distances']),
        excluded_same_component_pairs=len(result['excluded_same_component_pairs']),
        adjacent_valid_pairs=len(result['neighbour_distances']),
        ignored_small_components=len(result['ignored_small_components']))),flush=True)


if __name__ == '__main__':
    main()
