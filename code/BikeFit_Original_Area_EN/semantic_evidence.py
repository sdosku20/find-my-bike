"""Local YOLOv8s-seg image evidence, using the existing project's ONNX model.

Masks describe detected bicycle/person silhouettes, not physical clearance.
No empty camera image, image-specific labels, or network service is used.
"""
from pathlib import Path
import math
import json

import cv2
import numpy as np

from access_paths import horizontal_clearance


def attach_raw_review(records, raw_parking, raw_approach, row):
    """Keep raw obstructions on semantic proposals, never call them verified free.

    Rack-like detections remain obstacles. Raw conflicts change ranking and
    may withhold a hypothesis from the shortlist, without calling it full.
    """
    h,w=raw_parking.shape
    x0,y0,_,y1=row["parking_xyxy"]
    dense_profiles=cv2.GaussianBlur(raw_parking,(0,0),sigmaX=1.,sigmaY=.01)
    dense_widths=horizontal_clearance(dense_profiles)
    for record in records:
        axis=np.asarray(json.loads(record["axis_xy_json"]),np.float32)
        yy=np.clip(np.rint(axis[:,1]-y0).astype(int),0,h-1)
        radius=max(2,int(round(h*.015)))
        profiles=np.stack([raw_parking[max(0,y-radius):min(h,y+radius+1)].mean(axis=0) for y in yy])
        target=record["target_width_px_assumed"]
        profiles=cv2.GaussianBlur(profiles,(0,0),sigmaX=max(1.,target*.018),sigmaY=.01)
        widths=horizontal_clearance(profiles)
        xx=np.clip(np.rint(axis[:,0]-x0).astype(int),0,w-1)
        raw_width=widths[np.arange(len(xx)),xx]
        blocked=raw_width==0
        reversed_blocked=blocked[::-1]
        pairs=reversed_blocked[1:]&reversed_blocked[:-1]
        stop=int(pairs.argmax()+1) if pairs.any() else len(axis)
        approach_profile=cv2.GaussianBlur(raw_approach.mean(axis=0).reshape(1,-1),(0,0),sigmaX=max(1.,target*.04)).ravel()
        entry=int(np.clip(round(record["entry_x_px"]-x0),0,w-1))
        approach=float(approach_profile[entry])
        # Check every image row along the axis, not just the 24 search slices.
        # A narrow crossbar between search slices must survive this review.
        order=np.argsort(axis[:,1])
        dense_y=np.arange(int(np.ceil(axis[order[0],1])),int(np.floor(axis[order[-1],1]))+1)
        dense_x=np.interp(dense_y,axis[order,1],axis[order,0])-x0
        dy=np.clip(dense_y-y0,0,h-1)
        dx=np.clip(np.rint(dense_x).astype(int),0,w-1)
        dense_clear=dense_widths[dy,dx]
        dense_blocked=dense_clear==0
        from_entry=dense_blocked[::-1] if row["entry_edge"]=="bottom" else dense_blocked
        entry_clear_run=int(np.flatnonzero(from_entry)[0]) if from_entry.any() else len(from_entry)
        clear_depth=entry_clear_run/h
        half=min(target,record["sustained_width_px"])*.5
        corridor_occupancy=[]
        for py,px in zip(dy,dense_x):
            left=max(0,int(np.floor(px-half)))
            right=min(w,int(np.ceil(px+half))+1)
            corridor_occupancy.append(float((dense_profiles[py,left:right]>=.22).mean()))
        corridor_fraction=float(np.mean(corridor_occupancy))
        crossing=float(dense_blocked.mean())
        sustained=float(np.quantile(dense_clear,.25))
        a=max(0,int(np.floor(entry-half)))
        b=min(w,int(np.ceil(entry+half))+1)
        approach_corridor=float((raw_approach[:,a:b]>=.22).mean())
        conflict=bool(dense_blocked.any() or approach>=.2 or approach_corridor>=.15)
        record["axis_evidence_source"]="semantic_silhouette_proposal_with_independent_raw_review"
        record["semantic_status_before_raw_review"]=record["status"]
        record["raw_axis_crossing_fraction"]=round(float(blocked.mean()),4)
        record["raw_axis_minimum_width_px"]=round(float(raw_width.min()),2)
        record["raw_axis_sustained_width_px"]=round(float(np.quantile(raw_width,.25)),2)
        record["raw_visible_depth_fraction"]=round(float(stop/24),4)
        record["raw_approach_obstruction"]=round(approach,4)
        record["raw_structure_conflict"]=conflict
        record["raw_dense_axis_crossing_fraction"]=round(crossing,4)
        record["raw_dense_sustained_width_px"]=round(sustained,2)
        record["raw_entry_contiguous_depth_fraction"]=round(clear_depth,4)
        record["raw_corridor_occupied_fraction"]=round(corridor_fraction,4)
        record["raw_approach_corridor_occupied_fraction"]=round(approach_corridor,4)
        # Preserve the old proposal score for audit; independently observed
        # obstruction must affect which hypotheses are shown first.
        proposal=float(record["ranking_score"])
        raw_score=100*(.35*min(1.,sustained/target)+.40*min(1.,clear_depth)
                       +.15*(1-crossing)+.10*(1-max(approach,approach_corridor)))
        revised=max(0.,min(proposal,raw_score)-20*crossing-15*corridor_fraction)
        record["proposal_score_before_raw_review"]=proposal
        record["ranking_score"]=round(revised,3)
        record["raw_ranking_penalty"]=round(proposal-revised,3)
        record["uncertain_axis_xy_json"]=json.dumps(np.column_stack((dense_x[dense_blocked]+x0,dense_y[dense_blocked]))[::3].round(2).tolist())
        if conflict:
            record["status"]="partial_obstruction"
            record["limiting_stage"]="raw_structure_unresolved"
        # A semantic mask is not enough to declare an entirely undetected row
        # empty: raw review survives, including any unrecognised black object.
        record["review_required"]=conflict or record["status"]=="partial_obstruction"
        reasons=[]
        if sustained<target*.35:
            reasons.append("insufficient_raw_width")
        if clear_depth<.40:
            reasons.append("insufficient_contiguous_raw_depth")
        if crossing>.10 or corridor_fraction>.15:
            reasons.append("too_much_unresolved_structure")
        if approach>=.2 or approach_corridor>=.15:
            reasons.append("approach_obstruction")
        record["shortlist_eligible"]=not reasons
        record["shortlist_withheld_reasons"]=reasons
    return records


def separate_rack_like_components(mask, rows):
    """Move isolated, tall thin components without rear support to uncertainty.

    Not a rack classifier: small bikes parked deeper can also fail the support
    assumption. Their raw pixels MUST remain in the independent review layer.
    Broad child bikes, basket fragments and rear-supported tyres are retained.
    """
    retained=mask.copy()
    uncertain=np.zeros_like(mask)
    count,labels,stats,_=cv2.connectedComponentsWithStats((mask>0).astype(np.uint8))
    removed=[]
    for k in range(1,count):
        x,y,bw,bh,area=map(int,stats[k])
        for row in rows:
            x0,y0,x1,y1=row["parking_xyxy"]
            if not (x0<=x+bw/2<x1 and y0<=y+bh/2<y1):
                continue
            rh=y1-y0
            if row["entry_edge"]=="bottom":
                region=labels[int(round(y0+rh*.8)):y1,x:x+bw]
            else:
                region=labels[y0:int(round(y1-rh*.8)),x:x+bw]
            support=int((region==k).sum())
            thin=bh>rh*.2 and bw<rh*.25 and bh>1.8*bw
            if thin and support<max(6,area*.003):
                retained[labels==k]=0
                uncertain[labels==k]=255
                removed.append({"row":row["name"],"box":[x,y,x+bw,y+bh],"pixels":area,
                                "reason":"isolated_thin_without_rear_support; uncertain, not proven empty"})
            break
    return retained,uncertain,removed


class BicycleSegmenter:
    # COCO classes: person (kept for privacy blurring), bicycle and motorcycle; recognition uses only the two-wheelers.
    def __init__(self, model, confidence=.22, classes=(0, 1, 3)):
        self.model_path=Path(model)
        self.net = cv2.dnn.readNetFromONNX(str(model))
        self.confidence = confidence
        self.classes = tuple(classes)

    def infer(self, image):
        h, w = image.shape[:2]
        scale = min(640/w, 640/h)
        nw, nh = int(round(w*scale)), int(round(h*scale))
        dx, dy = (640-nw)//2, (640-nh)//2
        canvas = np.full((640, 640, 3), 114, np.uint8)
        canvas[dy:dy+nh, dx:dx+nw] = cv2.resize(image, (nw, nh))
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1/255, (640,640), swapRB=True))
        outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        pred = next(o for o in outputs if o.ndim == 3)[0].T
        proto = next(o for o in outputs if o.ndim == 4)[0]
        if pred.shape[1] != 116 or proto.shape[0] != 32:
            raise ValueError(f"Unsupported model output: {[o.shape for o in outputs]}")
        classes = pred[:,4:84].argmax(axis=1)
        scores = pred[np.arange(len(pred)), 4+classes]
        chosen = []
        for category in self.classes:
            indices = np.flatnonzero((classes == category) & (scores >= self.confidence))
            if not len(indices):
                continue
            boxes = [[float(cx-bw/2),float(cy-bh/2),float(bw),float(bh)] for cx,cy,bw,bh in pred[indices,:4]]
            picks = np.asarray(cv2.dnn.NMSBoxes(boxes, scores[indices].tolist(), self.confidence, .5)).reshape(-1)
            chosen.extend(indices[picks].tolist())
        ph,pw = proto.shape[1:]
        yy,xx = np.ogrid[:ph,:pw]
        result=[]
        for k in chosen:
            cx,cy,bw,bh = pred[k,:4]
            bx0,by0,bx1,by1 = cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2
            x0,y0 = max(0,int((bx0-dx)/scale)),max(0,int((by0-dy)/scale))
            x1,y1 = min(w,int(math.ceil((bx1-dx)/scale))),min(h,int(math.ceil((by1-dy)/scale)))
            if x1<=x0 or y1<=y0:
                continue
            logits = (pred[k,84:] @ proto.reshape(32,-1)).reshape(ph,pw)
            probability = 1/(1+np.exp(-np.clip(logits,-30,30)))
            probability *= (xx>=bx0/640*pw)&(xx<bx1/640*pw)&(yy>=by0/640*ph)&(yy<by1/640*ph)
            large = cv2.resize(probability,(640,640),interpolation=cv2.INTER_LINEAR)
            mask = cv2.resize(large[dy:dy+nh,dx:dx+nw],(w,h),interpolation=cv2.INTER_LINEAR)>.5
            result.append({"class":int(classes[k]),"confidence":float(scores[k]),"box":[x0,y0,x1,y1],"mask":mask})
        return result

    def evidence(self, frame, config):
        """Union full-frame and overlapping row tiles; keep small/reversed bikes.

        The detector has no bicycle-size rejection. A separate thin-component
        support filter moves rack-like fragments to uncertainty. Racks can
        still be classified as bicycles; all detections remain inspectable.
        """
        h,w = frame.shape[:2]
        bike = np.zeros((h,w),np.uint8)
        people = np.zeros((h,w),np.uint8)
        views=[(0,0,w,h)]
        if config.get('live_scale_adaptive'):
            # Square, overlapping views preserve distant-object detail even
            # when most of the whole frame is empty foreground/background.
            side=min(w,h,640) if config.get('live_detail_tiles') else min(w,h)
            nx=max(1,int(math.ceil((w-side)/(side*.65)))+1)
            ny=max(1,int(math.ceil((h-side)/(side*.65)))+1)
            for top in np.linspace(0,h-side,ny).astype(int):
                for left in np.linspace(0,w-side,nx).astype(int):
                    view=(int(left),int(top),int(left)+side,int(top)+side)
                    if view not in views:
                        views.append(view)
        for row in ([] if config.get('live_scale_adaptive') or config.get('single_instance_view') else config["rows"]):
            x0,y0,x1,y1 = row["parking_xyxy"]
            y0,y1=max(0,y0-40),min(h,y1+40)
            tile=min(x1-x0,640)
            count=max(1,int(math.ceil((x1-x0-tile)/(tile*.65)))+1)
            for left in np.linspace(x0,max(x0,x1-tile),count).astype(int):
                views.append((int(left),y0,min(x1,int(left)+tile),y1))
        detections=[]
        vehicle_supports=[]
        self.instance_observations=[]
        for x0,y0,x1,y1 in views:
            for item in self.infer(frame[y0:y1,x0:x1]):
                a,b,c,d=item["box"]
                if item["class"] == 1:
                    local=bike[y0:y1,x0:x1]
                    local[item["mask"]]=255
                    instance_id=len(self.instance_observations)
                    self.instance_observations.append({'instance_id':instance_id,
                        'box':[a+x0,b+y0,c+x0,d+y0],
                        'confidence':float(item['confidence']),
                        'mask':item['mask'][b:d,a:c].copy()})
                    # Preserve instance-level near-wheel evidence before the
                    # silhouette union merges adjacent bicycles together.
                    yy,xx=np.nonzero(item['mask'])
                    for row in config['rows']:
                        rx0,ry0,rx1,ry1=row['parking_xyxy']
                        if not (rx0<=(a+c)/2+x0<rx1 and ry0<=(b+d)/2+y0<ry1):
                            continue
                        minimum_height = max(16,h*.025) if config.get('live_scale_adaptive') else (ry1-ry0)*.3
                        if d-b < minimum_height:
                            break
                        bottom=row['entry_edge']=='bottom'
                        near=(yy>=b+.80*(d-b)) if bottom else (yy<=b+.20*(d-b))
                        mid=(yy>=b+.45*(d-b))&(yy<=b+.65*(d-b))
                        if near.sum()<12 or mid.sum()<12:
                            break
                        near_x=float(np.median(xx[near]))+x0
                        near_y=float(np.quantile(yy[near],.90 if bottom else .10))+y0
                        mid_x=float(np.median(xx[mid]))+x0
                        mid_y=float(np.median(yy[mid]))+y0
                        half=max(2.,float(np.quantile(np.abs(xx[near]+x0-near_x),.8)))
                        slope=float(np.clip((near_x-mid_x)/(near_y-mid_y),-.5,.5)) if abs(near_y-mid_y)>1 else 0.
                        vehicle_supports.append({'row':row['name'],'instance_id':instance_id,'near_x':round(near_x,2),
                            'near_y':round(near_y,2),'half_width':round(half,2),
                            'slope_dx_per_dy':round(slope,5),'confidence':round(item['confidence'],4),
                            'box':[a+x0,b+y0,c+x0,d+y0]})
                        break
                else:
                    # People occlude unknown ground, so keep their whole box.
                    people[y0+b:y0+d,x0+a:x0+c]=255
                detections.append({"class":item["class"],"confidence":round(item["confidence"],4),
                                   "box":[a+x0,b+y0,c+x0,d+y0]})
        self.raw_bicycle_mask=bike.copy()
        self.person_mask=people.copy()
        bike,uncertain,removed=separate_rack_like_components(bike,config["rows"])
        # Recover a small margin around thin parts; no large box filling.
        radius=max(2,round(w*.003))
        kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1))
        # A shape heuristic cannot erase a solid rack (or a small bicycle).
        # Retain uncertain components in obstacle evidence, with the same margin.
        supported=cv2.dilate(np.maximum(bike,uncertain),kernel)
        return np.maximum(supported,people).astype(np.float32)/255, {
            "model":"YOLOv8s-seg ONNX (existing local model)","confidence_threshold":self.confidence,
            "views":len(views),"detections_in_overlapping_views":detections,
            "vehicle_supports_in_overlapping_views":vehicle_supports,
            "uncertain_rack_like_components":removed,
            "rack_like_components_retained_as_obstacles":True,
            "mask_margin_px":radius,"person_occlusion_present":bool(people.any()),
            "physical_fit_verified":False}
