import io
import posixpath
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


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
from test_run_allocation import group_sizes, read_csv


STREAMS = [
    "cs_year_1",
    "maths_and_cs_year_1",
    "cs_with_ai_year_1",
    "cs_with_innov_year_1",
    "computer_science_msc",
    "cyber_msc",
    "immersive_technologies_msc",
]

PROGRAMMES = {
    "cs_year_1": [
        ("CS-BSC", "Computer Science (BSc)"),
        ("CS-MENG", "Computer Science (MEng)"),
    ],
    "maths_and_cs_year_1": [
        ("MCS-BSC", "Mathematics and Computer Science (BSc)"),
        ("MCS-MENG", "Mathematics and Computer Science (MEng)"),
    ],
    "cs_with_ai_year_1": [
        ("AI-BSC", "Computer Science with Artificial Intelligence (BSc)"),
        ("AI-MENG", "Computer Science with Artificial Intelligence (MEng)"),
    ],
    "cs_with_innov_year_1": [
        ("INNOV-BSC", "Computer Science with Innovation (BSc)"),
        ("INNOV-MENG", "Computer Science with Innovation (MEng)"),
    ],
    "computer_science_msc": [
        ("CS-MSC", "Computer Science (MSc)"),
        ("ADV-CS-MSC", "Advanced Computer Science (MSc)"),
    ],
    "cyber_msc": [
        ("CYBER-MSC", "Cyber Security (MSc)"),
        ("ADV-CYBER-MSC", "Advanced Cyber Security (MSc)"),
    ],
    "immersive_technologies_msc": [
        ("IMM-MSC", "Immersive Technologies (MSc)"),
        ("XR-MSC", "Extended Reality (MSc)"),
    ],
}

FEASIBLE_COUNTS = [86, 86, 86, 86, 86, 85, 85]
IMPOSSIBLE_ID = "IMP-U18-001"


def workbook_data_rows(path):
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office_rel_ns = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall(f"{{{package_rel_ns}}}Relationship")
        }
        counts = {}
        for sheet in workbook.findall(f".//{{{main_ns}}}sheet"):
            relationship_id = sheet.attrib[f"{{{office_rel_ns}}}id"]
            target = targets[relationship_id]
            member = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            worksheet = ET.fromstring(archive.read(member))
            rows = worksheet.findall(f".//{{{main_ns}}}sheetData/{{{main_ns}}}row")
            counts[sheet.attrib["name"]] = max(len(rows) - 1, 0)
    return counts


class LargeEndToEndSmokeTest(unittest.TestCase):
    def _write_inputs(self, directory):
        applicants = directory / "applicants.xlsx"
        tutor_workbook = directory / "tutors.xlsx"
        programme_map = directory / "programme_map.csv"
        tutor_config = directory / "tutor_config.csv"
        student_config = directory / "student_config.csv"
        qualification_map = directory / "qualification_map.csv"

        applicant_rows = []
        student_config_rows = []
        student_index = 0
        qualification_options = [
            ("Fictional A level", "Level 3"),
            ("Fictional BTEC", "Level 3"),
            ("Fictional Access Diploma", "Level 3"),
            ("Fictional Foundation", "Level 3"),
        ]
        overseas_countries = ["India", "China", "Nigeria", "France"]

        for stream_index, (stream, count) in enumerate(
            zip(STREAMS, FEASIBLE_COUNTS)
        ):
            postgraduate = stream.endswith("_msc")
            for local_index in range(count):
                student_index += 1
                student_id = f"STU-{student_index:04d}"
                programme_code, programme_name = PROGRAMMES[stream][local_index % 2]
                sex = ["F", "M", "Non-binary"][local_index % 3]
                overseas = local_index % 3 != 0
                country = (
                    overseas_countries[(local_index + stream_index) % 4]
                    if overseas
                    else "England"
                )
                fee_status = "Overseas" if overseas else "Home"
                if postgraduate:
                    age = 21 + local_index % 15
                    ifp = "No"
                    qualification_name = "Fictional postgraduate qualification"
                    qualification_level = "Level 7"
                else:
                    age = (
                        17
                        if stream != "cs_with_innov_year_1" and local_index < 2
                        else 18 + local_index % 14
                    )
                    ifp = "Yes" if local_index % 13 == 0 else "No"
                    qualification_name, qualification_level = qualification_options[
                        local_index % len(qualification_options)
                    ]
                applicant_rows.append(
                    [
                        programme_code,
                        programme_name,
                        student_id,
                        sex,
                        "Accepted",
                        country,
                        fee_status,
                        age,
                        ifp,
                        "",
                        "",
                        qualification_name,
                        qualification_level,
                    ]
                )
                student_config_rows.append(
                    {
                        "student_number": student_id,
                        "support_need": str(local_index % 3),
                        "entry_route": "",
                        "returning_student": (
                            "True" if student_index % 53 == 0 else "False"
                        ),
                    }
                )

        impossible_code, impossible_name = PROGRAMMES["cs_with_innov_year_1"][0]
        applicant_rows.append(
            [
                impossible_code,
                impossible_name,
                IMPOSSIBLE_ID,
                "F",
                "Accepted",
                "India",
                "Overseas",
                17,
                "Yes",
                "",
                "",
                "Fictional Foundation",
                "Level 3",
            ]
        )
        student_config_rows.append(
            {
                "student_number": IMPOSSIBLE_ID,
                "support_need": "2",
                "entry_route": "",
                "returning_student": "False",
            }
        )

        write_xlsx(
            applicants,
            "Report",
            {
                1: [None, None, "Fictional accepted applicants"],
                7: [None, None, *APPLICANT_HEADERS],
                **{
                    8 + index: [None, None, *row]
                    for index, row in enumerate(applicant_rows)
                },
            },
        )

        tutor_rows = []
        tutor_config_rows = []
        capacities = [6, 8, 10]
        for stream_index, stream in enumerate(STREAMS):
            for tutor_index in range(3):
                tutor_name = f"Tutor {stream_index + 1:02d}-{tutor_index + 1:02d}"
                markers = [0] * len(STREAMS)
                markers[stream_index] = 1
                tutor_rows.append([tutor_name, "available", *markers])
                tutor_config_rows.append(
                    {
                        "tutor_name": tutor_name,
                        "tutor_id": f"T{stream_index + 1:02d}{tutor_index + 1:02d}",
                        "dbs_checked": str(
                            stream != "cs_with_innov_year_1"
                            and tutor_index in (0, 2)
                        ),
                        "experience_level": (
                            "experienced" if stream == "cyber_msc" else "standard"
                        ),
                        "preferred_capacity": str(capacities[tutor_index]),
                        "admin_role": "",
                    }
                )
        write_xlsx(
            tutor_workbook,
            "Tutor List",
            {
                2: TUTOR_HEADERS,
                **{3 + index: row for index, row in enumerate(tutor_rows)},
            },
            shared_strings=True,
        )

        write_csv(
            programme_map,
            ["programme_code", "allocation_stream"],
            [
                {"programme_code": code, "allocation_stream": stream}
                for stream in STREAMS
                for code, _ in PROGRAMMES[stream]
            ],
        )
        write_csv(
            tutor_config,
            [
                "tutor_name",
                "tutor_id",
                "dbs_checked",
                "experience_level",
                "preferred_capacity",
                "admin_role",
            ],
            tutor_config_rows,
        )
        write_csv(
            student_config,
            ["student_number", "support_need", "entry_route", "returning_student"],
            student_config_rows,
        )
        write_csv(
            qualification_map,
            ["qualification_name", "qualification_level", "entry_route"],
            [
                {
                    "qualification_name": "Fictional A level",
                    "qualification_level": "Level 3",
                    "entry_route": "A-level",
                },
                {
                    "qualification_name": "Fictional BTEC",
                    "qualification_level": "Level 3",
                    "entry_route": "BTEC",
                },
                {
                    "qualification_name": "Fictional Access Diploma",
                    "qualification_level": "Level 3",
                    "entry_route": "Access",
                },
                {
                    "qualification_name": "Fictional Foundation",
                    "qualification_level": "Level 3",
                    "entry_route": "Foundation",
                },
                {
                    "qualification_name": "Fictional postgraduate qualification",
                    "qualification_level": "Level 7",
                    "entry_route": "Postgraduate",
                },
            ],
        )
        return {
            "applicants": applicants,
            "tutors": tutor_workbook,
            "programme_map": programme_map,
            "tutor_config": tutor_config,
            "student_config": student_config,
            "qualification_map": qualification_map,
        }

    @staticmethod
    def _arguments(inputs, output):
        return [
            str(inputs["applicants"]),
            str(inputs["tutors"]),
            "--programme-map",
            str(inputs["programme_map"]),
            "--tutor-config",
            str(inputs["tutor_config"]),
            "--student-config",
            str(inputs["student_config"]),
            "--qualification-map",
            str(inputs["qualification_map"]),
            "--output-dir",
            str(output),
        ]

    def test_large_end_to_end_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inputs = self._write_inputs(directory)
            first_output = directory / "first"
            second_output = directory / "second"
            exhaustive = run_allocation.production_optimizer.optimizer

            stdout = io.StringIO()
            stderr = io.StringIO()
            started = time.perf_counter()
            with (
                patch.object(
                    exhaustive,
                    "build_candidate_sets",
                    side_effect=AssertionError("exhaustive search called"),
                ),
                patch.object(
                    exhaustive,
                    "feasible_assignments",
                    side_effect=AssertionError("exhaustive search called"),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                first_result = run_allocation.main(
                    self._arguments(inputs, first_output)
                )
            first_runtime = time.perf_counter() - started

            repeat_stdout = io.StringIO()
            repeat_stderr = io.StringIO()
            repeat_started = time.perf_counter()
            with (
                patch.object(
                    exhaustive,
                    "build_candidate_sets",
                    side_effect=AssertionError("exhaustive search called"),
                ),
                patch.object(
                    exhaustive,
                    "feasible_assignments",
                    side_effect=AssertionError("exhaustive search called"),
                ),
                redirect_stdout(repeat_stdout),
                redirect_stderr(repeat_stderr),
            ):
                second_result = run_allocation.main(
                    self._arguments(inputs, second_output)
                )
            repeat_runtime = time.perf_counter() - repeat_started

            self.assertEqual(1, first_result, stderr.getvalue())
            self.assertEqual(1, second_result, repeat_stderr.getvalue())
            self.assertIn(IMPOSSIBLE_ID, stderr.getvalue())
            self.assertIn(IMPOSSIBLE_ID, repeat_stderr.getvalue())

            students = read_csv(first_output / "students.csv")
            tutors = read_csv(first_output / "tutors.csv")
            baseline = read_csv(first_output / "baseline_allocations.csv")
            final = read_csv(first_output / "final_allocations.csv")
            diagnostics = read_csv(first_output / "diagnostics.csv")
            unallocated = read_csv(first_output / "unallocated.csv")

            student_by_id = {row["student_id"]: row for row in students}
            tutor_by_id = {row["tutor_id"]: row for row in tutors}
            feasible_ids = set(student_by_id) - {IMPOSSIBLE_ID}
            final_id_counts = Counter(row["student_id"] for row in final)
            self.assertEqual(feasible_ids, set(final_id_counts))
            self.assertTrue(all(count == 1 for count in final_id_counts.values()))
            self.assertEqual(600, len(final))
            self.assertNotIn(IMPOSSIBLE_ID, final_id_counts)
            self.assertEqual(1, len(unallocated))
            self.assertEqual(IMPOSSIBLE_ID, unallocated[0]["student_id"])
            self.assertIn("under-18 safeguarding", unallocated[0]["reason"])

            for allocation in final:
                student = student_by_id[allocation["student_id"]]
                tutor = tutor_by_id[allocation["tutor_id"]]
                eligibility = set(
                    tutor["eligible_allocation_streams"].split("|")
                )
                self.assertIn(student["allocation_stream"], eligibility)
                if int(student["age"]) < 18:
                    self.assertEqual("True", tutor["dbs_checked"])

            self.assertEqual(group_sizes(baseline), group_sizes(final))
            baseline_metrics = exhaustive.tracked_metric_values(
                students, tutors, baseline
            )
            final_metrics = exhaustive.tracked_metric_values(students, tutors, final)
            self.assertTrue(
                all(after <= before for before, after in zip(baseline_metrics, final_metrics)),
                (baseline_metrics, final_metrics),
            )

            stream_codes = defaultdict(set)
            for student in students:
                stream_codes[student["allocation_stream"]].add(student["programme"])
            self.assertEqual(set(STREAMS), set(stream_codes))
            self.assertTrue(all(len(stream_codes[stream]) == 2 for stream in STREAMS))
            self.assertEqual({"Home", "Overseas"}, {row["fee_status"] for row in students})
            self.assertGreater(
                max(Counter(
                    row["country"] for row in students if row["fee_status"] == "Overseas"
                ).values()),
                1,
            )
            self.assertGreater(len({row["sex"] for row in students}), 1)
            self.assertIn("True", {row["mature_student"] for row in students})
            self.assertEqual(
                {"A-level", "BTEC", "Access", "Foundation", "IFP", "Postgraduate"},
                {row["entry_route"] for row in students},
            )
            self.assertEqual(
                {"none", "standard", "complex"},
                {row["support_need"] for row in students},
            )
            self.assertIn("True", {row["returning_student"] for row in students})
            self.assertTrue(any(int(row["age"]) < 18 for row in students))
            self.assertEqual({"True", "False"}, {row["dbs_checked"] for row in tutors})
            self.assertEqual(
                {"standard", "experienced"},
                {row["experience_level"] for row in tutors},
            )
            self.assertGreater(len({row["preferred_capacity"] for row in tutors}), 1)

            workbook = first_output / "PT_Allocation_Output.xlsx"
            self.assertTrue(workbook.is_file())
            workbook_counts = workbook_data_rows(workbook)
            self.assertEqual(len(final), workbook_counts["Proposed Allocations"])
            self.assertEqual(len(diagnostics), workbook_counts["Group Summary"])
            self.assertEqual(len(unallocated), workbook_counts["Unallocated"])

            first_files = sorted(
                path.relative_to(first_output) for path in first_output.iterdir()
            )
            second_files = sorted(
                path.relative_to(second_output) for path in second_output.iterdir()
            )
            self.assertEqual(first_files, second_files)
            for relative_path in first_files:
                self.assertEqual(
                    (first_output / relative_path).read_bytes(),
                    (second_output / relative_path).read_bytes(),
                    str(relative_path),
                )

            print(
                "SMOKE_RESULT "
                f"students={len(students)} tutors={len(tutors)} streams={len(STREAMS)} "
                f"allocated={len(final)} unallocated={len(unallocated)} "
                f"baseline_metrics={baseline_metrics} final_metrics={final_metrics} "
                f"first_runtime={first_runtime:.3f}s repeat_runtime={repeat_runtime:.3f}s "
                f"workbook_allocations={workbook_counts['Proposed Allocations']} "
                f"workbook_groups={workbook_counts['Group Summary']}"
            )


if __name__ == "__main__":
    unittest.main()
