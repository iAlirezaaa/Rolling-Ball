"""Build and bake the Rolling Ball film in Blender 4.3+.

The animation is imported from simulate.py. No mechanical event is scheduled here.
Camera choreography is the only time-directed animation in this file.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Quaternion

ROOT = Path(__file__).resolve().parents[1]
TAU = 2 * math.pi
M = {}


def material(name, color, metallic=0, roughness=.4):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = roughness
    m.diffuse_color = (*color, 1)
    return m


def make_materials():
    M['brass'] = material('01 | Satin champagne brass', (.58, .36, .12), .8, .25)
    M['gold'] = material('02 | Polished edges', (.82, .58, .26), .87, .2)
    M['darkmetal'] = material('03 | Gunmetal bearings', (.035, .055, .058), .75, .27)
    M['steel'] = material('04 | Mirror-polished steel', (.57, .64, .69), .96, .12)
    M['ivory'] = material('05 | Warm porcelain inlay', (.76, .72, .56), .15, .36)
    M['teal'] = material('06 | Deep petrol enamel', (.018, .09, .09), .4, .25)
    M['flag'] = material('07 | Oxblood silk', (.26, .024, .026), .05, .64)
    M['cord'] = material('08 | Braided ivory cord', (.61, .52, .32), .08, .73)
    M['black'] = material('09 | Engraved lettering', (.007, .012, .013), .15, .46)
    M['floor'] = material('10 | Teal studio sweep', (.017, .035, .04), .12, .42)
    M['felt'] = material('11 | Charcoal felt stops', (.025, .032, .03), 0, .86)
    for key, dark, light in [
        ('wood', (.028,.008,.004), (.15,.048,.016)),
        ('woodlight', (.065,.021,.007), (.28,.115,.036)),
    ]:
        m = material('12 | Quarter-sawn walnut' if key=='wood' else '13 | Honey walnut', light, 0, .32)
        nodes=m.node_tree.nodes; links=m.node_tree.links
        tex=nodes.new('ShaderNodeTexCoord')
        mapping=nodes.new('ShaderNodeVectorMath'); mapping.operation='MULTIPLY'
        mapping.inputs[1].default_value=(1.8, 35.0, 8.0)
        noise=nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=2.2
        noise.inputs['Detail'].default_value=3.0; noise.inputs['Roughness'].default_value=.62
        ramp=nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position=.24; ramp.color_ramp.elements[0].color=(*dark,1)
        ramp.color_ramp.elements[1].position=.78; ramp.color_ramp.elements[1].color=(*light,1)
        bump=nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.13; bump.inputs['Distance'].default_value=.035
        links.new(tex.outputs['Generated'], mapping.inputs[0]); links.new(mapping.outputs[0],noise.inputs['Vector'])
        links.new(noise.outputs['Fac'],ramp.inputs[0]); links.new(ramp.outputs[0],nodes.get('Principled BSDF').inputs['Base Color'])
        links.new(noise.outputs['Fac'],bump.inputs['Height']); links.new(bump.outputs[0],nodes.get('Principled BSDF').inputs['Normal'])
        M[key]=m
    # Woven rather than glossy flag surface.
    n=M['flag'].node_tree.nodes; l=M['flag'].node_tree.links
    tex=n.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value=170
    bump=n.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.12; bump.inputs['Distance'].default_value=.009
    l.new(tex.outputs['Fac'],bump.inputs['Height']); l.new(bump.outputs[0],n.get('Principled BSDF').inputs['Normal'])


def finish(o, name, mat=None, parent=None, bevel=0, smooth=False):
    o.name = name
    if mat: o.data.materials.append(M[mat] if isinstance(mat,str) else mat)
    if bevel:
        b=o.modifiers.new('Machined edge / soft highlight','BEVEL'); b.width=bevel; b.segments=3
        b.affect='EDGES'
        norm=o.modifiers.new('Weighted corner normals','WEIGHTED_NORMAL'); norm.keep_sharp=True; norm.weight=40
    if smooth and hasattr(o.data,'polygons'):
        for p in o.data.polygons:p.use_smooth=True
    if parent:o.parent=parent
    return o


def empty(name, pos=(0,0,0)):
    o=bpy.data.objects.new(name,None); bpy.context.collection.objects.link(o); o.location=pos
    return o


def box(name, pos, size, mat, bevel=.025, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1,location=pos)
    o=bpy.context.object; o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return finish(o,name,mat,parent,bevel)


def sphere(name,pos,r,mat,parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=r,location=pos)
    return finish(bpy.context.object,name,mat,parent,smooth=True)


def cylinder(name,pos,r,depth,mat,axis='Z',parent=None,vertices=48,bevel=.014):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=r,depth=depth,location=pos)
    o=bpy.context.object
    if axis=='Y':o.rotation_euler[0]=math.pi/2
    if axis=='X':o.rotation_euler[1]=math.pi/2
    return finish(o,name,mat,parent,bevel,smooth=True)


def rod(name,a,b,r,mat,parent=None):
    a,b=Vector(a),Vector(b)
    o=cylinder(name,(a+b)/2,r,(b-a).length,mat,parent=parent,bevel=min(.01,r*.22))
    o.rotation_mode='QUATERNION'; o.rotation_quaternion=(b-a).to_track_quat('Z','Y')
    return o


def tube(name,points,r,mat,parent=None):
    curve=bpy.data.curves.new(name,'CURVE'); curve.dimensions='3D';curve.resolution_u=1
    curve.bevel_depth=r;curve.bevel_resolution=3;curve.resolution_u=1
    spl=curve.splines.new('POLY');spl.points.add(len(points)-1)
    for p,co in zip(spl.points,points):p.co=(*co,1)
    o=bpy.data.objects.new(name,curve);bpy.context.collection.objects.link(o)
    return finish(o,name,mat,parent)


def ring(name,pos,major,minor,mat,axis='Z',parent=None):
    bpy.ops.mesh.primitive_torus_add(major_segments=64,minor_segments=12,location=pos,major_radius=major,minor_radius=minor)
    o=bpy.context.object
    if axis=='Y':o.rotation_euler[0]=math.pi/2
    if axis=='X':o.rotation_euler[1]=math.pi/2
    return finish(o,name,mat,parent,smooth=True)


def text_obj(name,body,pos,size,mat='gold',rot=(math.pi/2,0,0),align='CENTER',parent=None,font='sans'):
    c=bpy.data.curves.new(name,'FONT');c.body=body;c.align_x=align;c.align_y='CENTER';c.size=size
    c.extrude=.0005;c.bevel_depth=.0003;c.space_character=1.15
    fontpaths={'sans':'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','serif':'/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf','bold':'/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'}
    if Path(fontpaths[font]).exists():c.font=bpy.data.fonts.load(fontpaths[font],check_existing=True)
    o=bpy.data.objects.new(name,c);bpy.context.collection.objects.link(o);o.location=pos;o.rotation_euler=rot
    return finish(o,name,mat,parent)


def screw(name,pos,axis='Z',r=.055,parent=None):
    cylinder(name,pos,r,.025,'gold',axis,parent,vertices=20,bevel=.003)
    if axis=='Z':
        box(name+' slot',(pos[0],pos[1],pos[2]+.014),(r*1.25,.012,.006),'darkmetal',.002,parent)
    else:
        box(name+' slot',(pos[0],pos[1]-.016,pos[2]),(r*1.25,.006,.012),'darkmetal',.002,parent)


def lathe(name,profile,mat,parent=None,segments=80):
    verts=[];faces=[]
    for z,r in profile:
        for i in range(segments):
            a=TAU*i/segments;verts.append((r*math.cos(a),r*math.sin(a),z))
    for j in range(len(profile)-1):
        for i in range(segments):
            k=j*segments+i;kn=j*segments+(i+1)%segments
            faces.append((k,kn,kn+segments,k+segments))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    o=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(o)
    return finish(o,name,mat,parent,smooth=True)


def gear(name,center,pitch,teeth,depth=.14,parent=None,phase=0):
    """Matching module, involute flanks, a real toothed rim and open spokes."""
    root=pitch-1.25*(2*pitch/teeth);outer=pitch+2*pitch/teeth
    base=pitch*math.cos(math.radians(20));half=math.pi/(2*teeth)
    invp=math.tan(math.acos(base/pitch))-math.acos(base/pitch)
    outline=[]
    for n in range(teeth):
        a=TAU*n/teeth+phase
        outline.append((root,a-math.pi/teeth))
        for r in [root,max(root,base),pitch,outer]:
            inv=0 if r<=base else math.tan(math.acos(base/r))-math.acos(base/r)
            outline.append((r,a-half-invp+inv))
        for r in [outer,pitch,max(root,base),root]:
            inv=0 if r<=base else math.tan(math.acos(base/r))-math.acos(base/r)
            outline.append((r,a+half+invp-inv))
        outline.append((root,a+math.pi/teeth))
    inner=max(.22,root-.17);N=len(outline);verts=[];faces=[]
    for y,innerflag in [(-depth/2,False),(depth/2,False),(-depth/2,True),(depth/2,True)]:
        for r,a in outline:
            rr=inner if innerflag else r;verts.append((rr*math.cos(a),y,rr*math.sin(a)))
    for i in range(N):
        j=(i+1)%N
        faces.extend([(i,j,j+N,i+N),(i+2*N,i+3*N,j+3*N,j+2*N),(i,i+2*N,j+2*N,j),(i+N,j+N,j+3*N,i+3*N)])
    mesh=bpy.data.meshes.new(name+' involute');mesh.from_pydata(verts,[],faces);mesh.update()
    group=empty(name,center)
    o=bpy.data.objects.new(name+' rim',mesh);bpy.context.collection.objects.link(o);finish(o,o.name,'brass',group,.008)
    cylinder(name+' hub',(0,0,0),.18,depth*1.7,'gold','Y',group)
    for i in range(5):
        a=TAU*i/5
        p=((inner+.08)/2*math.cos(a),0,(inner+.08)/2*math.sin(a))
        b=box(name+' spoke',p,(inner-.08,.10,.095),'brass',.02,group);b.rotation_euler[1]=-a
    cylinder(name+' bearing',(0,-depth*.95,0),.095,.06,'darkmetal','Y',group)
    screw(name+' axle',(0,-depth*1.18,0),'Y',.06,group)
    if parent:group.parent=parent
    return group


def build_static(track):
    # Floating walnut instrument case with continuous brass pinstripes.
    box('Walnut instrument plinth',(0,0,.28),(15.4,5.9,.56),'wood',.16)
    box('Lower shadow reveal',(0,0,.07),(15.1,5.6,.12),'darkmetal',.08)
    box('Top brass reveal',(0,0,.57),(15.12,5.62,.055),'brass',.09)
    box('Walnut upper deck',(0,0,.65),(15.03,5.53,.15),'wood',.09)
    for x in [-6.7,6.7]:
        for y in [-2.1,2.1]:
            cylinder('Turned brass foot',(x,y,-.08),.27,.25,'brass',bevel=.03)
            cylinder('Felt under foot',(x,y,-.21),.24,.04,'felt',bevel=.012)
    # A brass-edged elevated lane ensures the ball and dominoes share a surface.
    box('Domino runway brass edge',(-1.5,-1.3,.91),(6.6,1.1,.16),'brass',.06)
    box('Domino runway walnut',(-1.5,-1.3,1.015),(6.53,1.02,.17),'woodlight',.055)
    for x in [-4.45,1.42]:
        for y in [-1.66,-.94]:screw('Runway fixing',(x,y,1.106),r=.038)
    # Thin architectural supports leave the moving marble visible.
    rail_offset=math.sqrt((.21+.055)**2-.14**2)
    for sign in [-1,1]:
        pts=[]
        for i,p in enumerate(track):
            a=Vector(track[max(0,i-1)]);b=Vector(track[min(len(track)-1,i+1)])
            tangent=b-a;n=Vector((-tangent.y,tangent.x,0)).normalized()
            v=Vector(p)+sign*.14*n;v.z-=rail_offset
            pts.append(tuple(v))
        tube('Continuous spiral rail '+str(sign),pts,.055,'gold')
    # Rail sleepers at even intervals, all physically beneath the rolling sphere.
    for i in range(0,len(track)-25,max(1,len(track)//52)):
        p=Vector(track[i]);prev=Vector(track[max(0,i-1)]);nxt=Vector(track[min(len(track)-1,i+1)])
        v=nxt-prev;n=Vector((-v.y,v.x,0)).normalized()
        a=p+.23*n; b=p-.23*n;a.z-=rail_offset+.06;b.z-=rail_offset+.06
        rod('Rail tie',a,b,.025,'darkmetal')
    # Three open-frame posts behind the helix.
    for angle in [.15,1.9,3.3]:
        x=-5+1.93*math.cos(angle);y=.25+1.93*math.sin(angle)
        cylinder('Spiral support socket',(x,y,.82),.16,.18,'brass')
        rod('Slender walnut upright',(x,y,.82),(x,y,4.9),.07,'woodlight')
        cylinder('Spiral post cap',(x,y,4.93),.10,.09,'gold')
        sphere('Post finial',(x,y,5.01),.07,'gold')
        # Clamp arms land at the actual track coordinates nearest this azimuth.
        candidates=[]
        for p in track:
            if p[0]>-3.4:continue
            az=math.atan2(p[1]-.25,p[0]+5)
            if abs(math.atan2(math.sin(az-angle),math.cos(az-angle)))<.025:candidates.append(p)
        chosen=[]
        for p in candidates:
            if not chosen or abs(p[2]-chosen[-1][2])>.45:chosen.append(p)
        for p in chosen:
            z=p[2]-rail_offset-.10
            rod('Rail bracket',(x,y,z),(p[0],p[1],z),.045,'brass')
            ring('Post clamp',(x,y,z),.083,.025,'gold')
    # Small inset station markers on the plinth, no floating UI.
    labels=[(-5.1,'01','THE DESCENT'),(-1.2,'02','FIVE FALLS'),(2.1,'03 / 04','THE DRIVE'),(5.5,'05 / 06','THE REWARD')]
    for x,num,title in labels:
        box('Inset station plate',(x,-2.28,.744),(2.65,.62,.018),'teal',.04)
        text_obj('Station number',num,(x,-2.25,.757),.105,'gold',rot=(0,0,0))
        text_obj('Station legend',title,(x,-2.46,.757),.075,'ivory',rot=(0,0,0))
    box('Maker plaque',(0,-2.962,.31),(3.55,.026,.29),'brass',.025)
    text_obj('Maker name','R O L L I N G   B A L L',(0,-2.982,.32),.125,'black')
    for x in [-1.63,1.63]:screw('Plaque screw',(x,-2.984,.31),'Y',.035)
    box('Studio ground',(0,0,-.30),(200,200,.10),'floor',.01)
    # A continuous curved sweep removes the horizon line during low close-ups.
    profile=[(-60,-.24),(6,-.24)]
    for i in range(1,49):
        a=(math.pi/2)*i/48;profile.append((6+8*math.sin(a),7.76-8*math.cos(a)))
    profile.append((14,45))
    verts=[(x,y,z) for x in [-70,70] for y,z in profile];n=len(profile)
    faces=[(i,i+n,i+1+n,i+1) for i in range(n-1)]
    mesh=bpy.data.meshes.new('Seamless cyclorama');mesh.from_pydata(verts,[],faces);mesh.update()
    sweep=bpy.data.objects.new('Seamless curved studio sweep',mesh);bpy.context.collection.objects.link(sweep);finish(sweep,sweep.name,'floor',smooth=True)


def build_dominoes():
    result=[]
    xs=[-2.7,-1.87,-1.04,-.21,.62]
    for i,x in enumerate(xs):
        root=empty(f'Domino {i+1} / contact-driven hinge',(x+.09,-1.3,1.1))
        box(f'Domino {i+1} walnut',(-.09,0,.675),(.18,.62,1.35),'woodlight',.045,root)
        # Bright edges on the camera-facing sides show every separate block.
        box('Domino brass perimeter',(-.092,-.319,.675),(.13,.018,1.22),'brass',.018,root)
        box('Domino enamel inset',(-.092,-.332,.675),(.08,.008,1.1),'teal',.012,root)
        # Pips on broad faces. Their plane faces the oncoming ball (negative X).
        for z in [.35,.97]:
            for y in [-.16,.16]:cylinder('Ivory domino pip',(-.184,y,z),.046,.009,'ivory','X',root,vertices=20,bevel=.002)
        box('Domino waist',(-.186,0,.675),(.01,.50,.014),'brass',.003,root)
        rod('Domino brass hinge',(0,-.37,0),(0,.37,0),.035,'gold',root)
        for y in [-1.69,-.91]:
            box('Domino hinge shoe',(x+.09,y,1.14),(.13,.08,.09),'darkmetal',.015)
            screw('Hinge shoe screw',(x+.09,y,1.191),r=.023)
        stop_angle=1.22; contact_height=.5; stop_radius=.075
        sx=x+.09+contact_height*math.sin(stop_angle)+stop_radius*math.cos(stop_angle)
        sz=1.1+contact_height*math.cos(stop_angle)-stop_radius*math.sin(stop_angle)
        cylinder('Felt-lined mechanical domino stop',(sx,-1.3,sz),stop_radius,.65,'felt','Y',bevel=.006)
        for yy in [-1.64,-.96]:
            box('Domino stop bracket',(sx,yy,(1.1+sz)/2),(.13,.065,sz-1.1+.02),'brass',.012)
        result.append(root)
    return result


def look_at(obj,target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()


def configure_scene(width,height,samples):
    s=bpy.context.scene;s.render.engine='CYCLES'
    s.cycles.samples=samples;s.cycles.use_denoising=False
    s.cycles.use_adaptive_sampling=True;s.cycles.adaptive_threshold=.06
    s.cycles.adaptive_min_samples=8
    s.cycles.max_bounces=6;s.cycles.diffuse_bounces=3;s.cycles.glossy_bounces=4
    s.cycles.transmission_bounces=3;s.cycles.transparent_max_bounces=4
    s.cycles.sample_clamp_indirect=3
    s.render.use_persistent_data=True
    s.render.resolution_x=width;s.render.resolution_y=height;s.render.resolution_percentage=100
    s.render.fps=24;s.frame_start=1;s.frame_end=600
    s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGB';s.render.image_settings.color_depth='8'
    s.render.film_transparent=False
    s.render.image_settings.compression=25
    s.world.color=(.15,.15,.15);s.world.use_nodes=True
    bg=s.world.node_tree.nodes.get('Background');bg.inputs[0].default_value=(.13,.20,.24,1);bg.inputs[1].default_value=.35
    s.view_settings.view_transform='AgX';s.view_settings.look='AgX - Medium High Contrast';s.view_settings.exposure=-.15
    # Large soft sources create useful moving reflections on the steel and brass.
    for name,pos,target,power,color,size,shape,sy in [
        ('Warm key / silkbox',(-4,-5,10),(-2,0,2),2300,(1,.82,.60),7,'DISK',7),
        ('Cool rim / strip',(2,4,8),(1,0,2.5),2700,(.52,.76,1),7,'RECTANGLE',3),
        ('Long front reflection',(0,-7,5),(0,0,2.5),1450,(1,.91,.76),10,'RECTANGLE',2),
        ('Bell jewel rim',(7,1,7),(4,0,3),1200,(1,.66,.32),4,'DISK',4),
        ('Spiral edge',(-9,1,6),(-5,0,3),950,(.62,.81,1),4,'RECTANGLE',5),
    ]:
        d=bpy.data.lights.new(name,'AREA');d.energy=power;d.color=color;d.shape=shape;d.size=size
        if shape=='RECTANGLE':d.size_y=sy
        o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=pos;look_at(o,target)
    d=bpy.data.cameras.new('Cinema / continuous dolly');o=bpy.data.objects.new('Cinema / continuous dolly',d);bpy.context.collection.objects.link(o)
    s.camera=o;d.sensor_width=36;d.lens=45;d.clip_end=300;d.dof.use_dof=False
    return s,o


def build_drive(geometry):
    objects={}
    # Three rear posts and open horizontal rails support every working axle.
    for x,z in [(1.35,4.65),(4.68,4.65),(6.65,4.65)]:
        box('Machinery pedestal',(x,.95,.85),(.58,.65,.25),'brass',.055)
        box('Walnut frame upright',(x,.95,(.97+z)/2),(.23,.30,z-.97),'wood',.045)
        box('Brass upright face',(x,.782,(.97+z)/2),(.10,.025,z-.97-.22),'brass',.015)
        box('Brass post capital',(x,.95,z),(.36,.43,.16),'brass',.035)
        sphere('Frame finial',(x,.95,z+.15),.075,'gold')
    box('Upper frame crossbeam',(4.0,.95,4.63),(5.55,.31,.20),'wood',.055)
    box('Upper beam gold line',(4.0,.778,4.63),(5.35,.025,.045),'gold',.01)
    box('Axle support crossbeam',(3.0,.95,3.60),(3.4,.28,.25),'wood',.035)
    box('Bell and flag bearing beam',(5.665,.95,4.18),(2.20,.28,.22),'wood',.035)
    for x in [5.62,6.30]:
        cylinder('Upper bearing backplate',(x,.785,4.18),.15,.05,'brass','Y')
        for dx in [-.10,.10]:screw('Upper bearing screw',(x+dx,.75,4.18),'Y',.024)
    for x in [2.4,3.84]:
        cylinder('Rear bearing plate',(x,.775,3.60),.22,.05,'brass','Y')
        rod('Gear through-shaft',(x,1.12,3.60),(x,-.40,3.60),.07,'darkmetal')
        for dx in [-.13,.13]:screw('Bearing plate screw',(x+dx,.737,3.60),'Y',.03)
    # The spool and gear share one rigid axle.
    objects['gear1']=gear('28 tooth driving gear',(2.4,-.12,3.6),.84,28,phase=0)
    objects['gear2']=gear('20 tooth driven gear',(3.84,-.12,3.6),.60,20,phase=math.pi/20)
    spool=empty('Cord drum / driving axle',(2.4,.60,3.6));objects['spool']=spool
    cylinder('Cord drum',(0,0,0),.332,.29,'woodlight','Y',spool)
    for y in [-.17,.17]:cylinder('Drum flange',(0,y,0),.40,.045,'brass','Y',spool)
    # A few real turns around the drum show where its length is stored.
    coils=[]
    for i in range(241):
        a=TAU*3*i/240;coils.append((.355*math.cos(a),-.12+.24*i/240,.355*math.sin(a)))
    objects['windings']=tube('Stored rope / conserved payout',coils,.018,'cord')
    objects['cord']=rod('Taut payout cord',(2.05,.60,3.60),(2.05,.60,3.12),.018,'cord')
    # High-friction viscous governor explains the deliberate counterweight speed.
    cylinder('Rotary damper housing',(2.4,1.23,3.60),.43,.22,'teal','Y')
    ring('Damper brass rim',(2.4,1.10,3.60),.405,.032,'gold','Y')
    cylinder('Damper axle',(2.4,1.40,3.6),.14,.15,'brass','Y')
    for a in [0,math.pi/2,math.pi,3*math.pi/2]:
        screw('Damper case screw',(2.4+.31*math.cos(a),1.10,3.6+.31*math.sin(a)),'Y',.031)
    # Counterweight slides, with ample travel to the felt-cushioned bottom stop.
    for x in [1.58,2.52]:
        rod('Counterweight guide',(x,.82,.76),(x,.82,3.35),.035,'steel')
        for z in [1.13,3.35]:
            cylinder('Guide collar',(x,.82,z),.09,.12,'brass')
        cylinder('Guide foot',(x,.82,.79),.13,.12,'brass')
        rod('Guide support top',(x,.82,3.35),(x,.95,3.35),.055,'brass')
    box('Weight buffer pedestal',(2.05,.60,.935),(.62,.56,.41),'wood',.045)
    box('Weight bottom buffer',(2.05,.60,1.215),(.70,.65,.15),'brass',.035)
    box('Weight felt arrestor',(2.05,.60,1.300),(.57,.46,.035),'felt',.02)
    weight=empty('Released counterweight',(2.05,.60,2.85));objects['weight']=weight
    box('Counterweight brass',(0,0,0),(.52,.42,.50),'brass',.06,weight)
    box('Square counterweight sear contact shoe',(.235,0,-.23),(.05,.12,.04),'brass',.001,weight)
    box('Counterweight enamel band',(0,-.219,0),(.33,.018,.31),'teal',.025,weight)
    text_obj('Weight engraving','W',(0,-.237,0),.18,'gold',parent=weight,font='serif')
    for x in [-.47,.47]:
        cylinder('Guide bearing on weight',(x,.22,0),.078,.19,'darkmetal',parent=weight)
        box('Weight guide ear',(x/2,.22,0),(.50,.10,.11),'brass',.02,weight)
    ring('Counterweight rope eye',(0,0,.29),.065,.022,'gold','Y',weight)
    trip=empty('Domino-operated release shaft',(2.4,0,2.65));objects['trip']=trip
    rod('Release through-shaft',(0,-1.40,0),(0,.75,0),.055,'steel',trip)
    rod('Trip arm',(0,-1.30,0),(-.82,-1.30,-.61),.055,'brass',trip)
    cylinder('Domino contact paddle',(-.82,-1.30,-.61),.10,.26,'brass','Y',trip)
    # The leftmost top corner IS the contact point in the numerical solver.
    # A thick cylinder here would falsely remain under the weight after release.
    poly=[(-.10,-.05),(-.015,.008),(.03,-.025),(-.10,-.065)]
    verts=[(x,y,z) for y in [.54,.66] for x,z in poly]
    faces=[(0,3,2,1),(4,5,6,7)]+[(i,(i+1)%4,(i+1)%4+4,i+4) for i in range(4)]
    mesh=bpy.data.meshes.new('Sear blade');mesh.from_pydata(verts,[],faces);mesh.update()
    blade=bpy.data.objects.new('Counterweight sear / true clearing edge',mesh);bpy.context.collection.objects.link(blade);finish(blade,blade.name,'brass',trip,.002)
    for y in [-.85,.91]:
        cylinder('Release shaft bearing',(2.4,y,2.65),.13,.10,'brass','Y')
        rod('Bearing upright',(2.4,y,.73),(2.4,y,2.65),.055,'darkmetal')
        cylinder('Bearing upright foot',(2.4,y,.78),.14,.10,'brass')
    # The crank extends from the output gear face into the linkage plane.
    crank=empty('Output crank',(3.84,-.65,3.6));objects['crank']=crank
    cylinder('Crank shaft',(0,.22,0),.075,.58,'steel','Y',crank)
    rod('Crank cheek',(0,0,0),(.25,0,0),.065,'brass',crank)
    cylinder('Crank connecting pin',(.25,-.06,0),.065,.30,'steel','Y',crank)
    objects['coupler']=rod('Crank to rocker connecting rod',(3.6,-.65,3.4),(4.3,-.65,3.9),.040,'brass')
    # Small hammer: brass rocker, walnut handle and dark polished steel head.
    hammer=empty('Crank-driven hammer',(4.70,-.65,4.05));objects['hammer']=hammer
    rod('Hammer handle',(0,0,0),(.85,0,0),.048,'woodlight',hammer)
    rod('Hammer brass reinforcement',(0,0,0),(.40,0,0),.064,'brass',hammer)
    cylinder('Hammer pivot',(0,0,0),.105,.22,'brass','Y',hammer)
    cylinder('Hammer connecting pin',(.38,-.06,0),.066,.30,'steel','Y',hammer)
    sphere('Hammer striking head',(.85,0,0),.12,'darkmetal',hammer)
    cylinder('Hammer cross-peen',(.85,0,0),.095,.25,'darkmetal','Y',hammer,bevel=.025)
    for y in [-.10,.10]:ring('Hammer face rim',(.85,y,0),.08,.015,'brass','Y',hammer)
    ring('Hammer ferrule',(.73,0,0),.064,.017,'gold','X',hammer)
    rod('Rocker supporting axle',(4.7,-.85,4.05),(4.7,.95,4.05),.058,'steel')
    cylinder('Rocker front cap',(4.7,-.83,4.05),.095,.05,'gold','Y')
    # Turned bell: true hollow wall, lip and interior; entire bell is on one hinge.
    bell=empty('Impact-driven bell yoke',(5.62,-.65,4.18));objects['bell']=bell
    outer=list(reversed(geometry['bell_profile']))
    profile=outer+[(-.875,.34),(-.875,.312)]+[(z,max(.02,r-.028)) for z,r in reversed(outer)]
    lathe('Spun bronze bell',profile,'gold',bell)
    ring('Bell lip bead',(0,0,-.858),.327,.013,'brass',parent=bell)
    ring('Bell shoulder bead',(0,0,-.30),.122,.008,'brass',parent=bell)
    rod('Bell crown shank',(0,0,-.18),(0,0,.0),.052,'brass',bell)
    box('Bell yoke',(0,0,0),(.26,.17,.10),'brass',.025,bell)
    rod('Bell suspension axle',(5.62,-.85,4.18),(5.62,.95,4.18),.048,'steel')
    cylinder('Bell pivot cap',(5.62,-.84,4.18),.085,.07,'gold','Y')
    rod('Bell release tab',(0,0,0),(.55,0,0),.035,'brass',bell)
    sphere('Bell tab roller',(.55,0,0),.048,'steel',bell)
    # The held flag is present in the scene from frame one.
    flag=empty('Spring flag hinge',(6.30,-.65,4.18));objects['flag']=flag
    rod('Flagpole',(0,0,0),(.9,0,0),.025,'gold',flag)
    sphere('Flagpole finial',(.94,0,0),.055,'gold',flag)
    cylinder('Flag hinge cartridge',(0,0,0),.14,.19,'teal','Y',flag)
    spring=[]
    for i in range(141):
        a=TAU*4*i/140;spring.append((.11*math.cos(a),-.11+.22*i/140,.11*math.sin(a)))
    tube('Preloaded torsion spring',spring,.016,'gold',flag)
    rod('Flag fixed axle',(6.30,-.90,4.18),(6.30,.95,4.18),.048,'steel')
    # Silk shape is gently scalloped, with no teleporting or scale reveal.
    verts=[];faces=[];nx=24;ny=8
    for j in range(ny+1):
        height=.44+.44*j/ny
        for i in range(nx+1):
            width=.04+1.03*i/nx
            ripple=.025*math.sin(i/nx*TAU*1.4)*math.sin(i/nx*math.pi/2)
            verts.append((height,-.025+ripple,-width))
    for j in range(ny):
        for i in range(nx):
            k=j*(nx+1)+i;faces.append((k,k+1,k+nx+2,k+nx+1))
    mesh=bpy.data.meshes.new('Silk flag');mesh.from_pydata(verts,[],faces);mesh.update()
    cloth=bpy.data.objects.new('Oxblood SUCCESS flag',mesh);bpy.context.collection.objects.link(cloth);finish(cloth,cloth.name,'flag',flag,smooth=True)
    sol=cloth.modifiers.new('Silk thickness','SOLIDIFY');sol.thickness=.005
    label=text_obj('SUCCESS — readable on final raised flag','SUCCESS',(.66,-.072,-.56),.165,'ivory',parent=flag,font='bold')
    from mathutils import Matrix
    label.rotation_euler=(Matrix.Rotation(math.pi/2,4,'Y')@Matrix.Rotation(math.pi/2,4,'X')).to_euler()
    # Gold stitched hems trace the panel in its folded and released configurations.
    for h in [.44,.88]:tube('Flag stitched hem',[(h,-.036,-.045),(h,-.036,-1.065)],.006,'gold',flag)
    pawl=empty('Flag retaining pawl',(6.43,-.65,4.25));objects['pawl']=pawl
    # Bell roller starts tangent to the paddle. The rising tab first lifts the
    # pawl, then the hook clears the flag notch at the solved release threshold.
    rod('Bell-contact flag catch',(-.26,0,0),(0,0,0),.022,'brass',pawl)
    rod('Flag retaining hook',(-.09,0,0),(-.09,0,-.05),.012,'brass',pawl)
    box('Flag notch lug',(.04,0,.012),(.04,.08,.025),'brass',.006,flag)
    cylinder('Pawl pivot',(0,0,0),.045,.13,'steel','Y',pawl)
    rod('Pawl support',(6.43,-.56,4.25),(6.43,.95,4.25),.025,'darkmetal')
    box('Pawl rear bracket',(6.43,.95,4.25),(.16,.20,.22),'brass',.025)
    return objects


def keyed(o,path,frame):
    o.keyframe_insert(data_path=path,frame=frame)


def pose_rod(o,a,b,original_length):
    a,b=Vector(a),Vector(b)
    o.location=(a+b)/2
    o.rotation_mode='QUATERNION';o.rotation_quaternion=(b-a).to_track_quat('Z','Y')
    o.scale.z=(b-a).length/original_length


def bake_mechanics(data,dominoes,objects):
    marble=sphere('Steel marble / rolling without slip',data['frames'][0]['ball'],.21,'steel')
    # One fine steel seam helps reveal the real rolling orientation in reflections.
    ring('Marble fine equator',(0,0,0),.2102,.0017,'darkmetal',parent=marble)
    marble.rotation_mode='QUATERNION';q=Quaternion((1,0,0,0))
    prev=Vector(data['frames'][0]['ball']);prev_spin=0
    for index,state in enumerate(data['frames']):
        frame=index+1
        p=Vector(state['ball']);delta=p-prev;spin_delta=state['ball_spin']-prev_spin
        if delta.length>1e-8 and abs(spin_delta)>1e-9:
            axis=Vector((0,0,1)).cross(delta).normalized()
            q=Quaternion(axis,abs(spin_delta))@q
        marble.location=p;marble.rotation_quaternion=q
        keyed(marble,'location',frame);keyed(marble,'rotation_quaternion',frame)
        prev=p;prev_spin=state['ball_spin']
        for o,theta in zip(dominoes,state['domino_angles']):
            o.rotation_euler.y=theta;keyed(o,'rotation_euler',frame)
        for name,theta in [
            ('trip',state['trip_angle']),('gear1',-state['gear1_angle']),
            ('gear2',-state['gear2_angle']),('spool',-state['gear1_angle']),
            ('crank',-state['crank_phase']),('hammer',-state['hammer_angle']),
            ('bell',-state['bell_swing']),('flag',-state['flag_angle']),
        ]:
            objects[name].rotation_euler.y=theta;keyed(objects[name],'rotation_euler',frame)
        objects['weight'].location.z=state['weight_z'];keyed(objects['weight'],'location',frame)
        pose_rod(objects['cord'],(2.05,.60,3.60),(2.05,.60,state['weight_z']+.34),.48)
        # Standard pin stacking puts the rod in front of the crank/rocker, so
        # it can pass the shaft in projection without intersecting it in 3D.
        a=state['crank_pin'].copy();b=state['hammer_follower'].copy();a[1]=b[1]=-.80
        pose_rod(objects['coupler'],a,b,math.sqrt(.7**2+.5**2))
        for name in ['cord','coupler']:
            for path in ['location','rotation_quaternion','scale']:keyed(objects[name],path,frame)
        objects['pawl'].rotation_euler.y=math.asin(min(math.sin(.65),max(0,(state['bell_tab'][2]-4.18)/.26)))
        keyed(objects['pawl'],'rotation_euler',frame)
        # The actual wound rope shortens by exactly the payout of the falling weight.
        # Sampling this cosmetic curve at 12fps does not affect any mechanism state.
        if index%2==0 or index==len(data['frames'])-1:
            points=objects['windings'].data.splines[0].points
            remaining=TAU*3-state['gear1_angle']
            for j,pt in enumerate(points):
                u=j/(len(points)-1);a=math.pi-u*remaining
                pt.co=(2.4+.35*math.cos(a),.60+.12*u,3.6+.35*math.sin(a),1)
                pt.keyframe_insert(data_path='co',frame=frame)
    # Linear interpolation preserves the sampled numerical trajectory exactly.
    for action in bpy.data.actions:
        for curve in action.fcurves:
            for point in curve.keyframe_points:point.interpolation='LINEAR'
    return marble


def interpolate_waypoints(points,t):
    """C1-continuous Hermite camera path with tangents in seconds."""
    if t<=points[0][0]:return Vector(points[0][1])
    if t>=points[-1][0]:return Vector(points[-1][1])
    for i in range(len(points)-1):
        t0,p0=points[i];t1,p1=points[i+1]
        if t0<=t<=t1:break
    p0,p1=Vector(p0),Vector(p1);duration=t1-t0;u=(t-t0)/duration
    before=points[max(0,i-1)];after=points[min(len(points)-1,i+2)]
    m0=(p1-Vector(before[1]))/(t1-before[0]) if i else (p1-p0)/duration*.25
    m1=(Vector(after[1])-p0)/(after[0]-t0) if i+2<len(points) else (p1-p0)/duration*.25
    return (2*u**3-3*u**2+1)*p0+(u**3-2*u**2+u)*duration*m0+(-2*u**3+3*u**2)*p1+(u**3-u**2)*duration*m1


def bake_camera(data,cam):
    ev={e['name']:e['time'] for e in data['events']}
    impact=ev['domino_1_impact'];latch=ev['latch_release'];bell=ev['bell_strike'];flag=ev['flag_settled']
    # The narrative framing is derived from solved contact times.
    poses=[
        (0,(-2,-22,11),(-.2,0,2.4),43),
        (2.8,(-8.4,-13.8,8.6),(-4.8,.1,3.3),48),
        (6.3,(-8.4,-10.8,6.2),(-4.7,-.05,2.8),48),
        (impact-1.0,(-4.0,-11,5.5),(-2.7,-.6,1.95),49),
        (impact+.5,(-1.7,-9.4,4.4),(-.8,-.8,1.85),48),
        (latch+.3,(3.3,-9.2,4.8),(1.3,-.25,2.2),50),
        (latch+2.1,(4.9,-10.4,5.7),(3.6,0,3.3),52),
        (bell-.5,(6.4,-9.7,5.2),(4.85,-.25,3.7),58),
        (flag+.6,(7.3,-9.0,5.3),(5.6,-.3,4.0),58),
        (min(flag+2.0,21.6),(7.5,-9.3,5.5),(5.65,-.3,4.0),58),
        (23.8,(8,-21,11.8),(-.1,0,2.4),43),
        (25,(8.7,-22,12.3),(0,0,2.4),43),
    ]
    poses.sort(key=lambda x:x[0])
    position=[(x[0],x[1]) for x in poses];target=[(x[0],x[2]) for x in poses];lenses=[(x[0],(x[3],0,0)) for x in poses]
    for i in range(600):
        t=i/24;cam.location=interpolate_waypoints(position,t);look_at(cam,interpolate_waypoints(target,t))
        cam.data.lens=interpolate_waypoints(lenses,t).x
        keyed(cam,'location',i+1);keyed(cam,'rotation_euler',i+1);keyed(cam.data,'lens',i+1)
    for action in bpy.data.actions:
        for curve in action.fcurves:
            for point in curve.keyframe_points:point.interpolation='LINEAR'
    return poses


def main():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation',default=str(ROOT/'data/simulation.json'))
    parser.add_argument('--output',default=str(ROOT/'scene/Rolling-Ball.blend'))
    parser.add_argument('--width',type=int,default=1920);parser.add_argument('--height',type=int,default=1080)
    parser.add_argument('--samples',type=int,default=32)
    parser.add_argument('--preview-frames',default='')
    parser.add_argument('--preview-dir',default=str(ROOT/'preview'))
    args=parser.parse_args(argv)
    data=json.loads(Path(args.simulation).read_text())
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    make_materials();build_static(data['track_path']);dominoes=build_dominoes();objects=build_drive(data['geometry'])
    scene,cam=configure_scene(args.width,args.height,args.samples)
    bake_mechanics(data,dominoes,objects);poses=bake_camera(data,cam)
    scene['production_title']='ROLLING BALL — a study in consequence'
    scene['mechanics']='Contact-driven constrained dynamics, no timed stage triggers'
    scene['duration_seconds']=25.0;scene['simulation_source']='data/simulation.json'
    for event in data['events']:
        scene.timeline_markers.new(event['name'],frame=round(event['time']*24)+1)
    scene.frame_set(1)
    scene.render.filepath='//../build/frames/frame_'
    # Fonts are packed: the editable film opens on another computer without missing assets.
    bpy.ops.file.pack_all()
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)
    (ROOT/'data/camera.json').write_text(json.dumps(poses,indent=2)+'\n')
    if args.preview_frames:
        dest=Path(args.preview_dir);dest.mkdir(parents=True,exist_ok=True)
        for f in map(int,args.preview_frames.split(',')):
            scene.frame_set(f);scene.render.filepath=str(dest/f'frame_{f:04d}.png')
            bpy.ops.render.render(write_still=True)
    print(json.dumps({'blend':str(out),'objects':len(bpy.data.objects),'frames':600,'duration':25}))


if __name__=='__main__':main()
