# Mechanical model and verification

The animation is driven by `src/simulate.py`. Its output supplies the geometry, frame samples, and contact events consumed by the Blender scene builder and Foley generator. Film timing does not activate the stages: a contact or an existing mechanical constraint must transmit motion to the next component.

## Scope and assumptions

This is a deterministic, reduced-order model of this particular machine. It uses constrained degrees of freedom and local contact equations, rather than Blender's general-purpose rigid-body solver. The dominoes rotate on bottom hinges; the cord is taut and inextensible; gears have ideal pitch-circle coupling; the crank, connecting rod, and hammer rocker are rigid; and the bell and flag each have one rotational degree of freedom.

Dimensions are expressed in scene metres. Masses and inertias are effective lumped values for the mechanism, so this is an animation mechanism rather than a dimensioned manufacturing specification. Rolling resistance, hinge damping, a reflected rotary damper, local restitution, and mechanical end stops dissipate energy. Airflow and cloth are not independently fluid/cloth simulated.

The solver advances with a **1/1200-second physical timestep**. A single **1.7785682525565425×** dilation maps physical time to film time for every moving mechanical part. The film is sampled at 24 fps for 600 frames, spanning `[0, 25)` seconds. The last displayed frame begins at `599/24` seconds and lasts one frame, completing exactly 25 seconds.

## 1. Marble and spiral

The marble follows a continuous two-turn helix, with its vertical pitch smoothly tapering to zero before a straight tangent exit. Its center follows the track; the rendered two-rail geometry places the sphere at the correct rail separation and support offset.

For arc length `s`, speed `v`, and gravity `g`, the rolling acceleration is:

```text
dv/dt = -g (dz/ds) / 1.4 - rolling resistance
ds/dt = v
```

The factor `1.4` includes the rotational inertia of a solid sphere. Rolling angle advances by distance divided by the sphere radius. At the end of the runway, the radius-0.21 sphere centered at `x = -3.00` meets the first domino's rear face at `x = -2.79`. The impact uses a shared impulse and gives the first domino angular velocity. The marble rebounds and slows on the same runway, remaining visible and continuous.

## 2. Exactly five dominoes

Five dominoes have height `1.35`, thickness `0.18`, and spacing `0.83`. Each rotates around its forward bottom edge. For mass `m`, height `h`, thickness `w`, and fall angle `theta`:

```text
I = m (h² + w²) / 3
gravity torque = m g (h sin(theta) - w cos(theta)) / 2
```

The finite-thickness term prevents an unstruck upright domino from spontaneously falling. Contact is detected by transforming the preceding domino's forward top corner into the next domino's local coordinates. A contact impulse transfers angular momentum, and a positional correction prevents overlap. No fixed interval is assigned between impacts.

The dominoes finish against modeled stops at `1.22` radians. These stops make the final arrangement constructible without allowing tiles to pass through one another.

## 3. Trip shaft and counterweight sear

The fifth domino's top corner pushes the visible diagonal trip arm. The trip arm and the rear sear share one rigid shaft, so the sear follows the measured trip angle.

The counterweight remains stationary until the computed sear tip clears the weight's right edge at `x = 2.31`. Clearance is tested geometrically. The normal run clears the edge at **11.708908 seconds of film time**.

## 4. Cord drum and gears

After release, the counterweight descends under gravity with reflected effective inertia and viscous rotary damping. Its travel is limited to `1.30` scene units by a mechanical stop.

The cord drum has radius `0.35`. Its payout and rotation obey:

```text
counterweight drop = 0.35 × drum angle
```

The drum shares a shaft with the 28-tooth driving gear. The driven gear has 20 teeth. Their pitch radii, `0.84` and `0.60`, have a matching module and center distance `1.44`. A half-tooth initial phase aligns teeth with gaps. Their angular motion obeys:

```text
28 × driving angle + 20 × driven angle = 0
```

The gears therefore cannot rotate ahead of the counterweight, and their motion cannot drift apart during the film.

## 5. Crank, connecting rod, hammer, and bell

An eccentric pin on the driven gear connects to a rigid rod and a hammer rocker. The solver computes their configuration as the intersection of two circles, preserving the crank radius, rod length, follower radius, and hammer length at every frame:

| Constraint | Length |
| --- | ---: |
| Crank radius | 0.25 |
| Connecting rod | 0.95 |
| Hammer follower radius | 0.38 |
| Hammer arm | 0.85 |
| Hammer head radius | 0.12 |

The hammer-to-bell collision is measured against the actual lathed bell profile in the swing plane. A positive approach speed and contact distance below the hammer-head radius produce a shared impact impulse. That impulse excites the bell and reacts back onto the falling-weight drive. The bell then follows a damped pendulum equation.

In the normal run, the strike occurs at **16.685934 seconds**. The exported event includes both contact positions, the separation, and the impulse. The sound generator uses this event time directly.

## 6. Bell tab, pawl, and flag

A tab is rigidly attached to the bell yoke. Bell rotation raises the tab until it reaches the pawl's contact height at `z = 4.23`. This geometric contact releases the flag at **16.960130 seconds**.

The flagpole and its flag exist in the scene before release. A preloaded torsion spring rotates the pole from its folded horizontal position toward the upright stop. Damping and a small stop restitution settle it at `pi/2` radians. The flag is settled at **17.889432 seconds**, with the **SUCCESS** lettering facing the final camera.

## Camera and sound

The camera uses a smooth Hermite path. Its important framing points are derived from the solved first impact, sear release, bell strike, and flag-settling times. Camera choreography changes the view; it never advances the mechanism.

The original procedural Foley follows the same event data. Its five domino transients use the five actual contact times. Cord and gear sound spans counterweight release through the end stop. The bell ring and flag sound start at their respective physical events. The output contains no music or speech.

## Validation

`tests/test_causality.py` verifies the normal sequence and six deliberately interrupted versions. The checked-in [mechanical verification report](../data/mechanical_verification.json) records 18 passing tests.

| Experiment | Required outcome |
| --- | --- |
| Hold the marble | No domino, drive, bell, or flag motion |
| Remove domino 3 | Dominoes 1 and 2 move; all later stages stop |
| Lock the counterweight | The domino row falls; the drive, bell, and flag stay inactive |
| Disconnect the driven gear | Counterweight descends; hammer, bell, and flag stay inactive |
| Lock the hammer | No bell strike or flag release |
| Lock the bell | Hammer contact can occur, but the flag remains latched |

The normal-run tests also check:

- Exactly five dominoes, positive impulses, and valid contact heights.
- Correct chronological order of all contacts and releases.
- A tangent-continuous spiral exit and bounded marble movement per frame.
- Rolling angle consistent with distance traveled.
- No component movement before its enabling contact.
- Domino nonpenetration and final stop angles.
- Sear clearance before any counterweight descent.
- Cord payout, gear ratio, and all linkage lengths at every sample.
- Hammer clearance against the actual bell profile.
- Bell-tab contact before flag release, and the final upright flag angle.

Run the mechanical suite with:

```bash
python -m unittest discover -s tests -v
```

A broken-chain trajectory can also be exported for inspection:

```bash
python src/simulate.py --disabled domino_3 --output build/broken-domino-chain.json
```

Valid disabled components are `ball`, `domino_3`, `counterweight`, `gear`, `hammer`, and `bell`. The scene builder expects the complete normal-run events for its final film camera, so the interrupted data is primarily for numerical inspection.

## Render and delivery checks

The Blender render helper checks frame-range limits, scene length, frame rate, PNG dimensions, file signatures, and per-frame SHA-256 checksums. The encoder refuses a missing or empty frame and requires an exact-duration stereo WAV. It then checks the MP4's decoded frame count, frame rate, duration, video codec, pixel format, audio format, and complete decode.

These checks complement visual review: the mechanical tests establish causal and geometric behavior, while rendered contact frames and the completed movie establish visibility, framing, material quality, and readable flag text.
