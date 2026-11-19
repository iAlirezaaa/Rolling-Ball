#!/usr/bin/env python3
"""Deterministic, contact-driven mechanics for the Rolling Ball film.

The Blender scene only plays samples produced here. There are no stage clocks:
gravity moves a rolling sphere, contact transfers angular momentum through five
hinged dominoes, the last domino rotates a rigid sear shaft, and a falling weight
drives a cord drum, gear pair, crank/rod/rocker and hammer. The struck bell's yoke
physically lifts a pawl, releasing a torsion-spring flag. A single global slow-
motion factor is used for the entire mechanism, including its gravity motion.

This is an intentionally reduced-order mechanical model (hinges, constrained
rolling, rigid gears/cord, local impact contacts), not a general rigid-body solver.
Dimensions are scene metres. Masses are effective lumped mechanism masses.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from pathlib import Path

PI = math.pi
G = 9.81
FPS = 24
DURATION = 25.0
DT = 1.0 / 1200.0

GEOMETRY = {
    "base_top": 0.6,
    "domino_surface": 1.1,
    "ball_radius": 0.21,
    "rail_radius": 0.055,
    "rail_half_spacing": 0.14,
    "spiral_center": [-5.0, 0.25],
    "spiral_radius": 1.55,
    "spiral_turns": 2,
    "spiral_start_z": 5.30,
    "spiral_end_z": 1.31,
    "domino_centers": [[x, -1.30, 1.775] for x in [-2.70, -1.87, -1.04, -0.21, 0.62]],
    "domino_pivots": [[x + 0.09, -1.30, 1.10] for x in [-2.70, -1.87, -1.04, -0.21, 0.62]],
    "domino_height": 1.35,
    "domino_thickness": 0.18,
    "domino_width": 0.62,
    "domino_stop_angle": 1.22,
    "trip_pivot": [2.40, -1.30, 2.65],
    "trip_rear_pivot": [2.40, 0.60, 2.65],
    "trip_arm_end": [1.58, -1.30, 2.04],
    "sear_tip_local": [-0.10, 0.0, -0.05],
    "weight_initial_center": [2.05, 0.60, 2.85],
    "weight_dimensions": [0.52, 0.42, 0.50],
    "weight_drop": 1.30,
    "spool_center": [2.40, 0.60, 3.60],
    "spool_radius": 0.35,
    "gear1_center": [2.40, -0.12, 3.60],
    "gear2_center": [3.84, -0.12, 3.60],
    "gear1_pitch_radius": 0.84,
    "gear2_pitch_radius": 0.60,
    "gear1_teeth": 28,
    "gear2_teeth": 20,
    "gear2_tooth_phase": PI / 20.0,
    "crank_radius": 0.25,
    "crank_initial_phase": 4.20,
    "linkage_y": -0.65,
    "hammer_pivot": [4.70, -0.65, 4.05],
    "hammer_follower_radius": 0.38,
    "connecting_rod_length": 0.95,
    "hammer_length": 0.85,
    "hammer_head_radius": 0.12,
    "bell_pivot": [5.62, -0.65, 4.18],
    "bell_lip_local": [-0.34, 0.0, -0.85],
    "bell_top_local_z": -0.18,
    "bell_bottom_local_z": -0.85,
    "bell_profile": [[-0.85, 0.34], [-0.78, 0.29], [-0.66, 0.23], [-0.50, 0.17], [-0.30, 0.13], [-0.18, 0.08]],
    "bell_tab_local": [0.55, 0.0, 0.0],
    "flag_pawl_contact_z": 4.23,
    "flag_pivot": [6.30, -0.65, 4.18],
    "flag_pole_length": 0.90,
    "flag_dimensions": [0.82, 0.43],
    "flag_text": "SUCCESS",
}


def rotate_y_xz(x: float, z: float, angle: float) -> tuple[float, float]:
    """Blender's positive Y rotation sends a vertical arm toward +X."""
    c, s = math.cos(angle), math.sin(angle)
    return x * c + z * s, -x * s + z * c


def make_track() -> tuple[list[list[float]], list[float]]:
    points = []
    taper = 0.15
    for i in range(2401):
        u = i / 2400.0
        angle = -PI / 2.0 - 4.0 * PI + 4.0 * PI * u
        if u <= 1.0 - taper:
            drop_fraction = u / (1.0 - taper / 2.0)
        else:
            v = u - (1.0 - taper)
            integral = 1.0 - taper + 0.5 * v + taper / (2.0 * PI) * math.sin(PI * v / taper)
            drop_fraction = integral / (1.0 - taper / 2.0)
        points.append([-5.0 + 1.55 * math.cos(angle),
                       0.25 + 1.55 * math.sin(angle),
                       5.30 - 3.99 * drop_fraction])
    # A straight tangent exit. The last spiral pitch is exactly horizontal.
    for i in range(1, 401):
        points.append([-5.0 + 2.0 * i / 400.0, -1.30, 1.31])
    arc = [0.0]
    for a, b in zip(points, points[1:]):
        arc.append(arc[-1] + math.dist(a, b))
    return points, arc


TRACK, TRACK_ARC = make_track()
TRACK_END = TRACK_ARC[-1]


def on_track(s: float) -> tuple[list[float], list[float]]:
    s = max(0.0, min(s, TRACK_END))
    i = max(0, min(len(TRACK_ARC) - 2, bisect.bisect_right(TRACK_ARC, s) - 1))
    length = TRACK_ARC[i + 1] - TRACK_ARC[i]
    f = (s - TRACK_ARC[i]) / length
    a, b = TRACK[i], TRACK[i + 1]
    return ([a[j] + f * (b[j] - a[j]) for j in range(3)],
            [(b[j] - a[j]) / length for j in range(3)])


def ball_acceleration(s: float, velocity: float) -> float:
    tangent = on_track(s)[1]
    # Rotational inertia of a solid sphere; small bearing/rolling resistance.
    drive = -G * tangent[2] / 1.4
    return drive - (0.012 * G if velocity > 0.0 else 0.0)


def arrival_time() -> float:
    s = v = t = 0.0
    while s < TRACK_END:
        v = max(0.0, v + ball_acceleration(s, v) * DT)
        s += v * DT
        t += DT
    return t


# One constant film-time dilation, calibrated from track geometry alone.
SLOW_MOTION = 10.0 / arrival_time()


def linkage(drop: float) -> dict:
    """Solve the exact two-circle intersection of a crank/rod/rocker linkage."""
    phase = GEOMETRY["crank_initial_phase"] - 4.0 * drop
    pin = [3.84 + 0.25 * math.cos(phase), -0.65, 3.60 + 0.25 * math.sin(phase)]
    hx, hz = 4.70, 4.05
    dx, dz = pin[0] - hx, pin[2] - hz
    distance = math.hypot(dx, dz)
    radius, rod = 0.38, 0.95
    value = (radius * radius + distance * distance - rod * rod) / (2.0 * radius * distance)
    if not -1.0 <= value <= 1.0:
        raise ValueError("Non-constructable four-bar linkage")
    alpha = math.atan2(dz, dx) + math.acos(value)
    follower = [hx + radius * math.cos(alpha), -0.65, hz + radius * math.sin(alpha)]
    head = [hx + 0.85 * math.cos(alpha), -0.65, hz + 0.85 * math.sin(alpha)]
    return {"crank_pin": pin, "hammer_follower": follower, "hammer_head": head,
            "hammer_angle": alpha, "crank_phase": phase}


def bell_point(angle: float, local: list[float]) -> list[float]:
    # Positive exported bell swing moves the bell to the right.
    dx, dz = rotate_y_xz(local[0], local[2], -angle)
    return [5.62 + dx, -0.65, 4.18 + dz]


def bell_contact(head: list[float], angle: float) -> tuple[list[float], list[float], float]:
    """Closest point on the actual lathed bell's left profile, in its swing plane."""
    hx, hz = rotate_y_xz(head[0] - 5.62, head[2] - 4.18, angle)
    best = None
    profile = GEOMETRY["bell_profile"]
    for (az, ar), (bz, br) in zip(profile, profile[1:]):
        ax, bx = -ar, -br
        vx, vz = bx - ax, bz - az
        u = max(0.0, min(1.0, ((hx - ax) * vx + (hz - az) * vz) / (vx * vx + vz * vz)))
        local = [ax + u * vx, 0.0, az + u * vz]
        distance = math.hypot(local[0] - hx, local[2] - hz)
        if best is None or distance < best[2]:
            best = (bell_point(angle, local), local, distance)
    return best


def simulate(disabled: str | None = None, include_track: bool = True) -> dict:
    """Run the mechanism; `disabled` is a physical break used for ablation QA."""
    allowed = {None, "ball", "domino_3", "counterweight", "gear", "hammer", "bell"}
    if disabled not in allowed:
        raise ValueError(disabled)
    film_end = DURATION / SLOW_MOTION
    events: list[dict] = []
    event_names: set[str] = set()
    frames = []

    def event(name, time, **details):
        if name not in event_names:
            event_names.add(name)
            events.append({"name": name, "time": round(time * SLOW_MOTION, 6),
                           "physical_time": round(time, 6), **details})

    ball_s = ball_v = ball_spin = 0.0
    ball_hit = False
    ball_x = -3.0
    ball_after_v = 0.0
    theta = [0.0] * 5
    omega = [0.0] * 5
    touched = [False] * 5
    trip_angle = 0.0
    released = False
    drop = weight_v = 0.0
    bell_angle = bell_omega = 0.0
    flag_angle = flag_omega = 0.0
    flag_released = False
    m_ball, m_domino = 0.24, 0.18
    domino_I = m_domino * (1.35 ** 2 + 0.18 ** 2) / 3.0
    weight_effective_mass = 3.0
    weight_drag = 34.0
    bell_I = 0.085
    initial_link = linkage(0.0)
    step_count = int(math.ceil(film_end / DT)) + 1
    sample_index = 0

    def snapshot(t):
        ball = [ball_x, -1.30, 1.31] if ball_hit else on_track(ball_s)[0]
        driven_drop = 0.0 if disabled == "gear" else drop
        link = initial_link if disabled == "hammer" else linkage(driven_drop)
        sear_dx, sear_dz = rotate_y_xz(-0.10, -0.05, trip_angle)
        return {
            "frame": sample_index,
            "time": round(sample_index / FPS, 6),
            "ball": [round(x, 8) for x in ball],
            "ball_spin": round(ball_spin, 8),
            "ball_distance": round(ball_s, 8),
            "domino_angles": [round(x, 8) for x in theta],
            "trip_angle": round(trip_angle, 8),
            "sear_tip": [2.4 + sear_dx, 0.60, 2.65 + sear_dz],
            "weight_z": round(2.85 - drop, 8),
            "weight_drop": round(drop, 8),
            "weight_velocity": round(weight_v, 8),
            "gear1_angle": round(drop / 0.35, 8),
            "gear2_angle": round(-4.0 * driven_drop, 8),
            "bell_swing": round(bell_angle, 8),
            "bell_lip": bell_point(bell_angle, GEOMETRY["bell_lip_local"]),
            "bell_tab": bell_point(bell_angle, GEOMETRY["bell_tab_local"]),
            "flag_angle": round(flag_angle, 8),
            "latch_released": released,
            "flag_released": flag_released,
            **link,
        }

    if disabled != "ball":
        event("ball_start", 0.0)

    for step in range(step_count):
        t = step * DT
        while sample_index < int(FPS * DURATION) and t + DT / 2 >= sample_index / FPS / SLOW_MOTION:
            frames.append(snapshot(t))
            sample_index += 1

        # Stage 1: constrained rolling under gravity, then an actual impact.
        if disabled != "ball" and not ball_hit:
            old_s = ball_s
            ball_v = max(0.0, ball_v + ball_acceleration(ball_s, ball_v) * DT)
            ball_s = min(TRACK_END, ball_s + ball_v * DT)
            ball_spin += (ball_s - old_s) / 0.21
            if ball_s >= TRACK_END:
                # Sphere center -3.00 + radius .21 meets first domino face -2.79.
                contact_height = 0.21
                effective_inverse_mass = 1.0 / m_ball + contact_height ** 2 / domino_I
                impulse = 1.35 * ball_v / effective_inverse_mass
                omega[0] += impulse * contact_height / domino_I
                ball_after_v = ball_v - impulse / m_ball
                ball_hit = touched[0] = True
                event("domino_1_impact", t, contact=[-2.79, -1.30, 1.31],
                      impulse=impulse, source="marble")
        elif ball_hit and abs(ball_after_v) > 1e-6:
            # The lighter rolling sphere rebounds on the same continuous runway.
            old_v = ball_after_v
            deceleration = 2.8
            ball_after_v = math.copysign(max(0.0, abs(old_v) - deceleration * DT), old_v)
            movement = 0.5 * (old_v + ball_after_v) * DT
            ball_x += movement
            ball_spin += movement / 0.21

        # Stage 2: hinged dominoes, including finite thickness and contact impulses.
        for i in range(5):
            if disabled == "domino_3" and i == 2:
                continue
            if touched[i] and theta[i] < 1.22:
                torque = m_domino * G / 2 * (1.35 * math.sin(theta[i]) - 0.18 * math.cos(theta[i]))
                omega[i] += (torque / domino_I - 0.11 * omega[i]) * DT
                theta[i] = max(0.0, theta[i] + omega[i] * DT)
                if theta[i] >= 1.22:
                    theta[i], omega[i] = 1.22, 0.0
        for _ in range(3):
            for i in range(4):
                if disabled == "domino_3" and i in (1, 2):
                    continue
                if not touched[i]:
                    continue
                a, b = theta[i], theta[i + 1]
                dx = -0.83 + 1.35 * math.sin(a)
                dz = 1.35 * math.cos(a)
                local_x = dx * math.cos(b) - dz * math.sin(b)
                local_z = dx * math.sin(b) + dz * math.cos(b)
                gap = -0.18 - local_x
                if gap <= 0.0 and 0.0 <= local_z <= 1.35:
                    ja = -1.35 * math.cos(a - b)
                    jb = local_z
                    inv = (ja * ja + jb * jb) / domino_I
                    rate = ja * omega[i] + jb * omega[i + 1]
                    impulse = 0.0
                    if rate < 0.0:
                        impulse = -1.12 * rate / inv
                        omega[i] += ja * impulse / domino_I
                        omega[i + 1] += jb * impulse / domino_I
                    correction = -gap / inv
                    theta[i] = max(0.0, theta[i] + ja * correction / domino_I)
                    theta[i + 1] += jb * correction / domino_I
                    if not touched[i + 1]:
                        touched[i + 1] = True
                        event(f"domino_{i + 2}_impact", t, source=f"domino_{i + 1}",
                              impulse=impulse, contact_height=local_z)

        # Stage 3: the fifth top corner pushes a real diagonal arm on a common shaft.
        if touched[4]:
            tip_x = 0.71 + 1.35 * math.sin(theta[4])
            tip_z = 1.10 + 1.35 * math.cos(theta[4])
            rx, rz = tip_x - 2.40, tip_z - 2.65
            arm_phase = math.atan2(-0.61, -0.82)
            tip_phase = math.atan2(rz, rx)
            radial = math.hypot(rx, rz)
            if radial <= math.hypot(0.82, 0.61) + 0.025 and tip_phase >= arm_phase:
                trip_angle = min(trip_angle, max(-0.57, arm_phase - tip_phase))
        sear_dx, _ = rotate_y_xz(-0.10, -0.05, trip_angle)
        sear_tip_x = 2.40 + sear_dx
        if not released and sear_tip_x > 2.31 + 0.0001 and disabled != "counterweight":
            released = True
            event("latch_release", t, source="domino_5", trip_angle=trip_angle,
                  sear_tip_x=sear_tip_x, weight_right_edge=2.31)
            event("gear_start", t, source="counterweight")

        # Stage 4: weight + winding drum, reflected train inertia and rotary damper.
        old_drop = drop
        if released and drop < 1.30:
            acceleration = (G - weight_drag * weight_v) / weight_effective_mass
            weight_v = max(0.0, weight_v + acceleration * DT)
            drop = min(1.30, drop + weight_v * DT)
            if drop >= 1.30:
                weight_v = 0.0
                event("gear_stop", t, source="counterweight_end_stop")

        # Stage 5: exact gear-driven linkage. Bell contact shares an impulse with
        # the falling weight, using each system's generalized contact Jacobian.
        driven_drop = 0.0 if disabled == "gear" else drop
        link = initial_link if disabled == "hammer" else linkage(driven_drop)
        if disabled != "bell":
            bell_omega += (-G / 0.62 * math.sin(bell_angle) - 2.8 * bell_omega) * DT
            bell_angle += bell_omega * DT
        head = link["hammer_head"]
        contact, contact_local, distance = bell_contact(head, bell_angle)
        dx, dz = contact[0] - head[0], contact[2] - head[2]
        if disabled not in ("gear", "hammer") and distance < 0.12:
            nx, nz = dx / max(distance, 1e-9), dz / max(distance, 1e-9)
            eps = 1e-5
            before = linkage(max(0.0, drop - eps))["hammer_head"]
            after = linkage(min(1.30, drop + eps))["hammer_head"]
            derivative_denom = min(1.30, drop + eps) - max(0.0, drop - eps)
            hdx = (after[0] - before[0]) / derivative_denom
            hdz = (after[2] - before[2]) / derivative_denom
            jh = nx * hdx + nz * hdz
            lx, lz = contact_local[0], contact_local[2]
            bdx = -lx * math.sin(bell_angle) - lz * math.cos(bell_angle)
            bdz = lx * math.cos(bell_angle) - lz * math.sin(bell_angle)
            jb = nx * bdx + nz * bdz
            approach = jh * weight_v - jb * bell_omega
            if approach > 0.0:
                inv = jh * jh / weight_effective_mass + (jb * jb / bell_I if disabled != "bell" else 0.0)
                impact = 1.28 * approach / max(inv, 1e-8)
                weight_v = max(0.0, weight_v - impact * jh / weight_effective_mass)
                if disabled != "bell":
                    bell_omega += impact * jb / bell_I
                event("bell_strike", t, source="hammer", distance=distance,
                      hammer_head=head, bell_contact=contact, impulse=impact)
            if disabled != "bell" and jb > 0.1:
                bell_angle += (0.12 - distance) / jb

        # Stage 6: a tab rigidly attached to the swinging bell lifts the flag pawl.
        tab = bell_point(bell_angle, GEOMETRY["bell_tab_local"])
        if not flag_released and tab[2] >= 4.23:
            flag_released = True
            event("flag_release", t, source="bell_yoke_tab", tab_z=tab[2], pawl_z=4.23,
                  bell_swing=bell_angle)
        if flag_released:
            flag_omega += (64.0 * (PI / 2.0 - flag_angle) - 12.0 * flag_omega) * DT
            flag_angle += flag_omega * DT
            if flag_angle > PI / 2.0:
                flag_angle = PI / 2.0
                flag_omega = -0.10 * max(0.0, flag_omega)
            if abs(flag_angle - PI / 2.0) < 0.005 and abs(flag_omega) < 0.03:
                event("flag_settled", t, source="torsion_spring_and_stop")

    result = {
        "schema": "rolling-ball-mechanics-v1",
        "duration": DURATION,
        "fps": FPS,
        "frame_count": FPS * int(DURATION),
        "slow_motion_factor": SLOW_MOTION,
        "physics_step_seconds": DT,
        "disabled": disabled,
        "geometry": GEOMETRY,
        "angle_conventions": {
            "domino_angles": "Blender rotation_euler.y directly; geometry relative to forward bottom hinge",
            "trip_angle": "Blender rotation_euler.y directly",
            "gear1_angle": "Mathematical XZ phase: Blender rotation_euler.y = -gear1_angle",
            "gear2_angle": "Mathematical XZ phase: Blender rotation_euler.y = -gear2_angle; add tooth phase in the same plane",
            "hammer_angle": "Mathematical XZ direction from hammer pivot toward follower/head",
            "bell_swing": "Positive swing moves bell right: Blender rotation_euler.y = -bell_swing",
            "flag_angle": "Zero folded horizontally right, pi/2 upright; for a modeled vertical mast use rotation_euler.y = pi/2 - flag_angle",
        },
        "events": events,
        "frames": frames,
        "model": {
            "gravity": G,
            "ball_mass": m_ball,
            "domino_mass": m_domino,
            "domino_inertia": domino_I,
            "weight_effective_mass": weight_effective_mass,
            "rotary_damper_reflected_drag": weight_drag,
            "bell_inertia": bell_I,
            "notes": "Constrained reduced-order mechanics. One global slow-motion scale. No timed stage triggers.",
        },
    }
    if include_track:
        result["track_path"] = TRACK
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/simulation.json")
    parser.add_argument("--disabled", default=None)
    args = parser.parse_args()
    result = simulate(args.disabled)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {len(result['frames'])} frames to {args.output}; global slow-motion {SLOW_MOTION:.6f}x")
    for e in result["events"]:
        print(f"{e['time']:7.3f}s  {e['name']}")


if __name__ == "__main__":
    main()
