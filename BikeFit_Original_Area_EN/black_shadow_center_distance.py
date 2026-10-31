"""Black-component centroids and all pairwise image/relative-scale distances."""
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from recalculate_leg_perspective import corrected_distance


def shadow_centers(image,min_area):
    grey = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    n,labels,stats,centroids = cv2.connectedComponentsWithStats((grey<128).astype(np.uint8),8)
    centers = []
    for label in range(1,n):
        x,y,w,h,area = map(int,stats[label])
        if area < min_area:
            continue
        centers.append(dict(component_label=label,box=[x,y,x+w,y+h],area_px=area,
            center_xy=centroids[label].tolist(),center_definition='mean_xy_of_all_black_pixels_in_component'))
    centers.sort(key=lambda b: ((b['box'][0]+b['box'][2])/2,b['box'][1],b['component_label']))
    for number,center in enumerate(centers,1):
        center['block_id'] = number
    return centers


def pair_distances(centers,scale):
    rows = []
    for i,first in enumerate(centers):
        for second in centers[i+1:]:
            p,q = first['center_xy'],second['center_xy']
            raw = math.dist(p,q)
            adjusted = corrected_distance(p,q,scale['sample_x_px'],scale['sample_height_px'],scale['reference_height_px'])
            rows.append(dict(pair_id=len(rows)+1,block_ids=[first['block_id'],second['block_id']],
                endpoints_xy=[p,q],distance_px=round(raw,3),corrected_distance_ref_px=round(adjusted,3)))
    return rows


def label(image,text,origin,scale=.52,colour=(30,30,30),background=True):
    (tw,th),_ = cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,scale,1)
    h,w = image.shape[:2]
    x,y = max(2,min(w-tw-3,round(origin[0]))),max(th+4,min(h-5,round(origin[1])))
    if background:
        cv2.rectangle(image,(x-2,y-th-3),(x+tw+2,y+3),(255,255,255),-1)
    cv2.putText(image,text,(x,y),cv2.FONT_HERSHEY_SIMPLEX,scale,colour,1,cv2.LINE_AA)


def overview(image,result):
    h,w = image.shape[:2]
    neighbors = result['neighbour_distances']
    output = np.full((h+100+math.ceil(len(neighbors)/3)*30,w,3),255,np.uint8)
    output[:h] = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
    for number,row in enumerate(neighbors,1):
        p,q = row['endpoints_xy']
        pi,qi = tuple(round(v) for v in p),tuple(round(v) for v in q)
        cv2.line(output,pi,qi,(40,55,235),2,cv2.LINE_AA)
        mx,my = (p[0]+q[0])/2,(p[1]+q[1])/2
        ty = min(h-10,round(max(p[1],q[1])+140+28*(number%2)))
        cv2.line(output,(round(mx),round(my)),(round(mx),ty-16),(40,55,235),1,cv2.LINE_AA)
        label(output,'%.1f refpx'%row['corrected_distance_ref_px'],(mx-38,ty),.5,(40,55,220))
    for center in result['centers']:
        x,y = (round(v) for v in center['center_xy'])
        cv2.circle(output,(x,y),8,(255,255,255),-1,cv2.LINE_AA)
        cv2.circle(output,(x,y),5,(235,110,20),-1,cv2.LINE_AA)
        a,b,c,d = center['box']
        label(output,'B%d'%center['block_id'],((a+c)/2-10,b-15),.6)
    label(output,'Center = centroid (mean position of all black pixels), one center per connected shadow.',(20,h+28),.58)
    label(output,'Lines: adjacent centers only. All %d pairs are in the matrix and CSV.'%len(result['distances']),(20,h+54),.54)
    label(output,'refpx = approximate local-scale compensation; NOT a calibrated ground-plane distance.',(20,h+80),.54)
    for i,row in enumerate(neighbors):
        text = 'B%d - B%d: %.3f refpx (raw %.3f px)'%(*row['block_ids'],row['corrected_distance_ref_px'],row['distance_px'])
        label(output,text,(20+(i%3)*(w//3),h+109+(i//3)*30),.5)
    return output


def matrix_image(result,title='BLACK-SHADOW CENTROID DISTANCES'):
    n = len(result['centers'])
    cell,left,top = 91,90,110
    image = np.full((top+n*cell+80,left+n*cell+20,3),255,np.uint8)
    label(image,title, (20,28),.7)
    label(image,'Approximate scale compensation, reference pixels (not metres)',(20,57),.5)
    values = {tuple(r['block_ids']):r['corrected_distance_ref_px'] for r in result['distances']}
    for i in range(n):
        label(image,'B%d'%(i+1),(left+i*cell+25,top-15),.55)
        label(image,'B%d'%(i+1),(15,top+i*cell+cell//2+5),.55)
        for j in range(n):
            x,y = left+j*cell,top+i*cell
            cv2.rectangle(image,(x,y),(x+cell,y+cell),(225,225,225) if i == j else (247,253,247),-1)
            cv2.rectangle(image,(x,y),(x+cell,y+cell),(190,190,190),1)
            value = '-' if i == j else '%.1f'%values[tuple(sorted((i+1,j+1)))]
            (tw,_),_ = cv2.getTextSize(value,cv2.FONT_HERSHEY_SIMPLEX,.46,1)
            label(image,value,(x+(cell-tw)//2,y+cell//2+5),.46,background=False)
    label(image,'%d independent shadows, %d unique pairs.'%(n,len(result['distances'])),(20,top+n*cell+40),.55)
    return image


def main():
    prior_path = ROOT/'independent_leg_perspective_20261028/results.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    image = cv2.imdecode(np.fromfile(str(ROOT/'bicycle_black_background_white_20261028.png'),np.uint8),0)
    centers = shadow_centers(image,prior['minimum_component_area_px'])
    assert [(c['component_label'],c['box'],c['area_px']) for c in centers] == [(b['component_label'],b['box'],b['area_px']) for b in prior['blocks']]
    scale = prior['perspective_scale_correction']
    rows = pair_distances(centers,scale)
    by_ids = {tuple(row['block_ids']):row for row in rows}
    spatial = sorted(centers,key=lambda c: (*c['center_xy'],c['block_id']))
    neighbors = [by_ids[tuple(sorted((a['block_id'],b['block_id']))) ] for a,b in zip(spatial,spatial[1:])]
    assert len(rows) == len(centers)*(len(centers)-1)//2
    result = dict(centers=centers,distances=rows,neighbour_distances=neighbors,
        minimum_component_area_px=prior['minimum_component_area_px'],
        ignored_small_components=prior['ignored_small_components'],connectivity=8,
        center_definition='black_pixel_area_centroid',perspective_scale_correction=scale,
        ground_plane_rectified=False,physical_distance_calibrated=False,
        limitation='Image centroids are not wheel ground-contact points. Correction is an approximate local image-scale proxy only.')
    out = ROOT/'black_shadow_center_distances_20261028'
    out.mkdir(exist_ok=True)
    cv2.imencode('.png',overview(image,result))[1].tofile(str(out/'annotated.png'))
    cv2.imencode('.png',matrix_image(result))[1].tofile(str(out/'distance_matrix.png'))
    (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (out/'distances.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['编号','黑影1','黑影2','中心1_X','中心1_Y','中心2_X','中心2_Y','原始距离_像素','尺度近似修正距离_参考像素'])
        for row in rows:
            writer.writerow([row['pair_id'],*row['block_ids'],*row['endpoints_xy'][0],*row['endpoints_xy'][1],row['distance_px'],row['corrected_distance_ref_px']])
    print(json.dumps(dict(shadows=len(centers),pairs=len(rows),neighbors=neighbors)),flush=True)


if __name__ == '__main__':
    main()
