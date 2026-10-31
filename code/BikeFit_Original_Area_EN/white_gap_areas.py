"""Bounded white scanline gaps between neighbouring distinct black components.

The exterior white background is connected to many openings. Define each gap
by bounded horizontal white runs with two neighbouring black components as
banks, then split disconnected pockets. Do not count intra-component holes.
"""
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from black_shadow_center_distance import label


def bounded_white_gaps(image,blocks):
    n,components,stats,_ = cv2.connectedComponentsWithStats((image<128).astype(np.uint8),8)
    spatial = sorted(blocks,key=lambda b:(*b['center_xy'],b['block_id']))
    allowed = {}
    for number,(first,second) in enumerate(zip(spatial,spatial[1:]),1):
        key = tuple(sorted((first['component_label'],second['component_label'])))
        allowed[key] = dict(pair_number=number,block_ids=[first['block_id'],second['block_id']])
    owner = np.zeros(image.shape,np.int32)
    for y,row in enumerate(components):
        occupied = np.flatnonzero(row)
        for index in np.flatnonzero(np.diff(occupied)>1):
            left,right = int(occupied[index]),int(occupied[index+1])
            first,second = int(row[left]),int(row[right])
            if first == second:
                continue
            pair = allowed.get(tuple(sorted((first,second))))
            if pair:
                owner[y,left+1:right] = pair['pair_number']
    pockets = []
    for pair in allowed.values():
        count,labels,stats,centroids = cv2.connectedComponentsWithStats((owner==pair['pair_number']).astype(np.uint8),8)
        for component in range(1,count):
            x,y,w,h,area = map(int,stats[component])
            mask = labels[y:y+h,x:x+w] == component
            pockets.append(dict(block_ids=pair['block_ids'],pair_number=pair['pair_number'],
                box=[x,y,x+w,y+h],area_px2=area,center_xy=centroids[component].tolist(),mask=mask))
    pockets.sort(key=lambda p:(p['pair_number'],p['center_xy'][1],p['center_xy'][0]))
    for number,pocket in enumerate(pockets,1):
        pocket['gap_id'] = number
    return pockets


def area_scale_weights(width,scale):
    heights = np.interp(np.arange(width),scale['sample_x_px'],scale['sample_height_px'])
    return (scale['reference_height_px']/heights)**2


def draw(image,pockets,blocks):
    h,w = image.shape
    output = np.full((h+115+math.ceil(len(pockets)/3)*30,w,3),255,np.uint8)
    output[:h] = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
    palette = [(235,180,90),(110,200,245),(180,130,230),(140,220,145),(225,180,210)]
    for pocket in pockets:
        a,b,c,d = pocket['box']
        mask = pocket['mask']
        colour = palette[(pocket['gap_id']-1)%len(palette)]
        patch = output[b:d,a:c]
        patch[mask] = colour
        contours,_ = cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(output,contours,-1,tuple(max(0,v-70) for v in colour),1,offset=(a,b))
        # Put the gap number on an actual interior pixel, not outside a thin gap.
        distance = cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
        px,py = cv2.minMaxLoc(distance)[3]
        point = (px+a,py+b)
        cv2.circle(output,point,12,(250,250,250),-1,cv2.LINE_AA)
        label(output,str(pocket['gap_id']),(point[0]-5,point[1]+5),.48,background=False)
    for block in blocks:
        a,b,c,d = block['box']
        label(output,'B%d'%block['block_id'],((a+c)/2-10,b-15),.55)
    label(output,'COLOURED REGIONS = measured white gaps between adjacent distinct black shadows.',(20,h+28),.6)
    label(output,'Only white runs bounded by both shadows count; upper/lower exterior and same-shadow leg holes excluded.',(20,h+54),.5)
    label(output,'px2 = original image area; refpx2 = approximate local-scale-squared compensation (NOT square metres).',(20,h+80),.5)
    label(output,'%d separate white pockets. Total original area: %d px2.'%(len(pockets),sum(p['area_px2'] for p in pockets)),(20,h+106),.53)
    for i,pocket in enumerate(pockets):
        text = '#%d B%d-B%d: %d px2 / %.1f refpx2'%(pocket['gap_id'],*pocket['block_ids'],pocket['area_px2'],pocket['corrected_area_ref_px2'])
        label(output,text,(20+(i%3)*(w//3),h+136+(i//3)*30),.47)
    return output


def main():
    prior = json.loads((ROOT/'black_shadow_center_distances_20261028/results.json').read_text(encoding='utf-8'))
    image = cv2.imdecode(np.fromfile(str(ROOT/'bicycle_black_background_white_20261028.png'),np.uint8),0)
    blocks = prior['centers']
    pockets = bounded_white_gaps(image,blocks)
    weights = area_scale_weights(image.shape[1],prior['perspective_scale_correction'])
    ownership = np.zeros(image.shape,np.int32)
    for pocket in pockets:
        a,b,c,d = pocket['box']
        mask = pocket['mask']
        pocket['corrected_area_ref_px2'] = round(float(np.sum(mask*weights[a:c][None,:])),3)
        assert np.all(image[b:d,a:c][mask] >= 128)
        assert not np.any(ownership[b:d,a:c][mask])
        ownership[b:d,a:c][mask] = pocket['gap_id']
    assert np.count_nonzero(ownership) == sum(p['area_px2'] for p in pockets)
    out = ROOT/'white_gap_areas_20261028'
    out.mkdir(exist_ok=True)
    cv2.imencode('.png',draw(image,pockets,blocks))[1].tofile(str(out/'annotated.png'))
    records = []
    for pocket in pockets:
        a,b,c,d = pocket['box']
        mask = np.zeros(image.shape,np.uint8)
        mask[b:d,a:c][pocket['mask']] = 255
        mask_file = 'gap_%02d.png'%pocket['gap_id']
        cv2.imencode('.png',mask)[1].tofile(str(out/mask_file))
        records.append(dict({k:v for k,v in pocket.items() if k!='mask'},mask_file=mask_file))
    result = dict(gaps=records,gap_count=len(records),total_area_px2=sum(p['area_px2'] for p in records),
        area_definition='horizontal_white_runs_bounded_by_neighbouring_distinct_black_components; disconnected_pockets_separate',
        same_component_interleg_spaces_excluded=True,exterior_background_excluded=True,
        minimum_white_gap_area_px=1,ignored_small_black_components=prior['ignored_small_components'],
        perspective_scale_correction=prior['perspective_scale_correction'],physical_area_calibrated=False,
        limitation='Scanline boundaries define visible image gaps, not verified ground-plane parking area.')
    (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (out/'areas.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['间隔编号','黑影1','黑影2','原始面积_像素平方','尺度近似补偿面积_参考像素平方'])
        for pocket in records:
            writer.writerow([pocket['gap_id'],*pocket['block_ids'],pocket['area_px2'],pocket['corrected_area_ref_px2']])
    print(json.dumps(dict(gap_count=len(records),total_area_px2=result['total_area_px2'],gaps=[dict(id=p['gap_id'],blocks=p['block_ids'],area_px2=p['area_px2'],corrected_area_ref_px2=p['corrected_area_ref_px2']) for p in records])),flush=True)


if __name__ == '__main__':
    main()
