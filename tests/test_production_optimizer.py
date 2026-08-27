import csv
import io
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src import allocator, diagnostics, optimizer, production_optimizer


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "data" / "synthetic"


def student(student_id, stream="stream_a", **overrides):
    row = {
        "student_id": student_id,
        "programme": "FAKE-PROG",
        "programme_name": "Fictional Programme",
        "allocation_stream": stream,
        "sex": "F",
        "country": "England",
        "fee_status": "Home",
        "year_of_study": "1",
        "status": "New",
        "age": "18",
        "mature_student": "False",
        "entry_route": "A-level",
        "returning_student": "False",
        "support_need": "none",
    }
    row.update(overrides)
    return row


def tutor(tutor_id, streams="stream_a", **overrides):
    row = {
        "tutor_id": tutor_id,
        "tutor_name": f"Fictional Tutor {tutor_id}",
        "eligible_allocation_streams": streams,
        "dbs_checked": "True",
        "experience_level": "standard",
        "preferred_capacity": "8",
    }
    row.update(overrides)
    return row


def allocation(student_row, tutor_row, group_number):
    return {
        "student_id": student_row["student_id"],
        "programme": student_row["programme"],
        "programme_name": student_row["programme_name"],
        "allocation_stream": student_row["allocation_stream"],
        "tutor_id": tutor_row["tutor_id"],
        "tutor_name": tutor_row["tutor_name"],
        "group_number": group_number,
    }


def group_sizes(rows):
    return Counter(
        (row["allocation_stream"], row["tutor_id"]) for row in rows
    )


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


class ProductionOptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.students = diagnostics.read_csv(SYNTHETIC / "feasible_students.csv")
        cls.tutors = diagnostics.read_csv(SYNTHETIC / "feasible_tutors.csv")
        cls.baseline, cls.unallocated = allocator.allocate(cls.students, cls.tutors)
        cls.refined = production_optimizer.optimize(
            cls.students, cls.tutors, cls.baseline
        )
        cls.baseline_metrics = optimizer.tracked_metric_values(
            cls.students, cls.tutors, cls.baseline
        )
        cls.refined_metrics = optimizer.tracked_metric_values(
            cls.students, cls.tutors, cls.refined
        )

    def test_hard_constraints_and_streams(self):
        self.assertFalse(self.unallocated)
        expected = Counter(row["student_id"] for row in self.students)
        actual = Counter(row["student_id"] for row in self.refined)
        self.assertEqual(len(self.refined), 32)
        self.assertEqual(actual, expected)
        students = {row["student_id"]: row for row in self.students}
        tutors = {row["tutor_id"]: row for row in self.tutors}
        for row in self.refined:
            source = students[row["student_id"]]
            destination = tutors[row["tutor_id"]]
            self.assertEqual(row["allocation_stream"], source["allocation_stream"])
            self.assertIn(
                row["allocation_stream"],
                destination["eligible_allocation_streams"].split("|"),
            )
            if int(source["age"]) < 18:
                self.assertEqual(destination["dbs_checked"], "True")

    def test_result_is_deterministic_on_repeated_runs(self):
        repeated = production_optimizer.optimize(
            self.students, self.tutors, self.baseline
        )
        self.assertEqual(repeated, self.refined)
        self.assertEqual(
            production_optimizer.optimize(self.students, self.tutors, self.refined),
            self.refined,
        )

    def test_tracked_metrics_do_not_regress(self):
        self.assertTrue(
            all(
                after <= before
                for before, after in zip(self.baseline_metrics, self.refined_metrics)
            )
        )

    def test_exact_baseline_group_sizes_are_preserved(self):
        self.assertEqual(group_sizes(self.refined), group_sizes(self.baseline))

    def test_returning_flags_do_not_affect_optimization(self):
        changed_students = [
            dict(
                row,
                returning_student=(
                    "False" if row["returning_student"] == "True" else "True"
                ),
            )
            for row in self.students
        ]
        self.assertEqual(
            production_optimizer.optimize(
                changed_students, self.tutors, self.baseline
            ),
            self.refined,
        )

    def test_local_swap_improves_isolation(self):
        students = [student("S1", sex="M")]
        students.extend(student(f"S{number}", sex="F") for number in range(2, 5))
        students.append(student("S5", sex="M"))
        students.extend(student(f"S{number}", sex="F") for number in range(6, 9))
        tutors = [tutor("T1"), tutor("T2")]
        baseline = [allocation(row, tutors[0], "G01") for row in students[:4]]
        baseline.extend(allocation(row, tutors[1], "G02") for row in students[4:])

        refined = production_optimizer.optimize(students, tutors, baseline)

        before = optimizer.tracked_metric_values(students, tutors, baseline)
        after = optimizer.tracked_metric_values(students, tutors, refined)
        self.assertLess(
            optimizer.objective_from_metrics(after),
            optimizer.objective_from_metrics(before),
        )
        self.assertEqual(after[0], 0)
        self.assertEqual(group_sizes(refined), group_sizes(baseline))

    def test_preferred_capacity_load_is_preserved(self):
        stream = "capacity_stream"
        students = [
            student(
                f"CAP-{number:02d}",
                stream=stream,
                sex="M" if number in {1, 4} else "F",
            )
            for number in range(1, 21)
        ]
        tutors = [
            tutor("CAP-T1", streams=stream, preferred_capacity="2"),
            tutor("CAP-T2", streams=stream, preferred_capacity="8"),
        ]
        baseline, unallocated = allocator.allocate(students, tutors)

        refined = production_optimizer.optimize(students, tutors, baseline)

        self.assertFalse(unallocated)
        expected = {(stream, "CAP-T1"): 4, (stream, "CAP-T2"): 16}
        self.assertEqual(group_sizes(baseline), expected)
        self.assertEqual(group_sizes(refined), expected)

    def test_local_swap_improves_complex_support_match(self):
        students = [student("S1", support_need="complex"), student("S2")]
        tutors = [tutor("T1"), tutor("T2", experience_level="experienced")]
        baseline = [
            allocation(students[0], tutors[0], "G01"),
            allocation(students[1], tutors[1], "G02"),
        ]

        refined = production_optimizer.optimize(students, tutors, baseline)

        before = optimizer.tracked_metric_values(students, tutors, baseline)
        after = optimizer.tracked_metric_values(students, tutors, refined)
        self.assertEqual(before[4], 1)
        self.assertEqual(after[4], 0)
        self.assertEqual(
            next(row for row in refined if row["student_id"] == "S1")["tutor_id"],
            "T2",
        )

    def test_impossible_student_is_reported_with_failure(self):
        students = [student("IMP-001", age="17")]
        tutors = [
            tutor("T1", dbs_checked="False"),
            tutor("T2", streams="other_stream", dbs_checked="True"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            students_path = temp / "students.csv"
            tutors_path = temp / "tutors.csv"
            output_path = temp / "allocations.csv"
            write_csv(students_path, students)
            write_csv(tutors_path, tutors)
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                result = production_optimizer.main(
                    [
                        str(students_path),
                        str(tutors_path),
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(result, 1)
            self.assertIn("IMP-001", stderr.getvalue())
            self.assertIn("under-18 safeguarding", stderr.getvalue())
            self.assertEqual(diagnostics.read_csv(output_path), [])

    def test_large_cohort_avoids_exhaustive_search(self):
        streams = [f"large_stream_{number}" for number in range(4)]
        tutors = [
            tutor(
                f"LT-{stream}-{number}",
                streams=stream,
                preferred_capacity="40",
            )
            for stream in streams
            for number in range(2)
        ]
        students = [
            student(
                f"LS-{stream}-{number:03d}",
                stream=stream,
                sex="M" if number in {0, 1} else "F",
            )
            for stream in streams
            for number in range(80)
        ]
        baseline, unallocated = allocator.allocate(students, tutors)
        self.assertFalse(unallocated)

        with patch.object(
            optimizer,
            "build_candidate_sets",
            side_effect=AssertionError("exhaustive search called"),
        ), patch.object(
            optimizer,
            "feasible_assignments",
            side_effect=AssertionError("exhaustive search called"),
        ):
            refined = production_optimizer.optimize(students, tutors, baseline)

        self.assertEqual(len(refined), 320)
        self.assertEqual(len({row["student_id"] for row in refined}), 320)
        self.assertEqual(group_sizes(refined), group_sizes(baseline))
        before = optimizer.tracked_metric_values(students, tutors, baseline)
        after = optimizer.tracked_metric_values(students, tutors, refined)
        self.assertLess(
            optimizer.objective_from_metrics(after),
            optimizer.objective_from_metrics(before),
        )
        self.assertTrue(
            all(value <= limit for value, limit in zip(after, before))
        )


if __name__ == "__main__":
    unittest.main()
