"""Conservative opaque-surface review for crowded, multirow scenes.

Image-enclosed pale surfaces over an occupied vehicle's footprint are withheld
from free-area measurement. This is an uncertainty mask, not a cloth classifier.
Open image-border walls/floors and thin rack edges do not seed the review.
"""
import cv2
import numpy as np


def covered_surface_review(image,observations):
    h,w=image.shape[:2]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    grey=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(grey,40,100)
    barrier=cv2.dilate(edges,np.ones((3,3),np.uint8))>0
    pale=(hsv[:,:,1]<60)&(hsv[:,:,2]>145)
    count,labels,stats,_=cv2.connectedComponentsWithStats((pale&~barrier).astype(np.uint8),connectivity=4)
    blocked=np.zeros((h,w),bool);records=[]
    for number in range(1,count):
        x,y,cw,ch,area=map(int,stats[number]);x1,y1=x+cw,y+ch
        if area<400 or x==0 or y==0 or x1==w or y1==h or area/(cw*ch)<.25:continue
        supports=[]
        for index,obs in enumerate(observations,1):
            a,b,c,d=obs['box'];height=d-b
            horizontal=max(0,min(x1,c)-max(x,a))/cw
            relative=((y+y1)/2-b)/max(1,height)
            if (height>=80 and horizontal>=.8 and -.35<=relative<=.38
                    and y1>=b-height*.3 and cw>=height*.08 and cw<=height*.65
                    and ch>=height*.04 and area>=max(400,height**2*.004)):
                supports.append(index)
        if not supports:continue
        local=(labels[y:y1,x:x1]==number).astype(np.uint8)
        expanded=cv2.dilate(local,np.ones((7,7),np.uint8))>0
        # Preserve only observed pale pixels, with bounded edge interpolation.
        expanded &= (hsv[y:y1,x:x1,1]<75)&(hsv[y:y1,x:x1,2]>125)
        blocked[y:y1,x:x1] |= expanded
        records.append(dict(box=[x,y,x1,y1],visible_pixels=int(expanded.sum()),
                            supporting_instance_ids=supports,reason='unresolved_enclosed_surface_over_vehicle'))
    return blocked,dict(method='enclosed_surface_review',semantic_cover_classification_verified=False,
                        withheld_pixels=int(blocked.sum()),surfaces=records)
