"""Enclose the row, refining long upper chords on broadside silhouettes."""
import cv2
import numpy as np


def secondary_upper_anchor(mask, point, neighbour):
    """Support a lower upper-body knot away from a broadside vehicle's peak.

    This is silhouette evidence, not a handlebar/seat or heading detector.
    Narrow vehicles and small height differences retain the original chord.
    The search stays in the inner opposite half, excluding the wheel ends;
    only a horizontally supported cap in the upper 42% can become a knot.
    """
    mask = np.asarray(mask, dtype=bool)
    yy, xx = np.nonzero(mask)
    x0, x1, y0, y1 = int(xx.min()), int(xx.max()), int(yy.min()), int(yy.max())
    width, height = x1-x0+1, y1-y0+1
    if height < 35 or width < height*1.05:
        return None
    tx, ty = point
    position = (tx-x0)/width
    if position < .30:
        lo, hi = x0+round(width*.45), x0+round(width*.82)
    elif position > .70:
        lo, hi = x0+round(width*.18), x0+round(width*.55)
    else:
        return None
    # Never extend beyond or reverse the original neighbouring top segment.
    lo, hi = max(lo, min(tx, neighbour[0])+1), min(hi, max(tx, neighbour[0]))
    if hi-lo < max(5, round(width*.05)):
        return None
    columns = np.arange(lo, hi)
    patch = mask[:, lo:hi]
    profile = np.where(patch.any(axis=0), patch.argmax(axis=0), y1+1)
    # A short median window rejects isolated high pixels without editing masks.
    window = max(3, round(height*.025)) | 1
    padded = np.pad(profile, window//2, mode='edge')
    stable = np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=1)
    cap_y = float(stable.min())
    supported = (profile <= cap_y+max(2, round(height*.035)))
    # Require one contiguous support, rather than joining unrelated specks.
    runs = np.split(np.flatnonzero(supported), np.flatnonzero(np.diff(np.flatnonzero(supported)) > 1)+1)
    # A broad, flat bar/body spanning the search window is not a separate
    # upper support. Retain its original boundary and fragment grouping.
    runs = [run for run in runs if max(5, round(width*.045)) <= len(run) <= width*.30
            and len(run) < (hi-lo)*.85]
    if not runs:
        return None
    run = min(runs, key=lambda r: (float(np.median(profile[r])), -len(r)))
    index = int(run[len(run)//2])
    x, y = int(columns[index]), int(profile[index])
    chord_y = ty+(neighbour[1]-ty)*(x-tx)/(neighbour[0]-tx)
    if y < chord_y+max(3, height*.08) or y > y0+height*.42:
        return None
    return dict(point_xy=[x,y], support_columns=len(run),
                drop_from_chord_px=round(y-chord_y,2),
                source='supported_opposite_upper_silhouette')


def outward_end_path(mask, top, bottom, side):
    """Refine an inward end chord using the observed outward silhouette.

    Both extrema must be well inside the same inward half of a broad mask.
    A sustained outer contour, not a speck or a bounding-box corner, must
    support the change. The old straight chord remains the fallback.
    """
    mask=np.asarray(mask,bool);yy,xx=np.nonzero(mask)
    a,c=int(xx.min()),int(xx.max());b,d=int(yy.min()),int(yy.max())
    width,height=c-a+1,d-b+1
    if height<35 or width<height*.60:
        return None
    positions=[(p[0]-a)/width for p in (top,bottom)]
    if side=='left':
        if min(positions)<.65:return None
    elif side=='right':
        if max(positions)>.35:return None
    else:
        raise ValueError('Unknown row end.')
    rows=np.arange(b,d+1);strip=mask[b:d+1,a:c+1]
    # Do not bridge vertically missing silhouettes or invent ground points.
    if not strip.any(axis=1).all():return None
    edge=strip.argmax(axis=1)+a if side=='left' else c-strip[:,::-1].argmax(axis=1)
    chord=top[0]+(bottom[0]-top[0])*(rows-top[1])/max(1,bottom[1]-top[1])
    outside=chord-edge if side=='left' else edge-chord
    support=outside>=max(4,width*.20)
    if support.sum()<height*.30:return None
    path=[list(top)]+[[int(x),int(y)] for x,y in zip(edge,rows)]+[list(bottom)]
    # Remove duplicate and exactly collinear points without moving any anchor.
    compact=[]
    for point in path:
        if compact and point==compact[-1]:continue
        while len(compact)>=2:
            p,q=compact[-2:]
            if (q[0]-p[0])*(point[1]-q[1])!=(q[1]-p[1])*(point[0]-q[0]):break
            compact.pop()
        compact.append(point)
    return dict(side=side,path_xy=compact,support_rows=int(support.sum()),
                maximum_outward_px=round(float(outside.max()),2),
                source='observed_rowwise_outer_silhouette')


def automatic_boundary(shape, observations):
    """Order bicycles from left to right; top is min y and bottom is max y."""
    points = []
    for instance_id, observation in enumerate(observations, 1):
        if not observation.get('boundary_eligible',True):
            continue
        mask = np.asarray(observation['mask'], dtype=bool)
        if mask.shape != shape:
            raise ValueError('Bicycle mask must match the frame dimensions.')
        yy, xx = np.nonzero(mask)
        if not len(xx):
            continue
        top_y, bottom_y = int(yy.min()), int(yy.max())
        # If an extreme row has several pixels, choose its middle actual pixel.
        top_xs = np.sort(xx[yy == top_y])
        bottom_xs = np.sort(xx[yy == bottom_y])
        points.append(dict(instance_id=instance_id, center_x=float(xx.mean()),
                           needs_review=bool(observation.get('needs_review',False)),
                           top_xy=[int(top_xs[len(top_xs)//2]), top_y],
                           bottom_xy=[int(bottom_xs[len(bottom_xs)//2]), bottom_y]))
    points.sort(key=lambda p: (p['center_x'], p['instance_id']))
    tops = [dict(instance_id=p['instance_id'], point_xy=p['top_xy'],needs_review=p['needs_review']) for p in points]
    bottoms = [dict(instance_id=p['instance_id'], point_xy=p['bottom_xy'],needs_review=p['needs_review']) for p in points]

    top_path, refinements = [], []
    for index, item in enumerate(tops):
        additions = []
        for neighbour_index in (index-1, index+1):
            if not 0 <= neighbour_index < len(tops):
                continue
            neighbour = tops[neighbour_index]
            anchor = secondary_upper_anchor(observations[item['instance_id']-1]['mask'],
                                            item['point_xy'], neighbour['point_xy'])
            if anchor is None:
                continue
            # The knot belongs on the correct side in the existing row order.
            before = neighbour_index < index
            if before != (anchor['point_xy'][0] < item['point_xy'][0]):
                continue
            extra = dict(instance_id=item['instance_id'], point_xy=anchor['point_xy'],
                         needs_review=item['needs_review'])
            additions.append((before, extra))
            refinements.append(dict(instance_id=item['instance_id'],
                                    neighbour_instance_id=neighbour['instance_id'], **anchor))
        top_path.extend(extra for before, extra in additions if before)
        top_path.append(item)
        top_path.extend(extra for before, extra in additions if not before)

    def lines(items):
        return [dict(instance_ids=[a['instance_id'], b['instance_id']],
                     needs_review=a['needs_review'] or b['needs_review'],
                     endpoints_xy=[a['point_xy'], b['point_xy']]) for a, b in zip(items, items[1:])]

    end_refinements=[];sides=[];end_paths=[]
    for side,p in ( [('left',points[0]),('right',points[-1])] if len(points)>=2 else []):
        refinement=outward_end_path(observations[p['instance_id']-1]['mask'],p['top_xy'],p['bottom_xy'],side)
        path=refinement['path_xy'] if refinement else [p['top_xy'],p['bottom_xy']]
        end_paths.append(path)
        if refinement:end_refinements.append(dict(instance_id=p['instance_id'],**refinement))
        sides.extend(dict(instance_ids=[p['instance_id']],needs_review=p['needs_review'],endpoints_xy=[a,b])
                     for a,b in zip(path,path[1:]))
    def close_path(upper):
        if len(points)<2:return []
        return ([p['point_xy'] for p in upper]+end_paths[1][1:]+
                [p['point_xy'] for p in reversed(bottoms)][1:]+list(reversed(end_paths[0]))[1:-1])
    polygon=close_path(top_path)
    boundary = dict(mode='automatic_local_upper_silhouette' if refinements else 'automatic_bicycle_y_extrema',
                    top_points=tops, top_path_points=top_path, upper_refinements=refinements, bottom_points=bottoms,
                    end_refinements=end_refinements,
                    top_lines=lines(top_path), bottom_lines=lines(bottoms), side_lines=sides,
                    polygon_xy=polygon, ordered_instance_ids=[p['instance_id'] for p in points],
                    review_required=any(p.get('needs_review',False) for p in observations),
                    excluded_instance_ids=[i for i,p in enumerate(observations,1) if not p.get('boundary_eligible',True)],
                    anchor_count=len(points),
                    top_rule='extrema_with_supported_broadside_upper_knots' if refinements else 'minimum_image_y_of_each_instance_mask',
                    bottom_rule='maximum_image_y_of_each_instance_mask',
                    ordering='instance_mask_centroid_x', tie_rule='middle_actual_pixel_on_extreme_row',
                    closure='supported_outer_silhouette_ends' if end_refinements else 'join_first_and_last_bicycle_top_to_bottom',
                    inside_rule='even_odd_pixel_centres; one_pixel_LINE_8_boundary_excluded',
                    status='ready' if polygon else 'need_at_least_two_bicycles')
    scope = polygon_mask(shape, polygon)
    if refinements:
        original_polygon = close_path(tops)
        # Refinement only removes upper background, including crossed contours.
        scope &= polygon_mask(shape, original_polygon)
    if end_refinements:
        # An end repair must not remove any previously enclosed pixels.
        legacy=[p['point_xy'] for p in top_path]+[p['point_xy'] for p in reversed(bottoms)]
        legacy_scope=polygon_mask(shape,legacy)
        if refinements:
            legacy_scope &= polygon_mask(shape,[p['point_xy'] for p in tops]+[p['point_xy'] for p in reversed(bottoms)])
        scope |= legacy_scope
        boundary['inside_rule']='union_of_legacy_and_observed_outer_end_contours; pixel_centres'
    if polygon and not scope.any():
        boundary['status'] = 'no_enclosed_pixels'
    return scope, boundary


def polygon_mask(shape, polygon):
    """Keep only pixel centres inside the displayed closed contour."""
    scope = np.zeros(shape, bool)
    if len(polygon) < 3:
        return scope
    points = np.asarray(polygon, dtype=np.int32)
    h, w = shape
    x0, y0 = np.maximum(points.min(axis=0), [0,0])
    x1, y1 = np.minimum(points.max(axis=0)+1, [w,h])
    if x1 <= x0 or y1 <= y0:
        return scope
    x = np.arange(x0, x1, dtype=np.float64)[None,:]
    y = np.arange(y0, y1, dtype=np.float64)[:,None]
    inside = np.zeros((y1-y0, x1-x0), bool)
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        dx, dy = (b-a).astype(np.float64)
        if dy:
            inside ^= ((a[1] > y) != (b[1] > y)) & (x < a[0]+(y-a[1])*dx/dy)
    edge = np.zeros(inside.shape, np.uint8)
    local = points-[x0,y0]
    cv2.polylines(edge, [local.astype(np.int32)], True, 1, 1, cv2.LINE_8)
    scope[y0:y1,x0:x1] = inside & (edge == 0)
    return scope


def automatic_bounded_regions(bicycle_mask, observations):
    occupied = np.asarray(bicycle_mask, dtype=bool)
    scope, boundary = automatic_boundary(occupied.shape, observations)
    free = scope & ~occupied
    count, labels, stats, centers = cv2.connectedComponentsWithStats(free.astype(np.uint8), connectivity=4)
    regions = []
    for number in range(1, count):
        x, y, width, height, area = map(int, stats[number])
        regions.append(dict(area_id=number, box=[x,y,x+width,y+height], area_px2=area,
                            center_xy=centers[number].tolist(), mask=labels[y:y+height,x:x+width] == number,
                            fragment_count=1, merged_across_overlap=False, source_area_ids=[number]))
    return regions, free, scope, boundary


def render_boundary(shape, boundaries):
    overlay = np.zeros((*shape,4),np.uint8)
    for name, colour in (('side_lines',(205,215,210,255)),
                         ('top_lines',(230,215,90,255)),('bottom_lines',(85,220,255,255))):
        for line in boundaries[name]:
            p,q = line['endpoints_xy']
            if line.get('needs_review'):
                first,last=np.asarray(p),np.asarray(q);length=float(np.linalg.norm(last-first))
                for start in np.arange(0,length,14):
                    lo=first+(last-first)*start/max(1,length);hi=first+(last-first)*min(start+8,length)/max(1,length)
                    cv2.line(overlay,tuple(np.rint(lo).astype(int)),tuple(np.rint(hi).astype(int)),colour,2,cv2.LINE_8)
            else:
                cv2.line(overlay,tuple(p),tuple(q),colour,2,cv2.LINE_8)
    for name,colour in (('top_points',(230,215,90,255)),('bottom_points',(85,220,255,255))):
        for point in boundaries[name]:
            cv2.circle(overlay,tuple(point['point_xy']),4 if point.get('needs_review') else 3,
                       (60,120,255,255) if point.get('needs_review') else colour,-1,cv2.LINE_8)
    return overlay
