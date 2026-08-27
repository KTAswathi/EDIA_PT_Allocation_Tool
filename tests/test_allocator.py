import csv
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from src import allocator


ROOT = Path(__file__).resolve().parents[1]
ALLOCATOR = ROOT / "src" / "allocator.py"
SYNTHETIC = ROOT / "data" / "synthetic"


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fieldnames, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class AllocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_context = tempfile.TemporaryDirectory()
        cls.temp_dir = Path(cls.temp_context.name)
        cls.students_path = SYNTHETIC / "feasible_students.csv"
        cls.tutors_path = SYNTHETIC / "feasible_tutors.csv"
        cls.impossible_students_path = SYNTHETIC / "impossible_students.csv"
        cls.impossible_tutors_path = SYNTHETIC / "impossible_tutors.csv"
        cls.students = read_csv(cls.students_path)
        cls.tutors = read_csv(cls.tutors_path)
        cls.feasible_output = cls.temp_dir / "feasible_allocations.csv"
        cls.impossible_output = cls.temp_dir / "impossible_allocations.csv"
        cls.feasible_result = cls.run_allocator(
            cls.students_path, cls.tutors_path, cls.feasible_output
        )
        cls.impossible_result = cls.run_allocator(
            cls.impossible_students_path,
            cls.impossible_tutors_path,
            cls.impossible_output,
        )
        cls.allocations = read_csv(cls.feasible_output)

    @classmethod
    def tearDownClass(cls):
        cls.temp_context.cleanup()

    @staticmethod
    def run_allocator(students, tutors, output):
        return subprocess.run(
            [
                sys.executable,
                str(ALLOCATOR),
                str(students),
                str(tutors),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_feasible_students_allocated_exactly_once(self):
        self.assertEqual(self.feasible_result.returncode, 0, self.feasible_result.stderr)
        expected = Counter(row["student_id"] for row in self.students)
        actual = Counter(row["student_id"] for row in self.allocations)
        self.assertEqual(len(self.allocations), 32)
        self.assertEqual(actual, expected)
        self.assertTrue(all(count == 1 for count in actual.values()))

        groups = defaultdict(set)
        for row in self.allocations:
            groups[row["allocation_stream"]].add(row["group_number"])
        for numbers in groups.values():
            self.assertEqual(
                sorted(numbers),
                [f"G{number:02d}" for number in range(1, len(numbers) + 1)],
            )

    def test_stream_eligibility(self):
        eligible = {
            tutor["tutor_id"]: set(tutor["eligible_allocation_streams"].split("|"))
            for tutor in self.tutors
        }
        for row in self.allocations:
            self.assertIn(row["allocation_stream"], eligible[row["tutor_id"]])

    def test_under_18_students_have_dbs_tutors(self):
        students = {row["student_id"]: row for row in self.students}
        tutors = {row["tutor_id"]: row for row in self.tutors}
        under_18 = [row for row in self.allocations if int(students[row["student_id"]]["age"]) < 18]
        self.assertEqual(len(under_18), 2)
        self.assertTrue(all(tutors[row["tutor_id"]]["dbs_checked"] == "True" for row in under_18))

    def test_programme_variants_share_stream_eligibility(self):
        variants = {
            "maths_and_cs_year_1": ("4COSC019UU", "4COSC018UU"),
            "cs_with_ai_year_1": ("4COMS002UU", "4COMS001UU"),
        }
        for stream, codes in variants.items():
            observed = {row["programme"] for row in self.students if row["allocation_stream"] == stream}
            self.assertEqual(observed, set(codes))
            template = next(
                row
                for row in self.students
                if row["allocation_stream"] == stream and int(row["age"]) >= 18
            )
            assigned_tutors = []
            for code in codes:
                student = dict(template, programme=code)
                rows, unallocated = allocator.allocate([student], self.tutors)
                self.assertFalse(unallocated)
                assigned_tutors.append(rows[0]["tutor_id"])
            self.assertEqual(assigned_tutors[0], assigned_tutors[1])

    def test_impossible_u18_is_unallocated_with_failure(self):
        self.assertEqual(self.impossible_result.returncode, 1)
        self.assertIn("IMP-STU-001", self.impossible_result.stderr)
        self.assertIn("under-18 safeguarding", self.impossible_result.stderr)
        self.assertEqual(read_csv(self.impossible_output), [])

    def test_duplicate_student_ids_are_rejected(self):
        students = [dict(row) for row in self.students]
        students[1]["student_id"] = students[0]["student_id"]
        students_path = self.temp_dir / "duplicate_students.csv"
        output_path = self.temp_dir / "duplicate_output.csv"
        write_csv(students_path, students[0].keys(), students)
        result = self.run_allocator(students_path, self.tutors_path, output_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate student_id", result.stderr)
        self.assertFalse(output_path.exists())

    def test_malformed_dbs_value_is_rejected(self):
        tutors = [dict(row) for row in self.tutors]
        tutors[0]["dbs_checked"] = "yes"
        tutors_path = self.temp_dir / "malformed_dbs_tutors.csv"
        output_path = self.temp_dir / "malformed_dbs_output.csv"
        write_csv(tutors_path, tutors[0].keys(), tutors)
        result = self.run_allocator(self.students_path, tutors_path, output_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("dbs_checked must be True or False", result.stderr)
        self.assertFalse(output_path.exists())

    def test_allocation_is_deterministic(self):
        first, first_unallocated = allocator.allocate(self.students, self.tutors)
        second, second_unallocated = allocator.allocate(self.students, self.tutors)
        self.assertEqual(first_unallocated, second_unallocated)
        self.assertEqual(first, second)

    def test_preferred_capacity_sets_proportional_soft_load(self):
        stream = "capacity_stream"
        students = [
            dict(
                self.students[0],
                student_id=f"CAP-{number:02d}",
                allocation_stream=stream,
                age="18",
            )
            for number in range(1, 21)
        ]
        tutors = [
            dict(
                self.tutors[0],
                tutor_id="CAP-T1",
                tutor_name="Capacity Tutor 1",
                eligible_allocation_streams=stream,
                preferred_capacity="2",
                dbs_checked="True",
            ),
            dict(
                self.tutors[1],
                tutor_id="CAP-T2",
                tutor_name="Capacity Tutor 2",
                eligible_allocation_streams=stream,
                preferred_capacity="8",
                dbs_checked="True",
            ),
        ]

        rows, unallocated = allocator.allocate(students, tutors)
        loads = Counter(row["tutor_id"] for row in rows)
        self.assertFalse(unallocated)
        self.assertEqual(loads, {"CAP-T1": 4, "CAP-T2": 16})
        self.assertGreater(loads["CAP-T1"], 2)
        self.assertGreater(loads["CAP-T2"], 8)

        for tutor in tutors:
            tutor["preferred_capacity"] = "8"
        equal_rows, _ = allocator.allocate(students[:4], tutors)
        self.assertEqual(
            [(row["student_id"], row["tutor_id"]) for row in equal_rows],
            [
                ("CAP-01", "CAP-T1"),
                ("CAP-02", "CAP-T2"),
                ("CAP-03", "CAP-T1"),
                ("CAP-04", "CAP-T2"),
            ],
        )

    def test_separate_output_paths_do_not_overwrite(self):
        self.assertNotEqual(self.feasible_output, self.impossible_output)
        self.assertTrue(self.feasible_output.exists())
        self.assertTrue(self.impossible_output.exists())
        self.assertEqual(len(read_csv(self.feasible_output)), 32)
        self.assertEqual(read_csv(self.impossible_output), [])


if __name__ == "__main__":
    unittest.main()
