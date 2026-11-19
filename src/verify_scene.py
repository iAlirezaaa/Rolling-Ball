"""Read-only Blender adapter QA: compare the baked film to solved mechanics.

Run after build_scene.py:
  blender -b scene/Rolling-Ball.blend --python src/verify_scene.py
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation', default=str(ROOT / 'data/simulation.json'))
    parser.add_argument('--output', default=str(ROOT / 'data/scene-verification.json'))
    args = parser.parse_args(argv)
    data = json.loads(Path(args.simulation).read_text())
    scene = bpy.context.scene
    camera = scene.camera
    objects = bpy.data.objects
    errors = []
    maxima = {}
    projection_checks = []
    clipped = []

    def check_error(name, value, tolerance=2e-5):
        maxima[name] = max(maxima.get(name, 0.0), float(value))
        if value > tolerance and not any(e.get('check') == name for e in errors):
            errors.append({'check': name, 'frame': scene.frame_current, 'error': float(value), 'tolerance': tolerance})

    def project(label, frame, point, radius=0.0):
        scene.frame_set(frame)
        center = Vector(point)
        points = [center]
        if radius:
            # Camera-plane extrema of the actual projected sphere footprint.
            right = camera.matrix_world.to_quaternion() @ Vector((1, 0, 0))
            up = camera.matrix_world.to_quaternion() @ Vector((0, 1, 0))
            points += [center + right*radius, center-right*radius, center+up*radius, center-up*radius]
        coords = [world_to_camera_view(scene, camera, p) for p in points]
        inside = all(0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0 and p.z > 0.0 for p in coords)
        rec = {'label': label, 'frame': frame, 'time': (frame-1)/24,
               'inside': inside, 'center_ndc': list(coords[0]),
               'bounds': {'left': min(p.x for p in coords), 'right': max(p.x for p in coords),
                          'bottom': min(p.y for p in coords), 'top': max(p.y for p in coords)}}
        projection_checks.append(rec)
        if not inside:
            clipped.append(rec)

    names = {'ball': 'Steel marble / rolling without slip', 'head': 'Hammer striking head',
             'gear1': '28 tooth driving gear', 'gear2': '20 tooth driven gear',
             'spool': 'Cord drum / driving axle', 'weight': 'Released counterweight',
             'bell': 'Impact-driven bell yoke', 'flag': 'Spring flag hinge',
             'rod': 'Crank to rocker connecting rod', 'trip': 'Domino-operated release shaft'}
    ob = {k: objects[v] for k,v in names.items()}
    rod_zmin = min(v.co.z for v in ob['rod'].data.vertices)
    rod_zmax = max(v.co.z for v in ob['rod'].data.vertices)
    for state in data['frames']:
        scene.frame_set(state['frame'] + 1)
        check_error('marble_world_position', (ob['ball'].matrix_world.translation-Vector(state['ball'])).length)
        check_error('hammer_head_world_position', (ob['head'].matrix_world.translation-Vector(state['hammer_head'])).length)
        for key in ('gear1', 'gear2'):
            check_error(key+'_phase', abs(ob[key].rotation_euler.y + state[key+'_angle']))
        check_error('drum_phase', abs(ob['spool'].rotation_euler.y + state['gear1_angle']))
        check_error('trip_angle', abs(ob['trip'].rotation_euler.y-state['trip_angle']))
        check_error('weight_z', abs(ob['weight'].matrix_world.translation.z-state['weight_z']))
        for i,theta in enumerate(state['domino_angles']):
            check_error('domino_'+str(i+1)+'_angle', abs(objects[f'Domino {i+1} / contact-driven hinge'].rotation_euler.y-theta))
        a = ob['rod'].matrix_world @ Vector((0,0,rod_zmin))
        b = ob['rod'].matrix_world @ Vector((0,0,rod_zmax))
        check_error('connecting_rod_length', abs((b-a).length-.95))
        check_error('connecting_rod_front_layer', max(abs(a.y+.80),abs(b.y+.80)))
        check_error('connecting_rod_pin_xz', math.hypot(a.x-state['crank_pin'][0],a.z-state['crank_pin'][2]))
        check_error('connecting_rod_follower_xz', math.hypot(b.x-state['hammer_follower'][0],b.z-state['hammer_follower'][2]))
        bell_lip = ob['bell'].matrix_world @ Vector((-.34,0,-.85))
        check_error('bell_lip_world_position', (bell_lip-Vector(state['bell_lip'])).length)
        check_error('bell_swing', abs(ob['bell'].rotation_euler.y+state['bell_swing']))
        check_error('flag_hinge_angle', abs(ob['flag'].rotation_euler.y+state['flag_angle']))

    events = {e['name']:e for e in data['events']}
    impact_frame = min(600, math.ceil(events['domino_1_impact']['time']*24)+1)
    for frame in range(1, impact_frame+1):
        scene.frame_set(frame)
        project('marble_visible_through_descent', frame, ob['ball'].matrix_world.translation, .21)

    def frame_at(time):
        return min(600, max(1, round(time*24)+1))

    for i in range(1,6):
        event = events[f'domino_{i}_impact']
        frame = frame_at(event['time'])
        if i == 1:
            point = event['contact']
        else:
            state = data['frames'][frame-1]
            pivot = data['geometry']['domino_pivots'][i-2]
            theta = state['domino_angles'][i-2]
            point = [pivot[0]+1.35*math.sin(theta),-1.3,1.1+1.35*math.cos(theta)]
        project(f'domino_{i}_contact',frame,point,.04)

    frame = frame_at(events['latch_release']['time'])
    state = data['frames'][frame-1]
    project('sear_clears_counterweight',frame,state['sear_tip'],.04)
    project('counterweight_release_visible',frame,[2.05,.60,state['weight_z']],.15)
    for time in [events['gear_start']['time']+1.0, events['bell_strike']['time']-1.0]:
        frame = frame_at(time)
        for label,point in [('gear_mesh',[3.24,-.12,3.60]),('output_crank',data['frames'][frame-1]['crank_pin'])]:
            project(label,frame,point,.06)
    frame = frame_at(events['bell_strike']['time'])
    project('hammer_bell_contact',frame,data['frames'][frame-1]['hammer_head'],.12)
    frame = frame_at(events['flag_release']['time'])
    project('bell_tab_lifts_flag_pawl',frame,data['frames'][frame-1]['bell_tab'],.048)
    project('flag_hinge_releases',frame,[6.3,-.65,4.18],.14)
    frame = frame_at(events['flag_settled']['time'])
    scene.frame_set(frame)
    flag_text = objects['SUCCESS — readable on final raised flag']
    project('success_label',frame,flag_text.matrix_world.translation,.25)
    for frame in [frame, 480, 599, 600]:
        scene.frame_set(frame)
        for i,p in enumerate(objects['Oxblood SUCCESS flag'].bound_box):
            project('complete_success_flag_corner_'+str(i),frame,objects['Oxblood SUCCESS flag'].matrix_world @ Vector(p))

    metadata = {'frame_start': scene.frame_start, 'frame_end': scene.frame_end,
                'fps': scene.render.fps, 'fps_base': scene.render.fps_base,
                'duration_seconds': (scene.frame_end-scene.frame_start+1)/scene.render.fps*scene.render.fps_base,
                'resolution': [scene.render.resolution_x,scene.render.resolution_y],
                'flag_text': flag_text.data.body, 'scene_title': scene.get('production_title'),
                'mechanics': scene.get('mechanics'), 'blend': bpy.data.filepath}
    if metadata['duration_seconds'] != 25.0 or metadata['fps'] != 24 or flag_text.data.body != 'SUCCESS':
        errors.append({'check':'film_metadata','actual':metadata})
    if clipped:
        errors.append({'check':'camera_clipping','count':len(clipped)})
    report = {'status':'PASS' if not errors else 'FAIL', 'metadata':metadata,
              'pose_maximum_errors':maxima, 'camera_checks':len(projection_checks),
              'camera_clipped':clipped, 'errors':errors, 'camera_projections':projection_checks}
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'errors':errors,'camera_checks':len(projection_checks),'report':str(path)}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
