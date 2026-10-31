"""Slanted image-gap proposals; no scene labels or empty reference inputs."""
import json

import cv2
import numpy as np


def horizontal_clearance(profiles, cutoff=.22):
    """Symmetric free width around each axis pixel at every depth."""
    widths = np.zeros_like(profiles)
    for i, profile in enumerate(profiles):
        free = profile < cutoff
        edges = np.r_[0, np.flatnonzero(free[1:] != free[:-1])+1, len(profile)]
        for left, right in zip(edges[:-1], edges[1:]):
            if free[left]:
                positions = np.arange(right-left, dtype=np.float32)+.5
                widths[i, left:right] = 2*np.minimum(positions, right-left-positions)
    return widths


def same_rear_opening(local, first_axis, second_axis, target):
    """Join alternatives around a short rack, preserving a sustained tyre separator."""
    distance = float(np.median(np.abs(first_axis-second_axis)))
    if distance >= target*.9:
        return False
    # Only rear tyre support separates neighbouring bicycle gaps here. Short
    # rack feet do not justify displaying two ranks for the same wide opening.
    left = max(0, int(min(np.median(first_axis), np.median(second_axis))))
    right = min(local.shape[1], int(max(np.median(first_axis), np.median(second_axis)))+1)
    if right <= left:
        return True
    rear = local[int(local.shape[0]*.68):max(int(local.shape[0]*.68)+1, int(local.shape[0]*.94)), left:right]
    support = (rear > .35).mean(axis=0).astype(np.float32)
    support = cv2.GaussianBlur(support.reshape(1, -1), (0, 0), sigmaX=1).ravel()
    return float(support.max()) < .35


def rank_slanted_row(parking, approach, row, target_fraction, slope_penalty=3.):
    """Compare slanted straight axes through multiple narrow depth slices.

    A robust width describes sustained visible openness. Minimum width and
    crossing fraction remain separate: a rack/handlebar crossing is never
    silently converted into a verified traversable corridor.
    """
    height, width = parking.shape
    target = max(10., width*target_fraction)
    local = parking if row["entry_edge"] == "bottom" else parking[::-1]
    # Narrow slices avoid collapsing an inclined gap into one vertical profile.
    depths = np.linspace(.13, .94, 24)
    ys = np.clip(np.rint(depths*(height-1)).astype(int), 0, height-1)
    radius = max(2, int(round(height*.015)))
    profiles = np.stack([local[max(0, y-radius):min(height, y+radius+1)].mean(axis=0)
                         for y in ys])
    profiles = cv2.GaussianBlur(profiles, (0, 0), sigmaX=max(1., target*.018), sigmaY=.01)
    widths = horizontal_clearance(profiles)
    # Anchors cover the whole row, including edge gaps. A path is clipped out
    # rather than silently padded with blank space when any sample leaves ROI.
    anchors = np.arange(0, width, 3, dtype=np.float32)
    slopes = np.linspace(-.50, .50, 25, dtype=np.float32)
    anchor_y = height*.86
    xs = anchors[None, :, None] + slopes[:, None, None]*(ys[None, None, :]-anchor_y)
    valid = np.all((xs >= 0) & (xs < width), axis=2)
    ix = np.clip(np.rint(xs).astype(int), 0, width-1)
    sample_ids = np.arange(len(ys))[None, None, :]
    density = profiles[sample_ids, ix]
    clear = widths[sample_ids, ix]
    # Trace visible floor from the entrance until sustained structure closes
    # the gap. An opening may end before the handlebars; report its depth
    # rather than requiring or claiming a full bicycle-length passage.
    entry_blocked = (clear[..., ::-1] == 0)
    # A single sampled crossbar may be a rack; retain it as a review flag.
    consecutive = entry_blocked[..., 1:] & entry_blocked[..., :-1]
    stop = np.where(consecutive.any(axis=2), consecutive.argmax(axis=2)+1, len(ys))
    reached = np.arange(len(ys))[None, None, :] >= (len(ys)-stop[:, :, None])
    gap_depth = reached.mean(axis=2)
    # Widths apply only to the visible rear opening, never to unseen depth.
    masked_clear = np.where(reached, clear, np.nan)
    robust_width = np.nanquantile(masked_clear, .25, axis=2)
    minimum_width = np.min(np.where(reached, clear, np.inf), axis=2)
    blocked_fraction = np.sum((clear == 0) & reached, axis=2)/np.maximum(stop, 1)
    visible_density = np.sum(density*reached, axis=2)/np.maximum(stop, 1)
    # Entry is extrapolated only through the locally drawn approach strip.
    sign = 1 if row["entry_edge"] == "bottom" else -1
    approach_y = height-1+approach.shape[0]*.5
    entry_x = anchors[None, :] + slopes[:, None]*(approach_y-anchor_y)
    valid &= (entry_x >= 0) & (entry_x < width)
    approach_profile = cv2.GaussianBlur(approach.mean(axis=0).reshape(1, -1),
                                      (0, 0), sigmaX=max(1., target*.04)).ravel()
    approach_density = approach_profile[np.clip(np.rint(entry_x).astype(int), 0, width-1)]
    score = 100*(.35*np.minimum(1, robust_width/target)
                 + .40*gap_depth+.15*(1-visible_density)+.10*(1-approach_density))
    score -= 12*blocked_fraction + slope_penalty*np.abs(slopes[:, None])
    valid &= (gap_depth >= .30) & (blocked_fraction <= .45) & (robust_width >= max(4, target*.045))
    valid &= approach_density < .35
    score[~valid] = -np.inf
    # For each entrance anchor retain the best slant, then apply spatial NMS.
    best_slope = score.argmax(axis=0)
    best_scores = score[best_slope, np.arange(len(anchors))]
    order = np.argsort(-best_scores, kind="stable")
    chosen = []
    x0, y0, _, y1 = row["parking_xyxy"]
    for anchor_id in order:
        if not np.isfinite(best_scores[anchor_id]):
            continue
        si = int(best_slope[anchor_id])
        axis_x = xs[si, anchor_id]
        # Do not count alternate slants through the same gap several times.
        if any(np.median(np.abs(axis_x-other[0])) < target*.42 for other in chosen):
            continue
        chosen.append((axis_x, si, int(anchor_id)))
    groups = []
    for candidate in chosen:
        group = next((group for group in groups if all(
            same_rear_opening(local, candidate[0], other[0], target) for other in group)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    merged = []
    for group in groups:
        if len(group) > 1:
            middle = np.mean([anchors[item[2]] for item in group])
            ai = int(np.argmin(np.abs(anchors-middle)))
            si = int(best_slope[ai])
            candidate = (xs[si, ai], si, ai) if np.isfinite(score[si, ai]) else group[0]
        else:
            candidate = group[0]
        merged.append((*candidate, len(group)))
    records = []
    for axis_x, si, ai, alternatives in merged:
        sustained = float(robust_width[si, ai])
        minimum = float(minimum_width[si, ai])
        crossing = float(blocked_fraction[si, ai])
        status = ("partial_obstruction" if crossing > 0 or gap_depth[si, ai] < 1 else "narrow_path" if sustained < target*.5
                  else "limited_path" if sustained < target else "open_path")
        image_y = y0+ys if sign == 1 else y1-1-ys
        active = reached[si, ai]
        points = np.column_stack((x0+axis_x[active], image_y[active])).round(2).tolist()
        entry_image_x = float(x0+entry_x[si, ai])
        center = float(x0+anchors[ai])
        # This is a hypothesis outline, not a clearance envelope.
        visible_half_width = min(target, sustained)*.5
        polygon = [[float(x-visible_half_width), float(y)] for x, y in points]
        polygon += [[float(x+visible_half_width), float(y)] for x, y in points[::-1]]
        record = {"row": row["name"], "candidate_id": len(records)+1,
                  "center_x_px": round(center, 2), "entry_x_px": round(entry_image_x, 2),
                  "x0_px": int(np.floor(np.min(axis_x)+x0-visible_half_width)),
                  "x1_px_exclusive": int(np.ceil(np.max(axis_x)+x0+visible_half_width)),
                  "y0_px": int(min(image_y[active])), "y1_px_exclusive": int(max(image_y[active])+1),
                  "entry_edge": row["entry_edge"], "ranking_score": round(float(score[si, ai]), 3),
                  "status": status, "limiting_stage": ("crossing_structure" if crossing else
                     "visible_gap_end" if gap_depth[si, ai] < 1 else "sustained_width"),
                  "bottleneck_width_px": round(minimum, 2),
                  "sustained_width_px": round(sustained, 2),
                  "bottleneck_fraction_of_row": round(minimum/width, 6),
                  "crossing_fraction": round(crossing, 4),
                  "visible_gap_depth_fraction": round(float(gap_depth[si, ai]), 4),
                  "axis_mean_obstruction": round(float(visible_density[si, ai]), 4),
                  "approach_obstruction": round(float(approach_density[si, ai]), 4),
                  "target_width_px_assumed": round(target, 3),
                  "slope_dx_per_dy": round(float(slopes[si])*sign, 4),
                  "merged_opening_alternatives": alternatives,
                  "axis_xy_json": json.dumps(points), "polygon_xy_json": json.dumps(polygon),
                  "scale_calibrated": False, "physical_fit_verified": False}
        records.append(record)
    return records
