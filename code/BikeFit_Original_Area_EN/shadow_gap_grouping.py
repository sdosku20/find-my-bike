"""Lighting preparation and conservative grouping of occluded gap fragments.

Grouping sums visible free pixels; it never fills a bicycle mask or measures
hidden clearance. Only top/bottom fragments bounded by the same two detected
bicycle instances may be grouped, with a short intervening obstruction.
"""
import cv2
import numpy as np


def compensate_shadows(image):
    """Gently lift locally dark luminance for semantic inference, not display.

    A smooth exposure map avoids sharpening ground-shadow edges. Bright areas
    are preserved and no brightness threshold is used to identify bicycles.
    This cannot recover silhouettes that the detector fails to distinguish.
    """
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light = lab[:, :, 0].astype(np.float32)
    scale = min(1., 640 / max(h, w))
    small = cv2.resize(light, (max(1, round(w*scale)), max(1, round(h*scale))), interpolation=cv2.INTER_AREA)
    smooth = cv2.GaussianBlur(small, (0, 0), max(1., min(small.shape)*.025))
    smooth = cv2.resize(smooth, (w, h), interpolation=cv2.INTER_LINEAR)
    gain = np.clip(125. / np.maximum(smooth, 35.), 1., 1.65)
    changed = gain > 1.01
    details = dict(method='smooth_local_luminance_gain', maximum_gain=1.65,
                   adjusted_fraction=round(float(changed.mean()), 4),
                   shadow_accuracy_verified=False)
    if not changed.any():
        return image, details
    corrected = lab.copy()
    corrected[:, :, 0] = np.clip(light*gain, 0, 255).astype(np.uint8)
    prepared = cv2.cvtColor(corrected, cv2.COLOR_LAB2BGR)
    prepared[~changed] = image[~changed]
    return prepared, details


def boundary_pair(pocket, observations):
    """Find two well-supported instance owners on a white patch's boundary."""
    a, b, c, d = pocket['box']
    # Pad before dilation so silhouettes just outside the box are included.
    x0, y0 = max(0, a-1), max(0, b-1)
    h, w = observations[0]['mask'].shape
    x1, y1 = min(w, c+1), min(h, d+1)
    patch = np.zeros((y1-y0, x1-x0), np.uint8)
    patch[b-y0:d-y0, a-x0:c-x0] = pocket['mask']
    border = cv2.dilate(patch, np.ones((3, 3), np.uint8)).astype(bool) & ~patch.astype(bool)
    support = []
    for index, observation in enumerate(observations):
        pixels = int(np.count_nonzero(border & observation['mask'][y0:y1, x0:x1]))
        if pixels:
            support.append((pixels, index))
    support.sort(reverse=True)
    if len(support) < 2:
        return None
    total = sum(pixels for pixels, _ in support)
    if support[1][0] < max(3, total*.04) or sum(p[0] for p in support[:2]) < total*.85:
        return None
    indices = tuple(sorted(index for _, index in support[:2]))
    first, second = [observations[i]['box'] for i in indices]
    if abs((first[0]+first[2]-second[0]-second[2])/2) < .12*min(first[2]-first[0], second[2]-second[0]):
        return None  # Nearly identical detections are not two gap boundaries.
    return indices


def can_join(upper, lower, pair, observations):
    """Require vertically aligned fragments and a limited separation."""
    a, b, c, d = upper['box']
    e, f, g, h = lower['box']
    if upper['center_xy'][1] >= lower['center_xy'][1] or f < b:
        return False
    left, right = max(a, e), min(c, g)
    if right-left < .25*min(c-a, g-e):
        return False
    height = min(observations[i]['box'][3]-observations[i]['box'][1] for i in pair)
    if max(0, f-d) > max(2., height*.25):
        return False
    # A third bicycle must not be crossed even if both end fragments touch
    # the same outer pair. Use only the shared horizontal strip between them.
    if f > d:
        for index, observation in enumerate(observations):
            if index in pair:
                continue
            other = observation['mask'][d:f, left:right]
            if np.count_nonzero(other) >= max(3, other.size*.03):
                return False
    return True


def merge_gap_fragments(pockets, observations):
    """Return disjoint grouped masks without inventing any extra free pixels."""
    if not observations:
        return pockets
    result = []
    pairs = [boundary_pair(p, observations) for p in pockets]
    parent = list(range(len(pockets)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, upper in enumerate(pockets):
        if pairs[i] is None or not upper['touches_top_line'] or upper['touches_bottom_line']:
            continue
        for j, lower in enumerate(pockets):
            if pairs[j] != pairs[i] or lower['touches_top_line'] or not lower['touches_bottom_line']:
                continue
            if can_join(upper, lower, pairs[i], observations):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(len(pockets)):
        groups.setdefault(find(i), []).append(i)
    for members in groups.values():
        if len(members) == 1:
            p = dict(pockets[members[0]])
            p.update(fragment_count=1, source_area_ids=[p['area_id']], merged_across_overlap=False)
            result.append(p)
            continue
        parts = [pockets[i] for i in members]
        a = min(p['box'][0] for p in parts); b = min(p['box'][1] for p in parts)
        c = max(p['box'][2] for p in parts); d = max(p['box'][3] for p in parts)
        mask = np.zeros((d-b, c-a), bool)
        for p in parts:
            x0, y0, x1, y1 = p['box']
            mask[y0-b:y1-b, x0-a:x1-a] |= p['mask']
        yy, xx = np.nonzero(mask)
        pair = pairs[members[0]]
        result.append(dict(box=[a,b,c,d], mask=mask, area_px2=int(mask.sum()),
            center_xy=[float(a+xx.mean()),float(b+yy.mean())], area_id=min(p['area_id'] for p in parts),
            touches_top_line=any(p['touches_top_line'] for p in parts),
            touches_bottom_line=any(p['touches_bottom_line'] for p in parts),
            fragment_count=len(parts), source_area_ids=[p['area_id'] for p in parts],
            gap_instance_ids=[i+1 for i in pair], merged_across_overlap=True,
            grouping_rule='same_two_bicycles_top_bottom_fragments_gap_at_most_25_percent_bicycle_height',
            hidden_area_added_px2=0, physical_fit_verified=False))
    return result


def annotate_group_fragments(overlay, ranked, rows):
    """Repeat one rank on each substantial disjoint patch of a grouped gap."""
    for pocket, row in zip(ranked, rows):
        row.update(fragment_count=pocket.get('fragment_count',1),
                   merged_across_overlap=pocket.get('merged_across_overlap',False),
                   source_area_ids=pocket.get('source_area_ids',[pocket['area_id']]))
        if row['fragment_count'] < 2:
            continue
        a,b,c,d=pocket['box'];mask=pocket['mask'].astype(np.uint8)
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
        tx,ty=row['target_xy'];main=int(labels[ty-b,tx-a])
        for number in range(1,count):
            if number==main or stats[number,cv2.CC_STAT_AREA] < max(10,pocket['area_px2']*.02):
                continue
            distance=cv2.distanceTransform(np.pad((labels==number).astype(np.uint8),1),cv2.DIST_L2,3)
            x,y=cv2.minMaxLoc(distance)[3];x+=a-1;y+=b-1
            cv2.circle(overlay,(x,y),12,(20,35,25,255),-1,cv2.LINE_AA)
            text=str(row['rank']);(tw,th),_=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,.48,1)
            cv2.putText(overlay,text,(x-tw//2,y+th//2),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,255,255),1,cv2.LINE_AA)
    return overlay,rows
