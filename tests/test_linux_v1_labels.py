"""features/windows.label_linux_v1: lifecycle labels frozen in R5 (docs/METHOD-FREEZE.md section 5)."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.adapters import Case  # noqa: E402
from features.windows import label_linux_v1  # noqa: E402

# run starts at 0, injection observed at 600, effect at 610, removed at 900, recovered at 1000
CASE = Case(case_id="lv1", root_cause="paymentservice", fault="cpu_saturation", repetition=1, onset=610.0,
            path=Path("."), run_start=0.0, injection=600.0, removal=900.0, recovery=1000.0)


def lab(start, case=CASE):
    return label_linux_v1(start - case.onset, case)


class LinuxV1LabelTests(unittest.TestCase):
    def test_lifecycle(self):
        self.assertEqual(lab(100), "excluded")              # warmup (< 180 s)
        self.assertEqual(lab(180), "baseline_stats")
        self.assertEqual(lab(460), "baseline_stats")        # ends at 490 = onset - 120
        self.assertEqual(lab(470), "excluded")              # crosses 490
        self.assertEqual(lab(490), "normal")
        self.assertEqual(lab(570), "normal")                # ends at 600 = injection
        self.assertEqual(lab(580), "transition")            # overlaps injection
        self.assertEqual(lab(660), "transition")            # rel 50 < 60
        self.assertEqual(lab(670), "fault_active")          # rel 60
        self.assertEqual(lab(870), "fault_active")          # ends at removal
        self.assertEqual(lab(880), "recovering")            # crosses removal
        self.assertEqual(lab(990), "recovering")            # crosses recovery
        self.assertEqual(lab(1000), "recovered")

    def test_control_and_unconfirmed_recovery(self):
        ctrl = replace(CASE, kind="control")
        self.assertEqual(lab(670, ctrl), "sham_active")
        self.assertEqual(lab(1200, replace(CASE, recovery=None)), "recovering")


if __name__ == "__main__":
    unittest.main()
