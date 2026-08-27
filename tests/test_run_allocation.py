import csv
import io
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import run_allocation
from test_production_adapter import (
    APPLICANT_HEADERS,
    TUTOR_HEADERS,
    write_csv,
    write_xlsx,
)


EXPECTED_FILES = {
    "PT_Allocation_Output.xlsx",
    "students.csv",
    "tutors.csv",
    "baseline_allocations.csv",
    "final_allocations.csv",
    "diagnostics.csv",
    "warnings.txt",
    "unallocated.csv",
    "run_summary.txt",
}


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def group_sizes(rows):
    return Counter(
        (row["allocation_stream"], row["tutor_id"]) for row in rows
    )


class RunAllocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.applicants = self.directory / "applicants.xlsx"
        self.tutor_workbook = self.directory / "tutors.xlsx"
        self.programmes = self.directory / "programmes.csv"
        self.tutor_config = self.directory / "tutor_config.csv"
        self.student_config = self.directory / "student_config.csv"
        self.qualification_map = self.directory / "qualification_map.csv"
        self._write_success_inputs()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _applicant(student_id, sex, country, fee_status, age, ifp):
        return [
            "P001",
            "Fictional Computer Science Programme",
            student_id,
            sex,
            "Accepted",
            country,
            fee_status,
            age,
            ifp,
            "",
            "",
            "Fictional qualification",
            "Level 3",
        ]

    def _write_workbooks(self, applicants, tutor_rows):
        write_xlsx(
            self.applicants,
            "Report",
            {
                1: [None, None, "Fictional accepted applicants"],
                7: [None, None, *APPLICANT_HEADERS],
                **{8 + index: [None, None, *row] for index, row in enumerate(applicants)},
            },
        )
        write_xlsx(
            self.tutor_workbook,
            "Tutor List",
            {2: TUTOR_HEADERS, **{3 + index: row for index, row in enumerate(tutor_rows)}},
            shared_strings=True,
        )

    def _write_tutor_config(self, rows):
        write_csv(
            self.tutor_config,
            [
                "tutor_name",
                "tutor_id",
                "dbs_checked",
                "experience_level",
                "preferred_capacity",
                "admin_role",
            ],
            rows,
        )

    def _write_success_inputs(self):
        applicants = [
            self._applicant("S001", "F", "England", "Home", 17, "Yes"),
            self._applicant("S002", "M", "India", "Overseas", 18, "No"),
            self._applicant("S003", "F", "England", "Home", 22, "No"),
            self._applicant("S004", "M", "China", "Overseas", 19, "Yes"),
        ]
        tutors = [
            ["Tutor Alpha", "available", 1, 0, 0, 0, 0, 0, 0],
            ["Tutor Beta", "available", 1, 0, 0, 0, 0, 0, 0],
        ]
        self._write_workbooks(applicants, tutors)
        write_csv(
            self.programmes,
            ["programme_code", "allocation_stream"],
            [{"programme_code": "P001", "allocation_stream": "cs_year_1"}],
        )
        self._write_tutor_config(
            [
                {
                    "tutor_name": "Tutor Alpha",
                    "tutor_id": "T001",
                    "dbs_checked": "True",
                    "experience_level": "standard",
                    "preferred_capacity": "1",
                },
                {
                    "tutor_name": "Tutor Beta",
                    "tutor_id": "T002",
                    "dbs_checked": "False",
                    "experience_level": "experienced",
                    "preferred_capacity": "3",
                },
            ]
        )
        write_csv(
            self.student_config,
            ["student_number", "support_need", "entry_route", "returning_student"],
            [
                {
                    "student_number": "S001",
                    "support_need": "0",
                    "entry_route": "",
                    "returning_student": "True",
                },
                {
                    "student_number": "S002",
                    "support_need": "1",
                    "entry_route": "",
                    "returning_student": "False",
                },
            ],
        )
        write_csv(
            self.qualification_map,
            ["qualification_name", "qualification_level", "entry_route"],
            [
                {
                    "qualification_name": "Fictional qualification",
                    "qualification_level": "Level 3",
                    "entry_route": "BTEC",
                }
            ],
        )

    def _write_impossible_inputs(self):
        applicants = [
            self._applicant("IMP-001", "F", "England", "Home", 17, "Yes")
        ]
        tutors = [
            ["Tutor Alpha", "available", 1, 0, 0, 0, 0, 0, 0],
            ["Tutor Beta", "available", 0, 0, 0, 0, 0, 1, 0],
        ]
        self._write_workbooks(applicants, tutors)
        self._write_tutor_config(
            [
                {
                    "tutor_name": "Tutor Alpha",
                    "tutor_id": "T001",
                    "dbs_checked": "False",
                    "experience_level": "standard",
                    "preferred_capacity": "8",
                },
                {
                    "tutor_name": "Tutor Beta",
                    "tutor_id": "T002",
                    "dbs_checked": "True",
                    "experience_level": "experienced",
                    "preferred_capacity": "8",
                },
            ]
        )

    def _run(self, output_dir, include_optional=True):
        arguments = [
            str(self.applicants),
            str(self.tutor_workbook),
            "--programme-map",
            str(self.programmes),
            "--tutor-config",
            str(self.tutor_config),
            "--output-dir",
            str(output_dir),
        ]
        if include_optional:
            arguments.extend(
                [
                    "--student-config",
                    str(self.student_config),
                    "--qualification-map",
                    str(self.qualification_map),
                ]
            )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_allocation.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_complete_successful_end_to_end_run(self):
        output = self.directory / "success"
        result, _, stderr = self._run(output)

        self.assertEqual(result, 0, stderr)
        self.assertEqual(len(read_csv(output / "students.csv")), 4)
        self.assertEqual(len(read_csv(output / "tutors.csv")), 2)
        self.assertEqual(len(read_csv(output / "final_allocations.csv")), 4)
        self.assertEqual(read_csv(output / "unallocated.csv"), [])
        summary = (output / "run_summary.txt").read_text(encoding="utf-8")
        for line in (
            "students supplied: 4",
            "students allocated: 4",
            "students unallocated: 0",
            "tutor groups: 2",
            "smallest group: 1",
            "largest group: 3",
            "total soft warnings: 3",
            "returning/manual-review groups: 1",
        ):
            self.assertIn(line, summary)

    def test_all_expected_files_are_created(self):
        output = self.directory / "all_files"
        result, _, stderr = self._run(output)

        self.assertEqual(result, 0, stderr)
        self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
        self.assertIn(
            "year_of_study is unknown",
            (output / "warnings.txt").read_text(encoding="utf-8"),
        )

    def test_final_allocation_preserves_hard_constraints(self):
        output = self.directory / "hard_constraints"
        result, _, stderr = self._run(output)
        self.assertEqual(result, 0, stderr)
        students = {row["student_id"]: row for row in read_csv(output / "students.csv")}
        tutors = {row["tutor_id"]: row for row in read_csv(output / "tutors.csv")}
        final = read_csv(output / "final_allocations.csv")

        self.assertEqual(
            Counter(row["student_id"] for row in final),
            Counter(students.keys()),
        )
        for row in final:
            student = students[row["student_id"]]
            tutor = tutors[row["tutor_id"]]
            self.assertEqual(row["allocation_stream"], student["allocation_stream"])
            self.assertIn(
                row["allocation_stream"],
                tutor["eligible_allocation_streams"].split("|"),
            )
            if int(student["age"]) < 18:
                self.assertEqual(tutor["dbs_checked"], "True")

    def test_final_group_sizes_equal_baseline(self):
        output = self.directory / "group_sizes"
        result, _, stderr = self._run(output)
        self.assertEqual(result, 0, stderr)
        baseline = read_csv(output / "baseline_allocations.csv")
        final = read_csv(output / "final_allocations.csv")
        self.assertEqual(group_sizes(final), group_sizes(baseline))

    def test_impossible_u18_exits_one_and_is_reported(self):
        self._write_impossible_inputs()
        output = self.directory / "impossible"
        result, _, stderr = self._run(output, include_optional=False)

        self.assertEqual(result, 1)
        self.assertIn("UNALLOCATED IMP-001", stderr)
        self.assertIn("under-18 safeguarding", stderr)
        self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
        unallocated = read_csv(output / "unallocated.csv")
        self.assertEqual([row["student_id"] for row in unallocated], ["IMP-001"])
        self.assertIn("under-18 safeguarding", unallocated[0]["reason"])
        self.assertEqual(read_csv(output / "baseline_allocations.csv"), [])
        self.assertEqual(read_csv(output / "final_allocations.csv"), [])

    def test_bad_config_exits_two(self):
        write_csv(
            self.programmes,
            ["programme_code", "allocation_stream"],
            [{"programme_code": "P999", "allocation_stream": "cs_year_1"}],
        )
        output = self.directory / "bad_config"
        result, _, stderr = self._run(output)

        self.assertEqual(result, 2)
        self.assertIn("INPUT ERROR", stderr)
        self.assertIn("unknown programme code 'P001'", stderr)
        self.assertFalse(output.exists())

    def test_empty_applicant_report_exits_two_without_outputs(self):
        self._write_workbooks(
            [],
            [
                ["Tutor Alpha", "available", 1, 0, 0, 0, 0, 0, 0],
                ["Tutor Beta", "available", 1, 0, 0, 0, 0, 0, 0],
            ],
        )
        output = self.directory / "empty_applicants"

        result, _, stderr = self._run(output, include_optional=False)

        self.assertEqual(result, 2)
        self.assertIn(
            "INPUT ERROR: no applicant records found; "
            "check the Accepted Applicants report",
            stderr,
        )
        self.assertFalse(output.exists())

    def test_repeated_runs_are_deterministic(self):
        first = self.directory / "deterministic_a"
        second = self.directory / "deterministic_b"
        first_result, _, first_error = self._run(first)
        second_result, _, second_error = self._run(second)

        self.assertEqual(first_result, 0, first_error)
        self.assertEqual(second_result, 0, second_error)
        for name in EXPECTED_FILES:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_separate_output_directories_do_not_interfere(self):
        first = self.directory / "separate_a"
        second = self.directory / "separate_b"
        first_result, _, first_error = self._run(first)
        self.assertEqual(first_result, 0, first_error)
        original = (first / "final_allocations.csv").read_bytes()
        sentinel = first / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        second_result, _, second_error = self._run(second)

        self.assertEqual(second_result, 0, second_error)
        self.assertEqual((first / "final_allocations.csv").read_bytes(), original)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertTrue((second / "final_allocations.csv").exists())


if __name__ == "__main__":
    unittest.main()
