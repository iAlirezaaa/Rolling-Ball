"""Mechanism-level verification, including deliberate broken-chain experiments.

These tests do not check merely that six timestamp labels exist. They measure
the geometry and motion, verify the shared mechanical constraints, and break
each causal link to establish that downstream stages genuinely stop.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import simulate as mechanics


class MechanicalSequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = mechanics.simulate(include_track=False)
        cls.frames = cls.result["frames"]
        cls.events = {event["name"]: event for event in cls.result["events"]}
        cls.broken = {part: mechanics.simulate(part, include_track=False)
                      for part in ("ball", "domino_3", "counterweight", "gear", "hammer", "bell")}

    def test_exact_film_length_and_sample_count(self):
        self.assertEqual(self.result["duration"], 25.0)
        self.assertEqual(self.result["fps"], 24)
        self.assertEqual(len(self.frames), 600)
        self.assertEqual(self.frames[0]["frame"], 0)
        self.assertEqual(self.frames[-1]["frame"], 599)
        self.assertAlmostEqual(self.frames[-1]["time"], 599 / 24, places=5)

    def test_six_stages_in_required_order(self):
        names = ["domino_1_impact", "domino_2_impact", "domino_3_impact", "domino_4_impact",
                 "domino_5_impact", "latch_release", "bell_strike", "flag_release", "flag_settled"]
        times = [self.events[name]["time"] for name in names]
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        self.assertLess(self.events["flag_settled"]["time"], 20.0)
        self.assertLess(self.events["gear_stop"]["time"], 20.1)

    def test_exactly_five_dominoes_and_real_contacts(self):
        self.assertEqual(len(mechanics.GEOMETRY["domino_centers"]), 5)
        impact_names = [n for n in self.events if n.startswith("domino_")]
        self.assertEqual(len(impact_names), 5)
        self.assertEqual(self.events["domino_1_impact"]["source"], "marble")
        for i in range(2, 6):
            event = self.events[f"domino_{i}_impact"]
            self.assertEqual(event["source"], f"domino_{i-1}")
            self.assertGreater(event["impulse"], 0.0)
            self.assertTrue(0.0 < event["contact_height"] < 1.35)
        self.assertTrue(all(abs(x - 1.22) < 1e-7 for x in self.frames[-1]["domino_angles"]))

    def test_tangent_continuous_track_exit(self):
        points = mechanics.TRACK
        a = [points[2400][j] - points[2399][j] for j in range(3)]
        b = [points[2401][j] - points[2400][j] for j in range(3)]
        cosine = sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b)))
        self.assertGreater(cosine, math.cos(0.01))
        self.assertEqual(points[-1], [-3.0, -1.3, 1.31])
        self.assertLess(max(math.dist(a,b) for a,b in zip(points, points[1:])), 0.02)

    def test_no_marble_teleport_or_missing_roll(self):
        jumps = [math.dist(a["ball"], b["ball"]) for a,b in zip(self.frames, self.frames[1:])]
        self.assertLess(max(jumps), mechanics.GEOMETRY["ball_radius"])
        self.assertAlmostEqual(self.frames[0]["ball_spin"], 0.0)
        self.assertGreater(self.frames[239]["ball_spin"], 80.0)
        for f in self.frames:
            if f["time"] < self.events["domino_1_impact"]["time"]:
                self.assertAlmostEqual(f["ball_spin"] * 0.21, f["ball_distance"], places=6)
        # After impact it rebounds continuously onto the same runway, not offscreen.
        self.assertTrue(-5.0 < self.frames[-1]["ball"][0] < -3.0)
        self.assertAlmostEqual(self.frames[-1]["ball"][2], 1.31)

    def test_no_premature_movement(self):
        for f in self.frames:
            for i in range(5):
                if f["time"] < self.events[f"domino_{i+1}_impact"]["time"] - 0.002:
                    self.assertAlmostEqual(f["domino_angles"][i], 0.0)
            if f["time"] < self.events["latch_release"]["time"] - 0.002:
                self.assertAlmostEqual(f["weight_z"], 2.85)
                self.assertAlmostEqual(f["gear1_angle"], 0.0)
                self.assertAlmostEqual(f["gear2_angle"], 0.0)
            if f["time"] < self.events["bell_strike"]["time"] - 0.002:
                self.assertAlmostEqual(f["bell_swing"], 0.0)
            if f["time"] < self.events["flag_release"]["time"] - 0.002:
                self.assertAlmostEqual(f["flag_angle"], 0.0)

    def test_dominoes_do_not_pass_through_neighbors(self):
        for f in self.frames:
            for a,b in zip(f["domino_angles"], f["domino_angles"][1:]):
                dx = -0.83 + 1.35 * math.sin(a)
                dz = 1.35 * math.cos(a)
                lx = dx * math.cos(b) - dz * math.sin(b)
                lz = dx * math.sin(b) + dz * math.cos(b)
                if 0.0 <= lz <= 1.35:
                    self.assertGreaterEqual(-0.18 - lx, -0.0001)

    def test_sear_is_physically_clear_before_weight_drops(self):
        event = self.events["latch_release"]
        self.assertGreater(event["sear_tip_x"], event["weight_right_edge"])
        for f in self.frames:
            if f["weight_drop"] > 1e-5:
                self.assertGreater(f["sear_tip"][0], 2.31)

    def test_cord_and_gears_remain_mechanically_coupled(self):
        for f in self.frames:
            self.assertAlmostEqual(f["weight_drop"], f["gear1_angle"] * 0.35, places=7)
            self.assertAlmostEqual(28 * f["gear1_angle"] + 20 * f["gear2_angle"], 0.0, places=6)
        self.assertAlmostEqual(self.frames[-1]["weight_drop"], 1.30)
        self.assertAlmostEqual(self.frames[-1]["weight_z"], 1.55)

    def test_crank_rod_and_hammer_lengths_do_not_change(self):
        pivot = mechanics.GEOMETRY["hammer_pivot"]
        gear = [3.84, -0.65, 3.60]
        for f in self.frames:
            self.assertAlmostEqual(math.dist(f["crank_pin"], gear), 0.25, places=10)
            self.assertAlmostEqual(math.dist(f["crank_pin"], f["hammer_follower"]), 0.95, places=10)
            self.assertAlmostEqual(math.dist(f["hammer_follower"], pivot), 0.38, places=10)
            self.assertAlmostEqual(math.dist(f["hammer_head"], pivot), 0.85, places=10)

    def test_hammer_contacts_actual_bell_surface(self):
        event = self.events["bell_strike"]
        self.assertLess(event["distance"], 0.12)
        self.assertGreater(event["distance"], 0.118)
        self.assertGreater(event["impulse"], 0.0)
        for f in self.frames:
            distance = mechanics.bell_contact(f["hammer_head"], f["bell_swing"])[2]
            self.assertGreaterEqual(distance, 0.1198)

    def test_bell_tab_physically_reaches_flag_pawl(self):
        event = self.events["flag_release"]
        self.assertGreaterEqual(event["tab_z"], event["pawl_z"])
        self.assertGreater(event["bell_swing"], 0.08)
        self.assertEqual(mechanics.GEOMETRY["flag_text"], "SUCCESS")
        self.assertAlmostEqual(self.frames[-1]["flag_angle"], math.pi/2, places=7)

    def assert_inactive(self, result, names, fields):
        names_present = {e["name"] for e in result["events"]}
        for name in names:
            self.assertNotIn(name, names_present)
        for f in result["frames"]:
            for field in fields:
                self.assertAlmostEqual(f[field], 0.0, msg=f"{result['disabled']} failed to stop {field}")

    def test_holding_marble_stops_entire_machine(self):
        result = self.broken["ball"]
        self.assertEqual(result["events"], [])
        for f in result["frames"]:
            self.assertEqual(f["domino_angles"], [0.0]*5)
        self.assert_inactive(result, ["latch_release", "bell_strike", "flag_release"],
                             ["weight_drop", "gear1_angle", "gear2_angle", "bell_swing", "flag_angle"])

    def test_removing_middle_domino_breaks_cascade(self):
        result = self.broken["domino_3"]
        self.assert_inactive(result, ["domino_3_impact", "domino_4_impact", "domino_5_impact", "latch_release", "bell_strike", "flag_release"],
                             ["weight_drop", "gear1_angle", "bell_swing", "flag_angle"])
        self.assertGreater(result["frames"][-1]["domino_angles"][1], 1.0)
        self.assertEqual(result["frames"][-1]["domino_angles"][2:], [0.0]*3)

    def test_locking_counterweight_stops_drive(self):
        result = self.broken["counterweight"]
        self.assertGreater(result["frames"][-1]["domino_angles"][4], 1.0)
        self.assert_inactive(result, ["latch_release", "gear_start", "bell_strike", "flag_release"],
                             ["weight_drop", "gear1_angle", "gear2_angle", "bell_swing", "flag_angle"])

    def test_disconnecting_gear_stops_hammer_and_flag(self):
        result = self.broken["gear"]
        self.assertAlmostEqual(result["frames"][-1]["weight_drop"], 1.30)
        self.assert_inactive(result, ["bell_strike", "flag_release"], ["gear2_angle", "bell_swing", "flag_angle"])
        self.assertEqual(result["frames"][0]["hammer_head"], result["frames"][-1]["hammer_head"])

    def test_locked_hammer_prevents_ring_and_flag(self):
        result = self.broken["hammer"]
        self.assert_inactive(result, ["bell_strike", "flag_release"], ["bell_swing", "flag_angle"])
        self.assertEqual(result["frames"][0]["hammer_head"], result["frames"][-1]["hammer_head"])

    def test_locked_bell_keeps_flag_latched(self):
        result = self.broken["bell"]
        self.assertIn("bell_strike", {e["name"] for e in result["events"]})
        self.assert_inactive(result, ["flag_release", "flag_settled"], ["bell_swing", "flag_angle"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
