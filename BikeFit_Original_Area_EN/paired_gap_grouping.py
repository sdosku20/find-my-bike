"""Visible gap identity from adjacent bicycle owners, not white connectivity.

Rows use the nearest facing occupied pixels. A wheel/frame hole with the
same owner on both sides is not a gap. Grouping never paints hidden pixels.
"""
import cv2
import numpy as np

DEFAULT_STRATEGY = 'pair_guarded'


def occupied_owners(occupied, observations):
    h,w=occupied.shape
    owners=np.zeros((h,w),np.int16)
    best=np.full((h,w),np.inf,np.float32)
    holes=np.zeros((h,w),bool)
    for number,obs in enumerate(observations,1):
        selected=np.asarray(obs['mask'],bool)
        support=np.asarray(obs.get('obstacle_mask',selected),bool)
        if selected.shape!=(h,w) or support.shape!=(h,w):
            raise ValueError('Instance masks must match the frame.')
        yy,xx=np.nonzero(support & occupied)
        if not len(xx):
            continue
        sy,sx=np.nonzero(selected)
        if not len(sx):
            continue
        # Actual selected masks outrank alternate-view support at overlaps.
        # Centre distance resolves overlapping selected instance masks only.
        centre=float(sx.mean());width=max(1,int(sx.max()-sx.min()+1))
        score=np.where(selected[yy,xx],0.,2.)+np.minimum(abs(xx-centre)/width,1.)
        score += (1-float(obs.get('confidence',1.)))*.001
        take=score<best[yy,xx]
        best[yy[take],xx[take]]=score[take]
        owners[yy[take],xx[take]]=number
        a,b,c,d=int(sx.min()),int(sy.min()),int(sx.max()+1),int(sy.max()+1)
        outside=np.pad((~selected[b:d,a:c]).astype(np.uint8),1,constant_values=1)
        cv2.floodFill(outside,None,(0,0),2)
        holes[b:d,a:c] |= outside[1:-1,1:-1]==1
    return owners,holes


def facing_pair_map(free,owners,ordered,holes):
    h,w=free.shape
    x=np.broadcast_to(np.arange(w,dtype=np.int32),(h,w))
    left=np.maximum.accumulate(np.where(owners>0,x,-1),axis=1)
    right=np.minimum.accumulate(np.where(owners>0,x,w)[:,::-1],axis=1)[:,::-1]
    left_id=np.take_along_axis(owners,np.maximum(left,0),axis=1)
    right_id=np.take_along_axis(owners,np.minimum(right,w-1),axis=1)
    table=np.zeros((max(int(owners.max()),max(ordered,default=0))+1,)*2,np.int16)
    pairs=list(zip(ordered,ordered[1:]))
    for number,(first,second) in enumerate(pairs,1):
        table[first,second]=number
    assignment=table[left_id,right_id]
    assignment[(left<0)|(right>=w)|~free|holes]=0
    return assignment,pairs


def region_parts(mask,pair,first_id):
    yy,xx=np.nonzero(mask)
    if not len(xx):
        return []
    a,b,c,d=int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
    count,labels,stats,centres=cv2.connectedComponentsWithStats(mask[b:d,a:c].astype(np.uint8),connectivity=4)
    parts=[]
    for k in range(1,count):
        x,y,width,height,area=map(int,stats[k]);x+=a;y+=b
        number=first_id+len(parts)
        parts.append(dict(area_id=number,box=[x,y,x+width,y+height],area_px2=area,
                          center_xy=[float(centres[k,0]+a),float(centres[k,1]+b)],
                          mask=labels[y-b:y-b+height,x-a:x-a+width]==k,
                          gap_instance_ids=list(pair),fragment_count=1,
                          source_area_ids=[number],merged_across_overlap=False))
    return parts


def bicycle_axis(observation,height):
    """A robust image-space divider for identity, never added free space."""
    mask=np.asarray(observation['mask'],bool);yy,xx=np.nonzero(mask)
    y0,y1=int(yy.min()),int(yy.max());span=max(1,y1-y0)
    middle=(yy>=y0+span*.25)&(yy<=y0+span*.65)
    rows=[];centres=[]
    for row in np.unique(yy[middle]):
        rows.append(float(row));centres.append(float(np.median(xx[yy==row])))
    if len(rows)<3:
        return np.full(height,float(np.median(xx)))
    centres=np.asarray(centres);rows=np.asarray(rows)
    keep=abs(centres-np.median(centres))<=max(3,float(np.ptp(xx))*.3)
    if keep.sum()<3:
        return np.full(height,float(np.median(centres)))
    slope,intercept=np.polyfit(rows[keep],centres[keep],1)
    slope=float(np.clip(slope,-.65,.65))
    intercept=float(np.median(centres[keep]-slope*rows[keep]))
    return slope*np.arange(height)+intercept


def recover_seeded_patches(raw_free,holes,seeds,pairs,ordered,observations):
    """Recover a visible patch beyond its horizontal facing-edge seed rows.

    A turned wheel can put the same bicycle on both sides of some rows of a
    valid gap. Its other rows still identify the neighbour pair. Flood only
    within that pair's disjoint image-space corridor; never across bicycles.
    """
    h,w=raw_free.shape;x=np.arange(w)[None,:]
    eligible=raw_free & ~holes
    count,components=cv2.connectedComponents(eligible.astype(np.uint8),connectivity=4)
    seen=seeds>0
    stride=len(pairs)+1
    evidence,counts=np.unique(components[seen].astype(np.int64)*stride+seeds[seen],return_counts=True)
    by_component={}
    for encoded,pixels in zip(evidence,counts):
        number,pair_id=divmod(int(encoded),stride)
        if number and pair_id:
            by_component.setdefault(number,[]).append((pair_id,int(pixels)))
    direct=np.zeros(count,np.int16)
    for number,support in by_component.items():
        if len(support)==1 and support[0][1]>=3:
            direct[number]=support[0][0]
    # A patch with unambiguous facing-pair evidence is retained in full.
    # Wheel steering must not shrink it merely by moving a fitted divider.
    assignment=direct[components]
    ambiguous=eligible & (assignment==0)
    if not ambiguous.any():
        return assignment
    axes={i:bicycle_axis(observations[i-1],h) for i in ordered}
    for index,(first,second) in enumerate(pairs,1):
        left=axes[first][:,None];right=axes[second][:,None]
        valid=right>left
        for other in ordered:
            if other not in (first,second):
                valid &= ~((axes[other][:,None]>left)&(axes[other][:,None]<right))
        corridor=ambiguous & (x>=left)&(x<right)&valid
        yy,xx=np.nonzero(corridor)
        if not len(xx):
            continue
        a,b,c,d=int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
        n,labels=cv2.connectedComponents(corridor[b:d,a:c].astype(np.uint8),connectivity=4)
        local_seeds=(seeds[b:d,a:c]==index)&(labels>0)
        support=np.bincount(labels[local_seeds],minlength=n)
        keep=support>=3;keep[0]=False
        retained=keep[labels]
        # Crossing/ambiguous divider order never permits overlapping ownership.
        retained &= assignment[b:d,a:c]==0
        assignment[b:d,a:c][retained]=index
    return assignment


def may_join(upper,lower,pair,observations,owners):
    """Join nearby aligned patches only when a third bicycle is not crossed."""
    a,b,c,d=upper['box'];e,f,g,h=lower['box']
    if upper['center_xy'][1]>=lower['center_xy'][1]:
        return False
    height=min(observations[i-1]['box'][3]-observations[i-1]['box'][1] for i in pair)
    separation=max(0,f-d)
    if separation>max(3,height*.55):
        return False
    overlap=min(c,g)-max(a,e)
    if overlap<.15*min(c-a,g-e):
        return False
    # Examine the direct strip between the visible fragments, not their
    # combined bounding box (which could include a distant neighbouring bike).
    y0=max(0,min(d,f));y1=min(owners.shape[0],max(d,f))
    if y1>y0:
        x0,x1=max(a,e),min(c,g)
        strip=owners[y0:y1,x0:x1]
        third=(strip>0)&~np.isin(strip,pair)
        if np.count_nonzero(third)>=max(3,strip.size*.015):
            return False
    else:
        # Side-by-side disjoint islands are not the upper/lower wheel case.
        return False
    return True


def combine(parts):
    a=min(p['box'][0] for p in parts);b=min(p['box'][1] for p in parts)
    c=max(p['box'][2] for p in parts);d=max(p['box'][3] for p in parts)
    mask=np.zeros((d-b,c-a),bool)
    for p in parts:
        x,y,x1,y1=p['box'];mask[y-b:y1-b,x-a:x1-a] |= p['mask']
    yy,xx=np.nonzero(mask)
    return dict(area_id=min(p['area_id'] for p in parts),box=[a,b,c,d],mask=mask,
                area_px2=int(mask.sum()),center_xy=[float(xx.mean()+a),float(yy.mean()+b)],
                gap_instance_ids=parts[0]['gap_instance_ids'],fragment_count=len(parts),
                source_area_ids=[p['area_id'] for p in parts],merged_across_overlap=len(parts)>1,
                hidden_area_added_px2=0,physical_fit_verified=False)


def group_pair_gaps(occupied,observations,scope,boundaries,strategy=DEFAULT_STRATEGY):
    if strategy not in ('components','pair_all','pair_guarded'):
        raise ValueError('Unknown gap grouping strategy.')
    occupied=np.asarray(occupied,bool);raw_free=scope & ~occupied
    owners,holes=occupied_owners(occupied,observations)
    seeds,pairs=facing_pair_map(raw_free,owners,boundaries['ordered_instance_ids'],holes)
    assignment=recover_seeded_patches(raw_free,holes,seeds,pairs,boundaries['ordered_instance_ids'],observations)
    groups=[];source_count=0;rejected=0
    for index,pair in enumerate(pairs,1):
        parts=region_parts(assignment==index,pair,source_count+1);source_count+=len(parts)
        if not parts:
            continue
        if strategy=='components':
            groups.extend(combine([p]) for p in parts)
            continue
        if strategy=='pair_all':
            groups.append(combine(parts))
            continue
        parent=list(range(len(parts)))
        def find(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]];i=parent[i]
            return i
        ordered=sorted(range(len(parts)),key=lambda i:parts[i]['center_xy'][1])
        for offset,i in enumerate(ordered):
            for j in ordered[offset+1:]:
                if find(i)==find(j):
                    continue
                if may_join(parts[i],parts[j],pair,observations,owners):
                    # Recheck every resulting member pair. Transitive chains
                    # cannot bypass a third-bicycle obstruction or distance cap.
                    first=[k for k in range(len(parts)) if find(k)==find(i)]
                    second=[k for k in range(len(parts)) if find(k)==find(j)]
                    allowed=all(may_join(*sorted([parts[x],parts[y]],key=lambda p:p['center_xy'][1]),
                                        pair,observations,owners) for x in first for y in second if x!=y)
                    if allowed:
                        parent[find(j)]=find(i)
                else:
                    rejected+=1
        buckets={}
        for i,p in enumerate(parts):
            buckets.setdefault(find(i),[]).append(p)
        groups.extend(combine(items) for items in buckets.values())
    candidate_free=assignment>0
    diagnostics=dict(strategy=strategy,raw_visible_free_area_px2=int(raw_free.sum()),
                     eligible_visible_area_px2=int(candidate_free.sum()),
                     excluded_intra_bicycle_holes_px2=int(np.count_nonzero(raw_free&holes)),
                     excluded_unowned_or_nonadjacent_px2=int(np.count_nonzero(raw_free&~holes&~candidate_free)),
                     source_fragment_count=source_count,candidate_group_count=len(groups),
                     merged_group_count=sum(p['fragment_count']>1 for p in groups),
                     guarded_join_rejections=rejected,hidden_area_added_px2=0,
                     physical_fit_verified=False)
    return groups,candidate_free,diagnostics


def annotate_gap_parts(overlay,ranked,rows):
    """Repeat a group's rank on every substantial disconnected visible part."""
    for pocket,row in zip(ranked,rows):
        row.update(fragment_count=pocket['fragment_count'],gap_instance_ids=pocket['gap_instance_ids'],
                   source_area_ids=pocket['source_area_ids'],merged_across_overlap=pocket['merged_across_overlap'])
        a,b,c,d=pocket['box']
        n,labels,stats,_=cv2.connectedComponentsWithStats(pocket['mask'].astype(np.uint8),connectivity=4)
        tx,ty=row['target_xy'];main=labels[ty-b,tx-a]
        for k in range(1,n):
            if k==main or stats[k,cv2.CC_STAT_AREA]<10:
                continue
            distance=cv2.distanceTransform(np.pad((labels==k).astype(np.uint8),1),cv2.DIST_L2,3)
            x,y=cv2.minMaxLoc(distance)[3];x+=a-1;y+=b-1
            cv2.circle(overlay,(x,y),15,(20,35,25,255),-1,cv2.LINE_AA)
            text=str(row['rank']);(tw,th),_=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,.6,2)
            cv2.putText(overlay,text,(x-tw//2,y+th//2),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255,255),2,cv2.LINE_AA)
    return overlay,rows
