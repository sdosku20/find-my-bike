"""20/60/20 trial: image-space frame alignment supplements visible areas.

Wheel rim/contact hypotheses support directions; uncertain silhouettes cannot
authorise inference. Ground geometry remains uncalibrated. Proposals keep evidence;
only observed free pixels contribute to area. No hidden pixels are filled.
"""
import math

import cv2
import numpy as np

SIDE_FRACTION = .20
TRANSITION_FRACTION = .05  # Shared checks around the fixed 20% borders; measured central areas stay intact.
RANKING_METRIC = 'middle_visible_area_side20_frame_alignment_trial'


def row_zones(observations, boundary):
    anchors = boundary.get('ordered_instance_ids', [])
    boxes = [observations[i-1]['box'] for i in anchors]
    if len(boxes) < 2:
        return None
    left = float(min(b[0] for b in boxes)); right = float(max(b[2] for b in boxes))
    width = right-left
    return dict(left_x=left, right_x=right, left_cut_x=left+SIDE_FRACTION*width,
                right_cut_x=right-SIDE_FRACTION*width, side_fraction=SIDE_FRACTION,
                middle_fraction=1-2*SIDE_FRACTION,
                transition_fraction=TRANSITION_FRACTION, span_source='detected_row_extent')


def side_weight(x, zones):
    p = (x-zones['left_x'])/max(1., zones['right_x']-zones['left_x'])
    edge_distance = min(p, 1-p)
    if edge_distance >= SIDE_FRACTION+TRANSITION_FRACTION-1e-12:
        return 0.
    return float(np.clip((SIDE_FRACTION+TRANSITION_FRACTION-edge_distance)/TRANSITION_FRACTION, 0., 1.))


def frame_alignment(observation):
    """Use supported image landmarks; never infer direction from a mask centroid."""
    geometry=observation.get('geometry',{})
    if geometry.get('status')!='supported' or not observation.get('boundary_eligible',True):
        return None
    if 'image_edge_cut' in observation.get('review_flags',[]): return None
    return geometry


def pair_proposal(pair, observations, axes, zones, occupied, scope):
    first,second=pair;left,right=axes.get(first),axes.get(second)
    evidence=dict(instance_ids=list(pair),accepted=False)
    if left is None or right is None:
        return None,dict(evidence,reason='supported_direction_unavailable')
    height=min(left['height'],right['height'])
    if max(left['height'],right['height'])/height>1.55:
        return None,dict(evidence,reason='different_depth_or_partial_vehicle')
    p0,p1=np.asarray(left['near_xy']),np.asarray(left['far_xy'])
    q0,q1=np.asarray(right['near_xy']),np.asarray(right['far_xy'])
    center=float(np.mean([p0[0],p1[0],q0[0],q1[0]]));weight=side_weight(center,zones)
    if weight<=0: return None,dict(evidence,reason='middle_area_only')
    u=(p1-p0)/max(1.,np.linalg.norm(p1-p0));v=(q1-q0)/max(1.,np.linalg.norm(q1-q0))
    if np.dot(u,v)<0:v=-v
    angle=math.degrees(math.acos(float(np.clip(np.dot(u,v),-1,1))))
    if angle>18:
        return None,dict(evidence,reason='supported_directions_disagree',angle_difference_deg=angle)
    direction=u+v;direction/=max(1e-9,np.linalg.norm(direction))
    normal=np.array([-direction[1],direction[0]])
    if normal[0]<0:normal=-normal
    ls=sorted([float(p0@direction),float(p1@direction)])
    rs=sorted([float(q0@direction),float(q1@direction)])
    start=max(ls[0],rs[0]);end=min(ls[1],rs[1])
    if end-start<.45*min(ls[1]-ls[0],rs[1]-rs[0]):
        return None,dict(evidence,reason='different_row_depth')
    ln=float(((p0+p1)/2)@normal)+height*.08
    rn=float(((q0+q1)/2)@normal)-height*.08
    clearance=rn-ln
    if clearance<height*.16:
        return None,dict(evidence,reason='supported_spacing_too_narrow')
    polygon=[(direction*t+normal*n).tolist() for t,n in [(start,ln),(start,rn),(end,rn),(end,ln)]]
    proposal=np.zeros(occupied.shape,np.uint8)
    cv2.fillPoly(proposal,[np.rint(polygon).astype(np.int32)],1)
    side='left' if center<(zones['left_x']+zones['right_x'])/2 else 'right'
    xx=np.arange(occupied.shape[1])[None,:];width=zones['right_x']-zones['left_x']
    cut=zones['left_cut_x']+TRANSITION_FRACTION*width if side=='left' else zones['right_cut_x']-TRANSITION_FRACTION*width
    zone=(xx<cut) if side=='left' else (xx>=cut)
    proposal=(proposal>0)&scope&zone
    if proposal.sum()<10:return None,dict(evidence,reason='proposal_outside_side_scope')
    for number,obs in enumerate(observations,1):
        if number in pair:continue
        hits=int(np.count_nonzero(proposal&obs.get('obstacle_mask',obs['mask'])))
        if hits>=max(3,int(proposal.sum()*.005)):
            return None,dict(evidence,reason='third_vehicle_inside_corridor',blocking_instance_id=number)
    quality=min(left['quality'],right['quality'])*(1-angle/36)
    evidence.update(accepted=True,reason='supported_wheel_direction_and_spacing',side=side,
                    side_weight=weight,angle_difference_deg=angle,relative_clearance=clearance/height,
                    relative_frame_extent=(end-start)/height,confidence_proxy=quality,axes=[left,right],
                    inferred_corridor_polygon_xy=polygon,left_cut_x=zones['left_cut_x'],right_cut_x=zones['right_cut_x'],
                    drawing_cut_x=cut,in_transition=side_weight(center,zones)<1,
                    physical_fit_verified=False,hidden_area_added_px2=0)
    return proposal,evidence


def supplement_side_gaps(regions, free, occupied, observations, scope, boundary):
    """Keep every baseline area mask unchanged; attach or add separate proposals."""
    zones=row_zones(observations,boundary)
    diagnostics=dict(enabled=True,side_fraction=SIDE_FRACTION,middle_fraction=.60,
                     zones=zones,frame_alignment_method='supported_wheel_contacts_with_frame_edge_diagnostics',
                     ground_heading_verified=False,pair_reviews=[],accepted_count=0,
                     added_count=0,hidden_area_added_px2=0,physical_fit_verified=False)
    if zones is None:
        return regions,free,diagnostics
    ordered=boundary['ordered_instance_ids']
    # Only side-adjacent frames need fitting; center pairs retain area processing.
    axes={i:frame_alignment(observations[i-1]) for i in ordered}
    result=list(regions);extended_free=free.copy()
    typical=float(np.median([observations[i-1]['box'][3]-observations[i-1]['box'][1] for i in ordered]))
    scale=max(1.,typical**2)
    for pocket in result:
        pocket['ranking_score']=pocket['area_px2']/scale
        pocket['candidate_status']='visible_area'
        pocket['occlusion_inferred']=False
    for pair in zip(ordered,ordered[1:]):
        proposal,evidence=pair_proposal(pair,observations,axes,zones,occupied,scope)
        diagnostics['pair_reviews'].append(evidence)
        if proposal is None:
            continue
        existing=[p for p in result if tuple(p['gap_instance_ids'])==pair]
        if existing:
            pocket=max(existing,key=lambda p:p['area_px2'])
        else:
            # Exclude wheel/frame holes as well as all previously assigned pixels.
            from paired_gap_grouping import occupied_owners
            _,holes=occupied_owners(occupied,observations)
            xx=np.arange(scope.shape[1])[None,:]
            core_zone=(xx<zones['left_cut_x']) if evidence['side']=='left' else (xx>=zones['right_cut_x'])
            visible=proposal&core_zone&~occupied&~extended_free&~holes
            yy,xx=np.nonzero(visible)
            if len(xx)<10:
                evidence.update(accepted=False,reason='insufficient_unassigned_visible_support')
                continue
            a,b,c,d=int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
            mask=visible[b:d,a:c]
            fragments=cv2.connectedComponents(mask.astype(np.uint8),connectivity=4)[0]-1
            number=max((p['area_id'] for p in result),default=0)+1
            pocket=dict(area_id=number,box=[a,b,c,d],mask=mask.copy(),area_px2=int(len(xx)),
                        center_xy=[float(xx.mean()),float(yy.mean())],gap_instance_ids=list(pair),
                        fragment_count=fragments,source_area_ids=[number],merged_across_overlap=False,
                        area_rank=len(result)+1,hidden_area_added_px2=0,physical_fit_verified=False)
            pocket.update(ranking_score=pocket['area_px2']/scale,candidate_status='visible_area',occlusion_inferred=False)
            result.append(pocket);extended_free|=visible;diagnostics['added_count']+=1
        side_score=evidence['relative_clearance']*evidence['relative_frame_extent']*evidence['confidence_proxy']*evidence['side_weight']
        base=pocket['area_px2']/scale
        # A fully visible large region does not need an inference badge or boost.
        supported_visible=int(np.count_nonzero(proposal&free))
        occluded_fraction=float(np.count_nonzero(proposal&occupied))/max(1,int(proposal.sum()))
        missing_fraction=1-supported_visible/max(1,int(proposal.sum()))
        evidence.update(occluded_fraction=occluded_fraction,missing_visible_fraction=missing_fraction,
                        area_score=base,alignment_score=side_score)
        if occluded_fraction<.04 and missing_fraction<.20:
            evidence.update(accepted=False,reason='already_supported_by_visible_area')
            continue
        pocket.update(occlusion_inferred=True,candidate_status='estimated_side_gap',
                      parallel_review=evidence,ranking_score=max(base,side_score),
                      physical_fit_verified=False)
        diagnostics['accepted_count']+=1
    # Central region masks, area values and their relative area order are unchanged.
    for rank,pocket in enumerate(sorted(result,key=lambda p:(-p['area_px2'],p['center_xy'][0])),1):
        pocket['area_rank']=rank
    result.sort(key=lambda p:(-p.get('ranking_score',p['area_px2']/scale),-p['area_px2'],p['center_xy'][0]))
    for rank,pocket in enumerate(result,1):
        pocket['rank']=rank
    diagnostics.update(visible_area_px2=int(extended_free.sum()),
                       original_visible_area_px2=int(free.sum()))
    return result,extended_free,diagnostics


def draw_side_proposals(overlay, ranked, rows, scope, occupied):
    """Dashed estimates are a separate layer, never measured filled area."""
    for pocket,row in zip(ranked,rows):
        if not pocket.get('occlusion_inferred'):
            continue
        layer=np.zeros_like(overlay)
        evidence=pocket['parallel_review'];polygon=evidence['inferred_corridor_polygon_xy']
        colour=tuple(int(row['color'][i:i+2],16) for i in (5,3,1))
        for first,last in zip(polygon,polygon[1:]+polygon[:1]):
            p,q=np.asarray(first),np.asarray(last);length=float(np.linalg.norm(q-p))
            for start in np.arange(0,length,12):
                lo=p+(q-p)*start/max(1,length);hi=p+(q-p)*min(start+6,length)/max(1,length)
                cv2.line(layer,tuple(np.rint(lo).astype(int)),tuple(np.rint(hi).astype(int)),(*colour,255),2,cv2.LINE_8)
        row.update(estimated_side_gap=True,side=evidence['side'],
                   relative_frame_spacing=round(evidence['relative_clearance'],3),
                   ranking_score=pocket['ranking_score'],area_kind='visible_pixels_only')
        xx=np.arange(scope.shape[1])[None,:]
        zone=(xx<evidence.get('drawing_cut_x',evidence['left_cut_x'])) if evidence['side']=='left' else (xx>=evidence.get('drawing_cut_x',evidence['right_cut_x']))
        layer[~scope|occupied|~zone]=0
        paint=layer[:,:,3]>0
        overlay[paint]=layer[paint]
    return overlay,rows
