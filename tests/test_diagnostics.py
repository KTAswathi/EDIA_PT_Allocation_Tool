import csv
import json
import tempfile
import unittest
from pathlib import Path

from src import diagnostics


def student(student_id, **overrides):
    row = {
        "student_id": student_id,
        "sex": "F",
        "country": "England",
        "fee_status": "Home",
        "age": "18",
        "mature_student": "False",
        "entry_route": "A-level",
        "returning_student": "False",
        "support_need": "none",
    }
    row.update(overrides)
    return row


def tutor(tutor_id, stream="stream_a", experience="standard"):
    return {
        "tutor_id": tutor_id,
        "tutor_name": f"Tutor {tutor_id}",
        "eligible_allocation_streams": stream,
        "experience_level": experience,
        "preferred_capacity": "8",
    }


def allocation(student_id, tutor_id, group_number, stream="stream_a"):
    return {
        "student_id": student_id,
        "programme": "SYN-PROG",
        "programme_name": "Synthetic Programme",
        "allocation_stream": stream,
        "tutor_id": tutor_id,
        "tutor_name": f"Tutor {tutor_id}",
        "group_number": group_number,
    }


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


class DiagnosticsTests(unittest.TestCase):
    def test_group_warning_definitions(self):
        students = [
            student(
                "S1",
                sex="F",
                country="India",
                fee_status="Overseas",
                age="17",
                mature_student="True",
                entry_route="BTEC",
                support_need="complex",
            ),
            student("S2", sex="M", support_need="standard"),
        ]
        tutors = [tutor("T1"), tutor("T2", experience="experienced")]
        allocations = [allocation("S1", "T1", "G01"), allocation("S2", "T1", "G01")]

        row = diagnostics.build_diagnostics(students, tutors, allocations)[0]

        self.assertEqual(row["group_size"], 2)
        self.assertEqual(row["Home_count"], 1)
        self.assertEqual(row["Overseas_count"], 1)
        self.assertEqual(json.loads(row["sex_counts"]), {"F": 1, "M": 1})
        self.assertEqual(row["mature_count"], 1)
        self.assertEqual(row["pathway_count"], 1)
        self.assertEqual(row["support_standard_count"], 1)
        self.assertEqual(row["support_complex_count"], 1)
        self.assertEqual(row["under_18_count"], 1)
        self.assertTrue(row["gender_isolation_warning"])
        self.assertTrue(row["overseas_isolation_warning"])
        self.assertTrue(row["mature_isolation_warning"])
        self.assertTrue(row["pathway_isolation_warning"])
        self.assertTrue(row["complex_support_tutor_warning"])
        self.assertEqual(row["soft_warning_count"], 5)

    def test_returning_review_is_not_scored(self):
        students = [student("S1", returning_student="True"), student("S2")]
        tutors = [tutor("T1")]
        allocations = [allocation("S1", "T1", "G01"), allocation("S2", "T1", "G01")]

        row = diagnostics.build_diagnostics(students, tutors, allocations)[0]

        self.assertEqual(row["returning_count"], 1)
        self.assertTrue(row["returning_manual_review"])
        self.assertFalse(row["gender_isolation_warning"])
        self.assertEqual(row["soft_warning_count"], 0)

    def test_postgraduate_and_complex_support_conditions(self):
        students = [student("S1", entry_route="Postgraduate", support_need="complex")]
        standard = tutor("T1")
        experienced = tutor("T2", experience="experienced")

        standard_row = diagnostics.build_diagnostics(
            students,
            [standard, experienced],
            [allocation("S1", "T1", "G01")],
        )[0]
        self.assertEqual(standard_row["pathway_count"], 0)
        self.assertTrue(standard_row["complex_support_tutor_warning"])

        no_alternative_row = diagnostics.build_diagnostics(
            students,
            [standard],
            [allocation("S1", "T1", "G01")],
        )[0]
        self.assertFalse(no_alternative_row["complex_support_tutor_warning"])

        experienced_row = diagnostics.build_diagnostics(
            students,
            [standard, experienced],
            [allocation("S1", "T2", "G01")],
        )[0]
        self.assertFalse(experienced_row["complex_support_tutor_warning"])

    def test_stream_level_diagnostics(self):
        students = [
            student("S1", country="India", fee_status="Overseas"),
            student("S2", country="India", fee_status="Overseas"),
            student("S3"),
            student("S4", country="China", fee_status="Overseas"),
        ]
        tutors = [tutor("T1"), tutor("T2")]
        allocations = [
            allocation("S1", "T1", "G01"),
            allocation("S2", "T1", "G01"),
            allocation("S3", "T1", "G01"),
            allocation("S4", "T2", "G02"),
        ]

        rows = diagnostics.build_diagnostics(students, tutors, allocations)
        for row in rows:
            self.assertEqual(row["stream_group_size_min"], 1)
            self.assertEqual(row["stream_group_size_max"], 3)
            self.assertEqual(row["stream_group_size_range"], 2)
            self.assertEqual(json.loads(row["stream_group_sizes"]), {"T1": 3, "T2": 1})
            self.assertEqual(
                json.loads(row["overseas_country_group_distribution"]),
                {"China": {"T2": 1}, "India": {"T1": 2}},
            )
            self.assertFalse(row["overseas_stream_concentration_warning"])
        self.assertFalse(next(row for row in rows if row["tutor_id"] == "T2")["overseas_isolation_warning"])

        students[-1] = student("S4")
        concentrated = diagnostics.build_diagnostics(students, tutors, allocations)
        self.assertTrue(all(row["overseas_stream_concentration_warning"] for row in concentrated))

    def test_cli_writes_diagnostics_csv(self):
        students = [student("S1")]
        tutors = [tutor("T1")]
        allocations = [allocation("S1", "T1", "G01")]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            students_path = temp / "students.csv"
            tutors_path = temp / "tutors.csv"
            allocations_path = temp / "allocations.csv"
            output_path = temp / "diagnostics.csv"
            write_csv(students_path, students)
            write_csv(tutors_path, tutors)
            write_csv(allocations_path, allocations)

            result = diagnostics.main(
                [
                    str(students_path),
                    str(tutors_path),
                    str(allocations_path),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(result, 0)
            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(list(rows[0]), diagnostics.DIAGNOSTIC_FIELDS)


if __name__ == "__main__":
    unittest.main()
