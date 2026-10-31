"""Image-supported wheel and frame directions, with explicit abstention.

Ellipse rims and frame tube edges are hypotheses, not trained keypoints or
metric ground reconstruction. A silhouette centroid line is never a heading.
"""
import math
import cv2
import numpy as np


def wheel_ellipses(image,mask):
    h,w=mask.shape
    grey=cv2.GaussianBlur(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(3,3),0)
    edges=cv2.Canny(grey,35,105)
    support=cv2.dilate(mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
    edges[~support]=0;edges[:round(h*.32)]=0
    distance=cv2.distanceTransform((edges==0).astype(np.uint8),cv2.DIST_L2,3)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
    candidates=[]
    for contour in contours:
        if len(contour)<20: continue
        try: ellipse=cv2.fitEllipse(contour)
        except cv2.error: continue
        (cx,cy),(ew,eh),angle=ellipse;minor,major=min(ew,eh),max(ew,eh)
        if not (h*.20<major<h*.85 and major*.1<minor<=major and 0<cx<w and h*.43<cy<h*.95): continue
        curve=cv2.ellipse2Poly((round(cx),round(cy)),(max(1,round(ew/2)),max(1,round(eh/2))),round(angle),0,360,5)
        valid=(curve[:,0]>=0)&(curve[:,0]<w)&(curve[:,1]>=0)&(curve[:,1]<h)
        if valid.mean()<.85: continue
        points=curve[valid]
        rim=float(np.mean(distance[points[:,1],points[:,0]]<=max(2,h*.009)))
        ownership=float(support[points[:,1],points[:,0]].mean())
        if rim<.60 or ownership<.75: continue
        vx,vy=contour[:,0,0]-cx,contour[:,0,1]-cy;theta=math.radians(angle)
        u=vx*math.cos(theta)+vy*math.sin(theta);v=-vx*math.sin(theta)+vy*math.cos(theta)
        residual=float(np.median(abs(np.sqrt((u/(ew/2))**2+(v/(eh/2))**2)-1)))
        if residual>.16: continue
        if any(np.linalg.norm(np.array([cx,cy])-q['center_xy'])<h*.055 for q in candidates): continue
        bottom=points[np.argmax(points[:,1])].astype(float).tolist()
        candidates.append(dict(center_xy=[float(cx),float(cy)],contact_xy=bottom,
                               diameter=float(major),score=rim-residual))
    return sorted(candidates,key=lambda q:-q['score'])[:12]


def heading_from_wheels(wheels,height):
    choices=[]
    for i,first in enumerate(wheels):
        for second in wheels[i+1:]:
            p,q=np.array(first['contact_xy']),np.array(second['contact_xy']);length=float(np.linalg.norm(q-p))
            sizes=sorted([first['diameter'],second['diameter']])
            if not height*.30<length<height*1.15 or sizes[0]/sizes[1]<.55: continue
            if np.linalg.norm(np.array(first['center_xy'])-second['center_xy'])<sizes[1]*.55: continue
            if p[1]<q[1]: p,q=q,p
            # Small elliptical frame/spoke patches above the tyre bottoms must
            # not masquerade as two ground contacts of one bicycle.
            if p[1]<height*.88:continue
            choices.append((first['score']+second['score'],p,q,length))
    if not choices: return None
    score,p,q,length=max(choices,key=lambda q:q[0]);direction=(q-p)/length
    return dict(method='two_supported_wheel_contacts',near_xy=p.tolist(),far_xy=q.tolist(),
                direction_xy=direction.tolist(),extent_px=length,
                quality=min(1.,score/2),ground_heading_verified=False)


def frame_tube_direction(image,mask,height,wheels):
    """Require multiple supported straight frame edges; exclude wheel rims."""
    grey=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    clahe=cv2.createCLAHE(clipLimit=1.5,tileGridSize=(4,4)).apply(grey)
    edges=cv2.Canny(clahe,45,120)
    support=cv2.dilate(mask.astype(np.uint8),np.ones((3,3),np.uint8))>0
    edges[~support]=0
    edges[:round(height*.18)]=0;edges[round(height*.66):]=0
    yy,xx=np.ogrid[:mask.shape[0],:mask.shape[1]]
    for wheel in wheels:
        cx,cy=wheel['center_xy'];radius=wheel['diameter']*.48
        edges[(xx-cx)**2+(yy-cy)**2<radius**2]=0
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=max(10,round(height*.1)),
                          minLineLength=max(10,round(height*.15)),maxLineGap=max(2,round(height*.025)))
    if lines is None:return None
    segments=[]
    for a,b,c,d in np.asarray(lines).reshape(-1,4):
        vector=np.array([c-a,d-b],float);length=float(np.linalg.norm(vector))
        if abs(vector[1])<height*.08:continue
        if vector[1]>0:vector=-vector
        angle=math.atan2(vector[1],vector[0]);segments.append((angle,length,[a,b,c,d]))
    clusters=[]
    for angle,length,line in segments:
        cluster=[s for s in segments if abs(math.atan2(math.sin(s[0]-angle),math.cos(s[0]-angle)))<math.radians(8)]
        if len(cluster)<2 or sum(s[1] for s in cluster)<height*.40:continue
        # Distinct tubes/edges must be supported beyond a single short segment.
        points=np.array([[s[2][0],s[2][1]] for s in cluster]+[[s[2][2],s[2][3]] for s in cluster],float)
        if np.ptp(points[:,1])<height*.25:continue
        clusters.append((sum(s[1] for s in cluster),cluster))
    if not clusters:return None
    _,cluster=max(clusters,key=lambda c:c[0]);lengths=np.array([s[1] for s in cluster])
    vector=np.sum(np.array([[math.cos(s[0]),math.sin(s[0])] for s in cluster])*lengths[:,None],axis=0)
    vector/=np.linalg.norm(vector)
    return dict(method='supported_frame_edges',direction_xy=vector.tolist(),
                quality=min(.75,float(lengths.sum()/height/2)),segment_count=len(cluster),
                ground_heading_verified=False)


def estimate_vehicle_geometry(image,observation):
    a,b,c,d=observation['box'];height=d-b
    if height<35 or not observation.get('boundary_eligible',True):return dict(status='uncertain',reason='partial_or_small_vehicle')
    if 'image_edge_cut' in observation.get('review_flags',[]):return dict(status='uncertain',reason='image_edge_cut')
    mask=observation['mask'][b:d,a:c];patch=image[b:d,a:c]
    wheels=wheel_ellipses(patch,mask)
    heading=heading_from_wheels(wheels,height)
    frame=frame_tube_direction(patch,mask,height,wheels)
    if heading is None:
        # Tube orientation alone can be a fork or seat tube, so it cannot
        # authorise a new parking corridor without two wheel supports.
        return dict(status='uncertain',reason='two_wheel_supports_unavailable',
                    wheel_candidates=len(wheels),frame_evidence=frame)
    for key in ('near_xy','far_xy'):heading[key]=[heading[key][0]+a,heading[key][1]+b]
    heading.update(status='supported',wheel_candidates=len(wheels),frame_evidence=frame,
                   height=float(height),source='image_edges_and_wheel_rims')
    return heading
