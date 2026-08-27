import csv
import sys
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
POPULATED_APPLICANTS_FIXTURE = ROOT / "tests" / "fixtures" / "accepted_applicants_populated.xlsx"

import generate_synthetic
import production_adapter


APPLICANT_HEADERS = [
    "Programme code",
    "Programme",
    "Student number",
    "Sex",
    "Student status",
    "Country of domicile",
    "Home / overseas",
    "Age at entry",
    "IFP Progressor?",
    "Disability code",
    "Disability name",
    "Qualification\nname",
    "Qualification level",
]
TUTOR_HEADERS = [
    "Tutor name",
    "Tutor 26-27?",
    "CS year 1",
    "Maths and CS  year 1",
    "CS with AI year 1",
    "CS with Innov year 1",
    "Computer Science MSc ",
    "Cyber Msc ",
    "Immersive Technologies MSc ",
]


def _column(number):
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def write_xlsx(path, sheet_name, rows, shared_strings=False):
    xml_rows = []
    strings = []
    string_indexes = {}
    for row_number, values in sorted(rows.items()):
        cells = []
        for column_number, value in enumerate(values, start=1):
            if value is None:
                continue
            reference = f"{_column(column_number)}{row_number}"
            if isinstance(value, int):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            elif shared_strings:
                text = str(value)
                if text not in string_indexes:
                    string_indexes[text] = len(strings)
                    strings.append(text)
                cells.append(f'<c r="{reference}" t="s"><v>{string_indexes[text]}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        if shared_strings:
            values = "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
            archive.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"{values}</sst>",
            )


def write_csv(path, fieldnames, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class ProductionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.applicants = self.directory / "applicants.xlsx"
        self.tutors = self.directory / "tutors.xlsx"
        self.programmes = self.directory / "programmes.csv"
        self.tutor_config = self.directory / "tutors.csv"
        self.student_config = self.directory / "students.csv"
        self.qualifications = self.directory / "qualifications.csv"
        self.applicant_row = [
            "P001",
            "Misleading Artificial Intelligence Programme",
            "S001",
            "F",
            "Accepted",
            "England",
            "Home",
            17,
            "Yes",
            "D1",
            "Source disability value",
            "Example qualification",
            "Level 3",
        ]
        self.tutor_rows = [
            ["Tutor Alpha", "yes but reduced", 1, 0, 0, 1, 0, 0, 1],
            ["Tutor Inactive", "no", 0, 0, 0, 0, 0, 0, 0],
        ]
        self._write_workbooks([self.applicant_row])
        write_csv(
            self.programmes,
            ["programme_code", "allocation_stream"],
            [{"programme_code": "P001", "allocation_stream": "cs_year_1"}],
        )
        self._write_tutor_config("True", "", "", "Head of example")

    def tearDown(self):
        self.temporary.cleanup()

    def _write_workbooks(self, applicant_rows, tutor_rows=None):
        write_xlsx(
            self.applicants,
            "Report",
            {
                1: [None, None, "Accepted applicants"],
                4: [None, None, "Report summary"],
                7: [None, None, *APPLICANT_HEADERS],
                **{8 + i: [None, None, *row] for i, row in enumerate(applicant_rows)},
            },
        )
        tutor_rows = self.tutor_rows if tutor_rows is None else tutor_rows
        write_xlsx(
            self.tutors,
            "Tutor List",
            {2: TUTOR_HEADERS, **{3 + i: row for i, row in enumerate(tutor_rows)}},
            shared_strings=True,
        )

    def _write_tutor_config(self, dbs, experience, capacity, admin_role=""):
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
            [
                {
                    "tutor_name": "Tutor Alpha",
                    "tutor_id": "T001",
                    "dbs_checked": dbs,
                    "experience_level": experience,
                    "preferred_capacity": capacity,
                    "admin_role": admin_role,
                }
            ],
        )

    def _adapt(self, student_config=None, qualification_map=None):
        return production_adapter.adapt_production(
            self.applicants,
            self.tutors,
            self.programmes,
            self.tutor_config,
            student_config,
            qualification_map,
        )

    def test_maps_confirmed_fields_and_current_schemas(self):
        write_csv(
            self.student_config,
            ["student_number", "support_need", "entry_route", "returning_student"],
            [
                {
                    "student_number": "S001",
                    "support_need": "1",
                    "entry_route": "",
                    "returning_student": "True",
                }
            ],
        )
        students, tutors, warnings = self._adapt(self.student_config)
        self.assertEqual(1, len(students))
        self.assertEqual(generate_synthetic.STUDENT_FIELDS, list(students[0]))
        self.assertEqual("S001", students[0]["student_id"])
        self.assertEqual("cs_year_1", students[0]["allocation_stream"])
        self.assertEqual("17", students[0]["age"])
        self.assertEqual("IFP", students[0]["entry_route"])
        self.assertEqual("standard", students[0]["support_need"])
        self.assertEqual("True", students[0]["returning_student"])
        self.assertEqual("False", students[0]["mature_student"])
        self.assertEqual(generate_synthetic.TUTOR_FIELDS, list(tutors[0]))
        self.assertEqual(
            "cs_year_1|cs_with_innov_year_1|immersive_technologies_msc",
            tutors[0]["eligible_allocation_streams"],
        )
        self.assertEqual("yes", tutors[0]["cs_with_innov_year_1"])
        self.assertEqual("yes", tutors[0]["immersive_technologies_msc"])
        self.assertEqual("True", tutors[0]["dbs_checked"])
        self.assertEqual("8", tutors[0]["preferred_capacity"])
        self.assertFalse(any("mature_student" in warning for warning in warnings))
        self.assertTrue(any("experience_level" in warning for warning in warnings))
        config = production_adapter.load_tutor_config(self.tutor_config)
        self.assertEqual("Head of example", config["tutor alpha"]["admin_role"])

    def test_populated_real_shape_fixture_maps_confirmed_student_fields(self):
        records = production_adapter._read_table(
            POPULATED_APPLICANTS_FIXTURE,
            "Report",
            production_adapter.APPLICANT_HEADERS,
        )
        students, warnings = production_adapter.adapt_students(
            records,
            {"FAKE001": "cs_year_1"},
            {},
            {},
        )
        self.assertEqual(1, len(students))
        student = students[0]
        self.assertEqual("FAKE-STU-001", student["student_id"])
        self.assertEqual("FAKE001", student["programme"])
        self.assertEqual("21", student["age"])
        self.assertEqual("Overseas", student["fee_status"])
        self.assertEqual("IFP", student["entry_route"])
        self.assertEqual("True", student["mature_student"])
        self.assertEqual("", student["support_need"])
        self.assertTrue(any("support_need" in warning for warning in warnings))

    def test_disability_and_qualification_are_not_inferred(self):
        row = list(self.applicant_row)
        row[8] = "No"
        self._write_workbooks([row])
        students, _, warnings = self._adapt()
        self.assertEqual("", students[0]["support_need"])
        self.assertEqual("", students[0]["entry_route"])
        self.assertTrue(any("support_need" in warning for warning in warnings))
        self.assertTrue(any("entry_route" in warning for warning in warnings))

    def test_exact_qualification_mapping_sets_route(self):
        row = list(self.applicant_row)
        row[8] = "No"
        self._write_workbooks([row])
        write_csv(
            self.qualifications,
            ["qualification_name", "qualification_level", "entry_route"],
            [
                {
                    "qualification_name": "Example qualification",
                    "qualification_level": "Level 3",
                    "entry_route": "BTEC",
                }
            ],
        )
        students, _, _ = self._adapt(qualification_map=self.qualifications)
        self.assertEqual("BTEC", students[0]["entry_route"])

    def test_unknown_programme_code_is_not_inferred_from_name(self):
        row = list(self.applicant_row)
        row[0] = "UNKNOWN"
        self._write_workbooks([row])
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "unknown programme code"):
            self._adapt()

    def test_multiple_programme_codes_can_share_one_stream(self):
        second = list(self.applicant_row)
        second[0] = "P002"
        second[2] = "S002"
        self._write_workbooks([self.applicant_row, second])
        write_csv(
            self.programmes,
            ["programme_code", "allocation_stream"],
            [
                {"programme_code": "P001", "allocation_stream": "cs_year_1"},
                {"programme_code": "P002", "allocation_stream": "cs_year_1"},
            ],
        )
        students, _, _ = self._adapt()
        self.assertEqual(["cs_year_1", "cs_year_1"], [row["allocation_stream"] for row in students])

    def test_duplicate_student_numbers_are_rejected(self):
        self._write_workbooks([self.applicant_row, self.applicant_row])
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "duplicate Student number"):
            self._adapt()

    def test_missing_dbs_is_rejected(self):
        self._write_tutor_config("", "standard", "8")
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "dbs_checked"):
            self._adapt()

    def test_empty_applicant_export_warns(self):
        self._write_workbooks([])
        students, _, warnings = self._adapt()
        self.assertEqual([], students)
        self.assertIn("Accepted Applicants contains no applicant rows", warnings)

    def test_manual_support_levels_zero_and_two_map_exactly(self):
        second = list(self.applicant_row)
        second[2] = "S002"
        self._write_workbooks([self.applicant_row, second])
        write_csv(
            self.student_config,
            ["student_number", "support_need", "entry_route", "returning_student"],
            [
                {"student_number": "S001", "support_need": "0"},
                {"student_number": "S002", "support_need": "2"},
            ],
        )
        students, _, _ = self._adapt(self.student_config)
        self.assertEqual(["none", "complex"], [row["support_need"] for row in students])

    def test_invalid_configs_are_rejected(self):
        cases = (
            (
                self.programmes,
                ["programme_code", "allocation_stream"],
                [{"programme_code": "P001", "allocation_stream": "not_a_stream"}],
                production_adapter.load_programme_map,
            ),
            (
                self.student_config,
                ["student_number", "support_need", "entry_route", "returning_student"],
                [{"student_number": "S001", "support_need": "3"}],
                production_adapter.load_student_config,
            ),
            (
                self.qualifications,
                ["qualification_name", "qualification_level", "entry_route"],
                [{"qualification_name": "Example", "qualification_level": "3", "entry_route": "IFP"}],
                production_adapter.load_qualification_map,
            ),
        )
        for path, fields, rows, loader in cases:
            with self.subTest(path=path.name):
                write_csv(path, fields, rows)
                with self.assertRaises(production_adapter.ProductionInputError):
                    loader(path)

    def test_missing_workbook_header_and_surplus_config_values_are_rejected(self):
        incomplete_headers = [header for header in APPLICANT_HEADERS if header != "Student number"]
        write_xlsx(self.applicants, "Report", {7: [None, None, *incomplete_headers]})
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "Student number"):
            self._adapt()
        with self.programmes.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(
                [
                    ["programme_code", "allocation_stream"],
                    ["P001", "cs_year_1", "surplus"],
                ]
            )
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "surplus"):
            production_adapter.load_programme_map(self.programmes)

    def test_invalid_tutor_eligibility_markers_are_rejected(self):
        for marker in ("yes", None):
            with self.subTest(marker=marker):
                tutor_rows = [["Tutor Alpha", "yes", marker, 0, 0, 0, 0, 0, 0]]
                self._write_workbooks([self.applicant_row], tutor_rows)
                with self.assertRaisesRegex(production_adapter.ProductionInputError, "must be 0 or 1"):
                    self._adapt()

    def test_each_tutor_stream_column_maps_independently(self):
        for index, stream in enumerate(generate_synthetic.ALLOCATION_STREAMS):
            with self.subTest(stream=stream):
                markers = [0] * len(generate_synthetic.ALLOCATION_STREAMS)
                markers[index] = 1
                self._write_workbooks(
                    [self.applicant_row],
                    [["Tutor Alpha", "ignored free text", *markers]],
                )
                _, tutors, _ = self._adapt()
                self.assertEqual(stream, tutors[0]["eligible_allocation_streams"])

    def test_manual_route_conflicting_with_ifp_is_rejected(self):
        write_csv(
            self.student_config,
            ["student_number", "support_need", "entry_route", "returning_student"],
            [{"student_number": "S001", "entry_route": "Access"}],
        )
        with self.assertRaisesRegex(production_adapter.ProductionInputError, "conflicts with IFP"):
            self._adapt(self.student_config)


if __name__ == "__main__":
    unittest.main()
