"""Separate supported contact baselines before using the existing gap rules.

Rows and covered-object masks are image hypotheses, not physical clearance.
The single-row path retains the established implementation unchanged.
"""
import cv2
import numpy as np
from automatic_boundary import automatic_boundary
from paired_gap_grouping import group_pair_gaps
from line_closed_white_areas import rank_regions
from side_gap_inference import supplement_side_gaps


def parking_rows(observations):
    items=[]
    for number,o in enumerate(observations,1):
        if not o.get('boundary_eligible',True):continue
        yy,xx=np.nonzero(o['mask'])
        if not len(xx):continue
        height=float(yy.max()-yy.min()+1)
        near=yy>=yy.max()-max(2,height*.05)
        items.append((number,float(np.median(xx[near])),float(yy.max()),height))
    if len(items)<6:return [list(p[0] for p in items)],[]
    data=np.array(items,float);typical=float(np.median(data[:,3]))
    if np.ptp(data[:,2])<typical*.65:return [data[:,0].astype(int).tolist()],[]
    remaining=list(range(len(items)));groups=[];models=[]
    while len(remaining)>=3:
        best=None
        for ii,i in enumerate(remaining):
            for j in remaining[ii+1:]:
                dx=data[j,1]-data[i,1]
                if abs(dx)<typical*.4:continue
                slope=(data[j,2]-data[i,2])/dx
                if abs(slope)>.6:continue
                intercept=data[i,2]-slope*data[i,1]
                errors=abs(data[remaining,2]-slope*data[remaining,1]-intercept)
                accepted=[k for k,e in zip(remaining,errors) if e<=max(5.,data[k,3]*.13)]
                if len(accepted)<3:continue
                heights=data[accepted,3]
                if np.quantile(heights,.8)/max(1,np.quantile(heights,.2))>2.5:continue
                score=(len(accepted),float(np.ptp(data[accepted,1])), -float(np.mean(errors)))
                if best is None or score>best[0]:best=(score,accepted,slope,intercept)
        if best is None:break
        _,accepted,slope,intercept=best
        # Refit once, still requiring a local height-scaled contact agreement.
        slope,intercept=np.polyfit(data[accepted,1],data[accepted,2],1)
        accepted=[k for k in remaining if abs(data[k,2]-slope*data[k,1]-intercept)<=max(5.,data[k,3]*.13)]
        if len(accepted)<3:break
        groups.append([items[k][0] for k in accepted])
        models.append(dict(slope=float(slope),intercept=float(intercept),
                           median_height_px=float(np.median(data[accepted,3]))))
        remaining=[k for k in remaining if k not in accepted]
    # Do not turn slight slope or a lone bad mask into a second parking row.
    if len(groups)<2:return [data[:,0].astype(int).tolist()],[]
    model_heights=[m['median_height_px'] for m in models]
    if max(model_heights)/max(1,min(model_heights))<1.45:
        distances=[abs(a['intercept']-b['intercept']) for i,a in enumerate(models) for b in models[i+1:]]
        if max(distances,default=0)<typical*.55:return [data[:,0].astype(int).tolist()],[]
    # Unassigned vehicles remain obstacles and cannot create cross-row links.
    uncertain=[items[k][0] for k in remaining]
    return groups,uncertain


def _single(occupied,observations):
    scope,boundary=automatic_boundary(occupied.shape,observations)
    regions,free,grouping=group_pair_gaps(occupied,observations,scope,boundary)
    ranked=rank_regions(regions)
    ranked,free,side_review=supplement_side_gaps(ranked,free,occupied,observations,scope,boundary)
    grouping.update(baseline_eligible_visible_area_px2=grouping['eligible_visible_area_px2'],
                    eligible_visible_area_px2=int(free.sum()),candidate_group_count=len(ranked))
    return scope,boundary,ranked,free,grouping,side_review


def analyze_scene_masks(occupied,observations):
    occupied=np.asarray(occupied,bool)
    rows,uncertain=parking_rows(observations)
    if len(rows)<2:
        scope,boundary,ranked,free,grouping,side_review=_single(occupied,observations)
        boundary.update(row_count=1 if len(rows[0])>=2 else 0, row_instance_ids=rows,
                        uncertain_row_instance_ids=[])
    else:
        scope=np.zeros_like(occupied);free=scope.copy();ranked=[];records=[]
        rows=sorted(rows,key=lambda ids:-np.median([observations[i-1]['box'][3] for i in ids]))
        boundary=dict(mode='independent_parking_rows',row_count=len(rows),row_instance_ids=rows,
            uncertain_row_instance_ids=uncertain,top_points=[],bottom_points=[],top_lines=[],bottom_lines=[],
            side_lines=[],top_path_points=[],upper_refinements=[],end_refinements=[],polygon_xy=[],ordered_instance_ids=[],
            excluded_instance_ids=uncertain,anchor_count=sum(map(len,rows)),review_required=True,
            ordering='contact_baselines_then_instance_mask_centroid_x',
            status='ready',inside_rule='union_of_independent_row_scopes')
        # Closest supported row owns overlaps; no pixel may be counted twice.
        for row_id,ids in enumerate(rows,1):
            selected=[dict(o,boundary_eligible=(i in ids)) for i,o in enumerate(observations,1)]
            local_scope,local_boundary=automatic_boundary(occupied.shape,selected)
            local_scope &= ~scope
            regions,local_free,diagnostics=group_pair_gaps(occupied,observations,local_scope,local_boundary)
            for p in regions:
                p['row_id']=row_id
                p['area_id']=len(ranked)+1;p['source_area_ids']=[p['area_id']]
                p.update(candidate_status='visible_area',occlusion_inferred=False)
                ranked.append(p)
            scope|=local_scope;free|=local_free
            records.append(dict(row_id=row_id,instance_ids=ids,**diagnostics))
            for key in ('top_points','bottom_points','top_lines','bottom_lines','side_lines','top_path_points','upper_refinements','end_refinements'):
                boundary[key].extend(local_boundary.get(key,[]))
            boundary['ordered_instance_ids'].extend(local_boundary['ordered_instance_ids'])
        ranked=rank_regions(ranked)
        for rank,p in enumerate(ranked,1):p['rank']=rank
        grouping=dict(strategy='pair_guarded_per_parking_row',rows=records,row_count=len(rows),
            eligible_visible_area_px2=int(free.sum()),baseline_eligible_visible_area_px2=int(free.sum()),
            candidate_group_count=len(ranked),hidden_area_added_px2=0,physical_fit_verified=False)
        side_review=dict(enabled=False,zones=None,pair_reviews=[],accepted_count=0,added_count=0,
                         reason='multiple_rows_use_same_row_visible_area_only',row_count=len(rows))
    count=cv2.connectedComponents(occupied.astype(np.uint8),connectivity=8)[0]-1
    return dict(binary=np.where(occupied,0,255).astype(np.uint8),boundaries=boundary,
        regions=ranked,ranked=[p for p in ranked if p['area_px2']>=10],component_count=count,
        minimum_component_area_px=0,free_mask=free,boundary_mask=scope,grouping=grouping,
        side_review=side_review,total_visible_area_px2=int(free.sum()))
