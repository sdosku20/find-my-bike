"""Whole-frame plus overlapping detail views, with inspectable instance masks.

This is an inference/review layer, not a trained accuracy guarantee. Mask
duplicates select one complete observation; distinct masks are never joined.
Unresolved extrema remain visible and make area measurements provisional.
"""
import math

import cv2
import numpy as np

PALETTE = [(85,210,255),(235,155,115),(130,220,130),(210,130,240),
           (240,210,90),(100,145,250),(210,210,120),(175,145,235)]
TWO_WHEEL_CLASSES = {1: 'bicycle', 3: 'motorcycle'}


def detail_views(shape, seeds):
    h,w = shape
    if max(h,w) <= 640:
        return []
    tw,th = min(w,768),min(h,768)
    nx = max(1,math.ceil((w-tw)/(tw*.65))+1)
    xs = sorted(set(int(round(v)) for v in np.linspace(0,w-tw,nx)))
    if seeds:
        # Prioritise detected row heights; the whole-frame pass is retained.
        centers = sorted((p['box'][1]+p['box'][3])/2 for p in seeds)
        groups = []
        for cy in centers:
            if not groups or cy-np.median(groups[-1]) > th*.55:
                groups.append([cy])
            else:
                groups[-1].append(cy)
        groups.sort(key=len,reverse=True)
        ys = sorted(set(int(np.clip(round(np.median(g)-th/2),0,h-th)) for g in groups[:2]))
    else:
        # Cover the entire frame within the view budget, rather than truncating
        # the bottom/right of an oversized grid.
        xs=sorted(set(int(round(v)) for v in np.linspace(0,w-tw,min(3,nx))))
        ny = max(1,math.ceil((h-th)/(th*.65))+1)
        ys = sorted(set(int(round(v)) for v in np.linspace(0,h-th,min(3,ny))))
    return [(x,y,x+tw,y+th) for y in ys for x in xs if (x,y,x+tw,y+th)!=(0,0,w,h)][:9]


def candidates_from_view(detector, image, view, view_id, kind, shape, exposure='original'):
    x0,y0,x1,y1 = view
    result = []
    for item in detector.infer(image[y0:y1,x0:x1]):
        if item['class'] not in TWO_WHEEL_CLASSES:
            continue
        mask = np.asarray(item['mask'],bool)
        if mask.shape != (y1-y0,x1-x0):
            raise ValueError('Bicycle mask must match the inference view.')
        yy,xx = np.nonzero(mask)
        if not len(xx):
            continue
        a,b,c,d = int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
        margin=max(2,round(min(x1-x0,y1-y0)*.025)) if kind=='source_detail' else 2
        edge_cut = ((x0>0 and a<margin) or (y0>0 and b<margin) or
                    (x1<shape[1] and c>x1-x0-margin) or (y1<shape[0] and d>y1-y0-margin))
        result.append(dict(box=[a+x0,b+y0,c+x0,d+y0], mask=mask[b:d,a:c].copy(),
                           **{'class': int(item['class'])},
                           confidence=float(item['confidence']), view_id=view_id, kind=kind,
                           exposure=exposure,
                           edge_cut=bool(edge_cut), area=int(len(xx)),
                           center_x=float(xx.mean()+x0)))
    return result


def overlap(first,second):
    a,b,c,d = first['box'];e,f,g,h = second['box']
    x0,y0,x1,y1 = max(a,e),max(b,f),min(c,g),min(d,h)
    if x1<=x0 or y1<=y0:
        return 0.,0.
    count = int(np.count_nonzero(first['mask'][y0-b:y1-b,x0-a:x1-a] &
                                 second['mask'][y0-f:y1-f,x0-e:x1-e]))
    small = min(first['area'],second['area'])
    return count/max(1,first['area']+second['area']-count),count/max(1,small)


def same_instance(first,second):
    iou,ios = overlap(first,second)
    ratio = min(first['area'],second['area'])/max(first['area'],second['area'])
    return iou>=.48 or (ios>=.78 and ratio>=.42)


def fuse_candidates(candidates):
    """Select masks, never union instance identities or bridge them by boxes."""
    complete = [p for p in candidates if not p['edge_cut']]
    # Detail masks receive a small preference, never an unconditional override.
    complete.sort(key=lambda p:(p['confidence']+(.07 if p['kind']!='whole' else 0),p['area']),reverse=True)
    groups = []
    suppressed = 0
    for candidate in complete:
        matches = [(overlap(candidate,g['selected'])[0],g) for g in groups
                   if same_instance(candidate,g['selected'])]
        if matches:
            group = max(matches,key=lambda p:p[0])[1]
            # Independent views support identity; two detections in one view
            # cannot manufacture corroboration.
            group['alternatives'].append(candidate)
            suppressed += 1
            continue
        if candidate['kind']=='whole':
            covered = [g for g in groups if overlap(candidate,g['selected'])[1]>=.65]
            if len(covered)>1:
                # A broad coarse mask covering several detailed instances is
                # not counted as an additional bicycle.
                suppressed += 1
                for group in covered:
                    group['coarse_conflict'] = True
                continue
        groups.append(dict(selected=candidate,alternatives=[],coarse_conflict=False))
    # A coarse mask can win on confidence first. Replace it only when several
    # separate, complete detail masks cover it without matching each other.
    result = []
    for group in groups:
        chosen = group['selected']
        if chosen['kind']=='whole':
            details = [p for p in complete if p['kind']!='whole' and
                       overlap(chosen,p)[1]>=.78 and p['area']<chosen['area']*.75]
            distinct = []
            for item in details:
                if not any(same_instance(item,q) for q in distinct):
                    distinct.append(item)
            if len(distinct)>1:
                for item in distinct:
                    if not any(same_instance(item,g['selected']) for g in result+groups if g is not group):
                        result.append(dict(selected=item,alternatives=[],coarse_conflict=True))
                suppressed += 1
                continue
        result.append(group)
    # A small wheel/fork patch contained in an existing silhouette must not
    # become an extra bicycle or an extra y-extrema anchor.
    final=[]
    for group in sorted(result,key=lambda g:g['selected']['area'],reverse=True):
        p=group['selected'];height=p['box'][3]-p['box'][1]
        parent=next((g for g in final if p['area']<g['selected']['area']*.3 and
                     height<(g['selected']['box'][3]-g['selected']['box'][1])*.65 and
                     overlap(p,g['selected'])[1]>=.85),None)
        if parent is not None:
            parent['alternatives'].extend([p]+group['alternatives'])
            parent['partial_conflict']=True;suppressed+=1
        else:
            final.append(group)
    return final,dict(raw_candidates=len(candidates),clipped_tile_candidates=sum(p['edge_cut'] for p in candidates),
                       suppressed_duplicates_or_coarse_conflicts=suppressed)


def extrema(candidate):
    a,b,_,_ = candidate['box']
    yy,xx = np.nonzero(candidate['mask'])
    top,bottom = int(yy.min()),int(yy.max())
    tx,bx = np.sort(xx[yy==top]),np.sort(xx[yy==bottom])
    return [int(tx[len(tx)//2]+a),top+b],[int(bx[len(bx)//2]+a),bottom+b]


def review_flags(group,shape):
    candidate = group['selected'];mask = candidate['mask'];a,b,c,d = candidate['box']
    flags = []
    if candidate['confidence']<.35:
        flags.append('low_model_score')
    if a==0 or b==0 or c==shape[1] or d==shape[0]:
        flags.append('image_edge_cut')
    yy,xx = np.nonzero(mask);height=max(1,d-b)
    for name,gap in (('top',float(np.quantile(yy,.05)-yy.min())),
                     ('bottom',float(yy.max()-np.quantile(yy,.95)))):
        if gap>max(8,height*.18):
            flags.append(name+'_thin_extension')
    count,labels,stats,_ = cv2.connectedComponentsWithStats(mask.astype(np.uint8),connectivity=8)
    top,bottom = extrema(candidate)
    for name,(x,y) in (('top',top),('bottom',bottom)):
        label = int(labels[y-b,x-a])
        if count>2 and stats[label,cv2.CC_STAT_AREA] < max(4,candidate['area']*.03):
            flags.append(name+'_detached_fragment')
    independent = [p for p in group['alternatives'] if p['view_id']!=candidate['view_id']]
    if independent:
        tolerance=max(8,height*.12)
        if any(abs(extrema(p)[0][1]-top[1])>tolerance or
               abs(extrema(p)[1][1]-bottom[1])>tolerance for p in independent):
            flags.append('views_disagree_on_extrema')
    if group.get('coarse_conflict'):
        flags.append('overlapping_bicycles_ambiguous')
    if group.get('partial_conflict'):
        flags.append('partial_instance_ambiguous')
    return sorted(set(flags))


def source_detail_candidates(detector, source, shape, seeds, view_start):
    """Inspect distant vehicles before downsampling; map masks to output pixels."""
    sh,sw=source.shape[:2];h,w=shape
    if max(sh,sw)<=max(h,w) or not seeds:
        return [],np.zeros(shape,bool),[]
    sx,sy=sw/w,sh/h
    side=min(896,sh,sw)
    top=float(np.quantile([p['box'][1]*sy for p in seeds],.03))
    y0=int(np.clip(round(top-side*.18),0,sh-side))
    nx=max(1,int(math.ceil((sw-side)/(side*.65)))+1)
    xs=sorted(set(int(round(x)) for x in np.linspace(0,sw-side,min(9,nx))))
    result=[];partial=np.zeros(shape,bool);views=[]
    for index,x0 in enumerate(xs,view_start):
        view=(x0,y0,x0+side,y0+side);views.append(list(view))
        for p in candidates_from_view(detector,source,view,index,'source_detail',(sh,sw)):
            a,b,c,d=p['box']
            e,f=int(np.floor(a/sx)),int(np.floor(b/sy))
            g,k=min(w,int(np.ceil(c/sx))),min(h,int(np.ceil(d/sy)))
            if g<=e or k<=f:continue
            mask=cv2.resize(p['mask'].astype(np.uint8),(g-e,k-f),interpolation=cv2.INTER_NEAREST)>0
            yy,xx=np.nonzero(mask)
            if not len(xx):continue
            partial[f:k,e:g] |= mask
            result.append(dict(p,box=[e,f,g,k],mask=mask,area=int(mask.sum()),
                               center_x=float(xx.mean()+e)))
    return result,partial,views


def sparse_scene_supported(seeds,shape):
    """A conservative speed gate, confirmed again after normal detail views.

    Few detections alone are insufficient: require strong scores, substantial
    silhouettes, a common contact band, and little instance overlap. Empty,
    dark/weak, small, overlapping and multi-depth scenes keep full inference.
    """
    if max(shape)<=640 or not 2<=len(seeds)<=6:
        return False
    heights=np.array([p['box'][3]-p['box'][1] for p in seeds],float)
    bottoms=np.array([p['box'][3] for p in seeds],float)
    if (min(p['confidence'] for p in seeds)<.60 or heights.min()<shape[0]*.08
            or heights.max()/max(1,heights.min())>1.65
            or np.ptp(bottoms)>np.median(heights)*.35):
        return False
    return all(overlap(first,second)[1]<.15 for i,first in enumerate(seeds) for second in seeds[i+1:])


def recognise_bicycles(prepared, original, detector, detail_source=None):
    shape = prepared.shape[:2];h,w=shape
    seeds = candidates_from_view(detector,original,(0,0,w,h),0,'whole',shape)
    candidates = list(seeds);views=detail_views(shape,seeds)
    for index,view in enumerate(views,1):
        candidates.extend(candidates_from_view(detector,original,view,index,'detail',shape))
    sparse=sparse_scene_supported(seeds,shape)
    if sparse:
        provisional,_=fuse_candidates(candidates)
        # Details must corroborate the main instances. An edge-cut vehicle is
        # retained as occupancy but cannot demand an impossible off-image crop.
        internal=[g for g in provisional if 'image_edge_cut' not in review_flags(g,shape)]
        sparse=(len(internal)==len(seeds) and len(provisional)<=len(seeds)+1
                and all(g['selected']['confidence']>=.60 for g in internal)
                and all(any(q['kind']=='detail' and not q['edge_cut'] for q in [g['selected']]+g['alternatives']) for g in internal)
                and not any(set(review_flags(g,shape)) & {'views_disagree_on_extrema','overlapping_bicycles_ambiguous','partial_instance_ambiguous','top_detached_fragment','bottom_detached_fragment'} for g in internal))
    exposure_views=0
    if not sparse and not np.array_equal(prepared,original):
        # Compare exposures at identical scales/coordinates. Never replace the
        # whole image with an enhanced version before seeing the original.
        for view,kind in [((0,0,w,h),'whole')]+[(v,'detail') for v in views[:2]]:
            exposure_views+=1
            candidates.extend(candidates_from_view(detector,prepared,view,len(views)+exposure_views,kind,shape,'lifted'))
    source_views=[];source_obstacles=np.zeros(shape,bool)
    if detail_source is not None and not sparse:
        details,source_obstacles,source_views=source_detail_candidates(
            detector,detail_source,shape,candidates,len(views)+exposure_views+10)
        candidates.extend(details)
    groups,stats = fuse_candidates(candidates)
    retries = 0
    for group in sorted(groups,key=lambda g:g['selected']['confidence']):
        flags=review_flags(group,shape)
        if sparse:
            # Strong, corroborated silhouettes keep their recorded thin extrema.
            # Neither a handlebar nor an image-edge cut justifies another pass.
            severe=set(flags)&{'low_model_score','top_detached_fragment','bottom_detached_fragment','views_disagree_on_extrema'}
            if not severe or 'image_edge_cut' in flags:
                continue
        if not flags or retries>=2 or max(shape)<=640:
            continue
        old=group['selected'];a,b,c,d=old['box'];pad=max(24,round(max(c-a,d-b)*.3))
        view=(max(0,a-pad),max(0,b-pad),min(w,c+pad),min(h,d+pad))
        retries+=1
        local=candidates_from_view(detector,original,view,len(views)+exposure_views+retries,'retry',shape)
        matches=[p for p in local if not p['edge_cut'] and same_instance(p,old)]
        if not matches:
            group['retry_unconfirmed']=True
            continue
        replacement=max(matches,key=lambda p:p['confidence'])
        # A retry is evidence, not permission to erase an inconvenient extreme.
        trial=dict(selected=replacement,alternatives=[old]+group['alternatives'],
                   coarse_conflict=group.get('coarse_conflict',False),
                   partial_conflict=group.get('partial_conflict',False))
        if replacement['confidence']>=.35 and len(review_flags(trial,shape))<len(flags):
            group.update(trial)
        else:
            group['alternatives'].append(replacement)
        group['retry_completed']=True
    groups.sort(key=lambda g:(g['selected']['center_x'],g['selected']['box'][1]))
    observations=[]
    typical_height=float(np.median([g['selected']['box'][3]-g['selected']['box'][1] for g in groups])) if groups else 0
    typical_area=float(np.median([g['selected']['area'] for g in groups])) if groups else 0
    for number,group in enumerate(groups,1):
        p=group['selected'];a,b,c,d=p['box'];mask=np.zeros(shape,bool);mask[b:d,a:c]=p['mask']
        flags=review_flags(group,shape)
        exposures={q.get('exposure','original') for q in [p]+group['alternatives']}
        original_support=any(q.get('exposure','original')=='original' for q in [p]+group['alternatives'])
        exposure_conflict=any(q.get('exposure','original')!=p.get('exposure','original') and overlap(p,q)[0]<.65 for q in group['alternatives'])
        if exposure_conflict:
            flags.append('lighting_views_disagree')
        if not original_support:
            flags.append('enhanced_only_detection')
        if group.get('retry_unconfirmed'):
            flags.append('local_recheck_unconfirmed')
        high_resolution_support=any(q['kind']=='source_detail' and not q['edge_cut']
                                    for q in [p]+group['alternatives'])
        if d-b<typical_height*.45 and p['area']<typical_area*.15 and not high_resolution_support:
            flags.append('small_fragment_not_boundary_anchor')
        obstacle=mask.copy()
        for alternate in group['alternatives']:
            e,f,g,h1=alternate['box'];obstacle[f:h1,e:g] |= alternate['mask']
        observations.append(dict(mask=mask,obstacle_mask=obstacle,box=p['box'],confidence=p['confidence'],**{'class':p.get('class',1)},
                                 bicycle_id=number,review_flags=flags,needs_review=bool(flags),
                                 boundary_eligible='small_fragment_not_boundary_anchor' not in flags and (original_support or p['confidence']>=.5),
                                 exposure=p.get('exposure','original'),exposure_agreement=len(exposures)>1 and not exposure_conflict,
                                 top_xy=extrema(p)[0],bottom_xy=extrema(p)[1],
                                 supporting_views=len({q['view_id'] for q in [p]+group['alternatives']}),
                                 source=p['kind'],local_recheck=bool(group.get('retry_completed') or group.get('retry_unconfirmed'))))
    if observations and source_views:
        # Partial tiled silhouettes remain occupancy evidence, never extra IDs.
        observations[0]['scene_obstacle_mask'] = source_obstacles
    stats.update(method='whole_frame_plus_overlapping_detail_views',whole_frame_count=len(seeds),
                 detail_views=[list(p) for p in views],inference_views=1+len(views)+exposure_views+retries+len(source_views),
                 exposure_comparison_views=exposure_views,exposure_policy='original_plus_bounded_luminance_comparison',
                 local_rechecks=retries,review_count=sum(p['needs_review'] for p in observations),
                 accepted_vehicle_classes=TWO_WHEEL_CLASSES, accuracy_verified=False,
                 source_detail_views=source_views,source_detail_inference_count=len(source_views),
                 processing_mode='sparse_confirmed' if sparse else 'full_review',
                 adaptive_skip_reason='strong_single_row_confirmed_by_detail_views' if sparse else None,
                 source_resolution_wh=list(detail_source.shape[1::-1]) if detail_source is not None else [w,h])
    return observations,stats


def instance_records(observations):
    return [dict(bicycle_id=p['bicycle_id'],box=p['box'],confidence=p['confidence'],
                 class_id=p.get('class',1),class_name=TWO_WHEEL_CLASSES[p.get('class',1)],
                 exposure=p.get('exposure','original'),exposure_agreement=p.get('exposure_agreement',False),
                 geometry=p.get('geometry',dict(status='uncertain',reason='not_evaluated')),
                 top_xy=p['top_xy'],bottom_xy=p['bottom_xy'],review_flags=p['review_flags'],
                 needs_review=p['needs_review'],supporting_views=p['supporting_views'],
                 source=p['source'],local_recheck=p['local_recheck'],boundary_eligible=p['boundary_eligible'],
                 color='#%02x%02x%02x'%PALETTE[(p['bicycle_id']-1)%len(PALETTE)][::-1]) for p in observations]


def render_instances(shape,observations):
    overlay=np.zeros((*shape,4),np.uint8)
    for p in observations:
        colour=PALETTE[(p['bicycle_id']-1)%len(PALETTE)];mask=p['mask']
        overlay[mask]=(*colour,65)
        contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay,contours,-1,(*colour,255),1)
        x,y=p['top_xy'];text='B'+str(p['bicycle_id'])+(' ?' if p['needs_review'] else '')
        scale=max(.4,min(1.,shape[1]/1400));(tw,th),_=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,scale,1)
        x=int(np.clip(x-tw//2,0,max(0,shape[1]-tw-6)));y=int(np.clip(y-8,th+6,shape[0]-1))
        cv2.rectangle(overlay,(x,y-th-5),(x+tw+5,y+3),(25,35,30,240),-1)
        cv2.putText(overlay,text,(x+2,y),cv2.FONT_HERSHEY_SIMPLEX,scale,(*colour,255),1,cv2.LINE_AA)
    return overlay
