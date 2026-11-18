"""Perspective synthetic views of the 40-degree, widened-pad print with five marker tiles."""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = json.loads((ROOT / 'assets/sim/dock-vision-layout.json').read_text(encoding='utf8'))
PANELS = LAYOUT['panels']
BODY_COLORS = ((74, 116, 149), (176, 132, 91), (99, 120, 96), (118, 108, 136),
               (73, 77, 80), (182, 171, 144), (151, 102, 86), (132, 132, 131))


def prism(profile, width, material='body'):
    """Extrude a convex XZ polygon across Y and orient every face outwards."""
    ring = np.asarray(profile)
    vertices = np.array([(x,y,z) for y in (-width/2,width/2) for x,z in ring])
    n = len(ring)
    polygons = [vertices[:n], vertices[n:]]
    polygons.extend(vertices[[i, (i+1)%n, (i+1)%n+n, i+n]] for i in range(n))
    centre = vertices.mean(axis=0)
    faces = []
    for polygon in polygons:
        normal = np.cross(polygon[1]-polygon[0], polygon[2]-polygon[0])
        normal /= np.linalg.norm(normal)
        if np.dot(normal, polygon.mean(axis=0)-centre) < 0:
            normal = -normal
        faces.append((polygon,normal,material,None))
    return faces


def box(center, size, material):
    x,y,z = np.asarray(size)/2
    return [(p+center,n,m,t) for p,n,m,t in prism([(-x,-z),(x,-z),(x,z),(-x,z)],2*y,material)]


def dock_faces():
    faces = prism(LAYOUT['wedge']['profile_xz_m'],LAYOUT['wedge']['width_m'])
    for part in LAYOUT['boxes']:
        faces.extend(box(part['center_m'],part['size_m'],part['material']))
    for index,panel in enumerate(PANELS):
        right,up,normal = (np.asarray(panel[k]) for k in ('right','up','normal'))
        # Top of the applied two-colour tile sits 1.6 mm off the mounting face.
        centre = np.asarray(panel['center_m']) + normal*(LAYOUT['plate_thickness_m']+LAYOUT['ink_thickness_m'])
        side = panel['size_m']
        verts = np.array([centre + right*(x*side/2)+up*(y*side/2)
                          for x,y in [(-1,-1),(1,-1),(1,1),(-1,1)]])
        bits = np.array([list(row) for row in panel['bitmap']],dtype=np.uint8)
        faces.append((verts, normal, 'panel', (index,centre,right,up,side,bits)))
    return faces


CHAIR = dock_faces()


def background(rng, width, height):
    base = rng.integers(66,195,size=3)
    base = (base+base.mean()*2)/3
    yy,xx = np.ogrid[:height,:width]
    grad = (xx/width-.5)*rng.uniform(-30,30)+(yy/height-.5)*rng.uniform(-35,35)
    img = Image.fromarray(np.uint8(np.clip(base + grad[...,None],0,255)))
    pen = ImageDraw.Draw(img)
    step = int(rng.integers(max(8,width//9), max(10,width//3)))
    edge = tuple(np.uint8(np.clip(base+rng.uniform(-25,15),0,255)))
    if rng.random()<.8:
        for x in range(-width,width*2,step):
            pen.line([(x,0),(x+width//3,height)],fill=edge,width=1)
        for y in range(step//2,height,step):
            pen.line([(0,y),(width,y-rng.integers(0,8))],fill=edge)
    for _ in range(rng.integers(1,8)):
        x,y=rng.integers(-step,width),rng.integers(-step,height)
        w,h=rng.integers(2,step+1,size=2)
        color=tuple(int(v) for v in rng.integers(42,200,3))
        if rng.random()<.5:
            pen.ellipse((x,y,x+w,y+h),fill=color)
        else:
            pen.rectangle((x,y,x+w,y+h),fill=color)
    return np.array(img)


def render_scene(seed, azimuth_deg, *, present=True, occlusion='none', elevation_deg=None,
                 size=(96,72), hard_negative=False, sensor_scale=1):
    """Return RGB uint8, clipped amodal pixel-edge XYXY box, and visibility metadata.

    Positive labels describe the chair before a partial foreground obstruction.
    Full occlusion and scenes without the chair return None. Azimuth zero is
    the approach lane (+X). The camera, materials, substrate and clutter vary by seed.
    """
    if occlusion not in ('none','partial','markers_hidden','full'):
        raise ValueError('unknown occlusion')
    rng=np.random.default_rng(seed)
    width,height=size
    el=float(elevation_deg) if elevation_deg is not None else rng.uniform(8,61)
    az,alt=np.radians([azimuth_deg,el])
    forward=-np.array([np.cos(alt)*np.cos(az),np.cos(alt)*np.sin(az),np.sin(alt)])
    right=np.array([-np.sin(az),np.cos(az),0])
    up=np.cross(right,forward)
    eye=np.array([-.006,0,.040])-forward*rng.uniform(.24,.48)
    focal=width*rng.uniform(.91,1.08)
    cx,cy=width*rng.uniform(.32,.68),height*rng.uniform(.33,.67)
    image=background(rng,width,height)
    # Keep the camera pose, materials and clutter RNG identical across sensor
    # resolutions. Rasterize the dock geometry itself at the sensor resolution.
    if sensor_scale != 1:
        width *= sensor_scale
        height *= sensor_scale
        focal *= sensor_scale
        cx *= sensor_scale
        cy *= sensor_scale
        image = np.array(Image.fromarray(image).resize((width,height), Image.Resampling.BILINEAR))
    depth=np.full((height,width),np.inf)
    owner=np.full((height,width),-1,np.int8)
    body=np.asarray(BODY_COLORS[rng.integers(len(BODY_COLORS))])
    light=np.array([rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(.45,1)])
    light/=np.linalg.norm(light)
    colors={'body':body,'contact':np.array([183,147,88]),
            'panel':np.array([219,218,210]),'decoy':body,'dark':np.array([42,42,38])}
    faces=CHAIR if present else []
    if not present and hard_negative:
        # Crates, low ramps and checker-patterned boxes share dock colours and scale.
        if rng.random()<.5:
            faces=box((0,0,.036),(.113,.106,.072),'decoy')
        else:
            faces=prism([(-.060,0),(.052,0),(-.060,.075)],.112,'decoy')
        if rng.random()<.66:
            faces += box((-.038,0,.076),(.018,.038,.008),'dark')
            faces += box((-.035,.022,.077),(.017,.014,.009),'panel')
    for polygon,normal,material,marker in faces:
        if np.dot(normal,eye-polygon[0]) <= 0:
            continue
        rel=polygon-eye
        z=rel@forward
        xy=np.stack((cx+focal*(rel@right)/z,cy-focal*(rel@up)/z),axis=1)
        a,b=np.maximum(0,np.floor(xy.min(axis=0)).astype(int))
        c,e=np.minimum([width,height],np.ceil(xy.max(axis=0)).astype(int)+1)
        if c<=a or e<=b:
            continue
        mask=Image.new('L',(c-a,e-b))
        ImageDraw.Draw(mask).polygon([tuple(v) for v in xy-[a,b]],fill=1)
        yy,xx=np.nonzero(np.asarray(mask)); yy+=b;xx+=a
        rays=forward + (xx+.5-cx)[:,None]*right/focal - (yy+.5-cy)[:,None]*up/focal
        denom=rays@normal
        with np.errstate(divide='ignore',invalid='ignore'):
            dist=np.dot(polygon[0]-eye,normal)/denom
        use=(dist>0)&(dist<depth[yy,xx])
        yy,xx,dist,rays=yy[use],xx[use],dist[use],rays[use]
        if not len(yy):
            continue
        depth[yy,xx]=dist
        shade=.68+.32*max(0.,float(normal@light))
        owner[yy,xx]=0
        if marker is not None and occlusion!='markers_hidden':
            index,centre,mr,mu,side,bits=marker
            hit=eye+rays*dist[:,None]-centre
            cols=np.clip(((hit@mr/side+.5)*7).astype(int),0,6)
            rows=np.clip(((.5-hit@mu/side)*7).astype(int),0,6)
            ink=bits[rows,cols].astype(bool)
            image[yy,xx]=np.where(ink[:,None],29.,colors['panel'])*shade
            owner[yy,xx]=1+index
        else:
            image[yy,xx]=colors['body' if marker is not None else material]*shade
    ys,xs=np.nonzero(owner>=0)
    box_xyxy=None
    if present and len(xs):
        x0,x1=int(xs.min()),int(xs.max())+1
        y0,y1=int(ys.min()),int(ys.max())+1
        box_xyxy=(x0,y0,x1,y1)
        if occlusion in ('partial','full'):
            if occlusion=='partial':
                border=int((x1-x0)*rng.uniform(.3,.6))
                if rng.random()<.5:
                    x0=x1-border
                    x1=width
                else:
                    x1=x0+border
                    x0=0
            else:
                x0=max(0,x0-sensor_scale*int(rng.integers(1,6))); x1=min(width,x1+sensor_scale*int(rng.integers(1,6)))
                box_xyxy=None
            y0=max(0,y0-sensor_scale*int(rng.integers(1,8))); y1=min(height,y1+sensor_scale*int(rng.integers(1,8)))
            image[y0:y1,x0:x1]=rng.integers(40,196,3)
            owner[y0:y1,x0:x1]=-1
    marker_pixels=[int(np.count_nonzero(owner==i+1)) for i in range(len(PANELS))]
    if rng.random()<.45:
        image=np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(rng.uniform(.15,.65))))
    gain=rng.uniform(.76,1.18)
    noise=rng.normal(0,rng.uniform(.5,4),size=(height,width,1))
    rgb=np.clip(image*gain+noise,0,255).astype(np.uint8)
    return rgb,box_xyxy,dict(azimuth_deg=float(azimuth_deg),elevation_deg=float(el),
                             visible_marker_count=sum(n>=4 for n in marker_pixels),marker_pixels=marker_pixels)
