import csv
import posixpath
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import diagnostics
import excel_report
import test_run_allocation as runner_tests


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EXPECTED_SHEETS = [
    "Run Summary",
    "Proposed Allocations",
    "Group Summary",
    "Manual Review",
    "EDIA Diagnostics",
    "Unallocated",
]


class WorkbookReader:
    def __init__(self, path):
        self.path = Path(path)
        with ZipFile(self.path) as archive:
            self.valid = archive.testzip() is None
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        targets = {
            item.get("Id"): item.get("Target")
            for item in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }
        self.sheets = {}
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            relationship_id = sheet.get(f"{{{REL_NS}}}id")
            target = targets[relationship_id]
            self.sheets[sheet.get("name")] = posixpath.normpath(
                posixpath.join("xl", target)
            )

    @property
    def sheet_names(self):
        return list(self.sheets)

    def root(self, name):
        with ZipFile(self.path) as archive:
            return ET.fromstring(archive.read(self.sheets[name]))

    @staticmethod
    def _column(reference):
        letters = re.match(r"[A-Z]+", reference).group()
        value = 0
        for letter in letters:
            value = value * 26 + ord(letter) - 64
        return value

    def rows(self, name):
        rows = []
        for row in self.root(name).findall(f".//{{{MAIN_NS}}}row"):
            values = {}
            for cell in row.findall(f"{{{MAIN_NS}}}c"):
                column = self._column(cell.get("r"))
                if cell.get("t") == "inlineStr":
                    value = "".join(
                        item.text or ""
                        for item in cell.findall(f".//{{{MAIN_NS}}}t")
                    )
                else:
                    value_node = cell.find(f"{{{MAIN_NS}}}v")
                    value = "" if value_node is None else value_node.text or ""
                    if cell.get("t") == "b":
                        value = "True" if value == "1" else "False"
                values[column] = value
            rows.append(
                [values.get(index, "") for index in range(1, max(values, default=0) + 1)]
            )
        return rows


def csv_rows(path, fields):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [[row[field] for field in fields] for row in csv.DictReader(handle)]


class ExcelReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = runner_tests.RunAllocationTests(
            "test_complete_successful_end_to_end_run"
        )
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def _success(self, name):
        output = self.fixture.directory / name
        result, _, stderr = self.fixture._run(output)
        self.assertEqual(result, 0, stderr)
        workbook = output / "PT_Allocation_Output.xlsx"
        self.assertTrue(workbook.exists())
        return output, WorkbookReader(workbook)

    def test_success_workbook_sheets_and_data_match_csv_outputs(self):
        output, workbook = self._success("workbook_data")

        self.assertTrue(workbook.valid)
        self.assertEqual(workbook.sheet_names, EXPECTED_SHEETS)

        proposed = workbook.rows("Proposed Allocations")
        self.assertEqual(proposed[0], excel_report.ALLOCATION_FIELDS)
        self.assertEqual(
            proposed[1:],
            csv_rows(output / "final_allocations.csv", excel_report.ALLOCATION_FIELDS),
        )
        self.assertEqual(len(proposed) - 1, 4)

        groups = workbook.rows("Group Summary")
        self.assertEqual(groups[0], excel_report.GROUP_SUMMARY_FIELDS)
        self.assertEqual(
            groups[1:],
            csv_rows(output / "diagnostics.csv", excel_report.GROUP_SUMMARY_FIELDS),
        )
        self.assertEqual(len(groups) - 1, 2)

        full_diagnostics = workbook.rows("EDIA Diagnostics")
        self.assertEqual(full_diagnostics[0], diagnostics.DIAGNOSTIC_FIELDS)
        self.assertEqual(
            full_diagnostics[1:],
            csv_rows(output / "diagnostics.csv", diagnostics.DIAGNOSTIC_FIELDS),
        )
        self.assertEqual(workbook.rows("Unallocated"), [excel_report.UNALLOCATED_FIELDS])

        summary = dict(workbook.rows("Run Summary")[1:])
        self.assertEqual(
            summary,
            {
                "students supplied": "4",
                "students allocated": "4",
                "students unallocated": "0",
                "tutor groups": "2",
                "smallest group": "1",
                "largest group": "3",
                "total soft warnings": "3",
                "returning/manual-review groups": "1",
            },
        )

    def test_all_sheets_have_staff_friendly_table_formatting(self):
        _, workbook = self._success("workbook_formatting")

        for name in EXPECTED_SHEETS:
            root = workbook.root(name)
            pane = root.find(f".//{{{MAIN_NS}}}pane")
            self.assertIsNotNone(pane, name)
            self.assertEqual(pane.get("state"), "frozen")
            self.assertEqual(pane.get("topLeftCell"), "A2")
            self.assertIsNotNone(root.find(f"{{{MAIN_NS}}}autoFilter"), name)
            columns = root.findall(f".//{{{MAIN_NS}}}col")
            self.assertTrue(columns, name)
            self.assertTrue(
                all(10 <= float(column.get("width")) <= 50 for column in columns),
                name,
            )
            header = root.find(f".//{{{MAIN_NS}}}row[@r='1']/{{{MAIN_NS}}}c")
            self.assertEqual(header.get("s"), "1", name)

    def test_manual_review_contains_returning_student_and_adapter_warnings(self):
        output, workbook = self._success("manual_review")
        rows = workbook.rows("Manual Review")
        records = [dict(zip(rows[0], row)) for row in rows[1:]]

        returning = [
            row for row in records if row["review_type"] == "Returning/repeating student"
        ]
        self.assertEqual(len(returning), 1)
        self.assertEqual(returning[0]["student_id"], "S001")
        self.assertEqual(returning[0]["tutor_id"], "T001")
        self.assertEqual(returning[0]["group_number"], "G01")

        expected_warnings = (output / "warnings.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        workbook_warnings = [
            row["detail"] for row in records if row["review_type"] == "Adapter warning"
        ]
        self.assertEqual(workbook_warnings, expected_warnings)
        self.assertTrue(
            any("year_of_study is unknown" in warning for warning in workbook_warnings)
        )

    def test_impossible_u18_is_reported_in_workbook(self):
        self.fixture._write_impossible_inputs()
        output = self.fixture.directory / "workbook_impossible"
        result, _, stderr = self.fixture._run(output, include_optional=False)

        self.assertEqual(result, 1, stderr)
        workbook = WorkbookReader(output / "PT_Allocation_Output.xlsx")
        unallocated = workbook.rows("Unallocated")
        self.assertEqual(unallocated[0], excel_report.UNALLOCATED_FIELDS)
        self.assertEqual(unallocated[1][0], "IMP-001")
        self.assertIn("under-18 safeguarding", unallocated[1][1])
        self.assertEqual(
            unallocated[1:],
            csv_rows(output / "unallocated.csv", excel_report.UNALLOCATED_FIELDS),
        )
        self.assertEqual(
            workbook.rows("Proposed Allocations"), [excel_report.ALLOCATION_FIELDS]
        )
        self.assertEqual(
            workbook.rows("Group Summary"), [excel_report.GROUP_SUMMARY_FIELDS]
        )
        self.assertEqual(
            workbook.rows("EDIA Diagnostics"), [diagnostics.DIAGNOSTIC_FIELDS]
        )
        summary = dict(workbook.rows("Run Summary")[1:])
        self.assertEqual(summary["students supplied"], "1")
        self.assertEqual(summary["students allocated"], "0")
        self.assertEqual(summary["students unallocated"], "1")
        self.assertEqual(summary["tutor groups"], "0")

    def test_workbook_data_is_deterministic(self):
        first, first_workbook = self._success("workbook_deterministic_a")
        second, second_workbook = self._success("workbook_deterministic_b")

        self.assertEqual(first_workbook.sheet_names, second_workbook.sheet_names)
        for name in EXPECTED_SHEETS:
            self.assertEqual(first_workbook.rows(name), second_workbook.rows(name))
        self.assertEqual(
            (first / "PT_Allocation_Output.xlsx").read_bytes(),
            (second / "PT_Allocation_Output.xlsx").read_bytes(),
        )

    def test_bad_input_produces_no_workbook(self):
        runner_tests.write_csv(
            self.fixture.programmes,
            ["programme_code", "allocation_stream"],
            [{"programme_code": "P999", "allocation_stream": "cs_year_1"}],
        )
        output = self.fixture.directory / "workbook_bad_input"

        result, _, stderr = self.fixture._run(output)

        self.assertEqual(result, 2)
        self.assertIn("INPUT ERROR", stderr)
        self.assertFalse((output / "PT_Allocation_Output.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
