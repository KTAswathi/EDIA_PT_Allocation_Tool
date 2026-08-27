import argparse
import csv
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = ROOT / "ANON_Tutor Allocations 25-26 .xlsx"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "historical_clean"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

STUDENT_SHEETS = (
    "UG Year 1",
    "CS MSc ",
    "Immersive Tech MSc",
    "Cyber MSc",
)
SHEET_PREFIXES = {
    "UG Year 1": "UG",
    "CS MSc ": "CSMSC",
    "Immersive Tech MSc": "IMM",
    "Cyber MSc": "CYBER",
}
STREAM_COLUMNS = (
    ("B", "cs_year_1"),
    ("C", "maths_and_cs_year_1"),
    ("D", "cs_with_ai_year_1"),
    ("E", "cs_with_innov_year_1"),
    ("F", "computer_science_msc"),
    ("G", "cyber_msc"),
    ("H", "immersive_technologies_msc"),
)
PIPELINE_STREAM_FIELDS = (
    "cs_year_1",
    "maths_and_cs_year_1",
    "cs_with_ai_year_1",
    "cs_with_innov_year_1",
    "computer_science_msc",
    "cyber_msc",
    "immersive_technologies_msc",
)

STUDENT_FIELDS = [
    "student_id",
    "programme",
    "programme_name",
    "allocation_stream",
    "sex",
    "country",
    "fee_status",
    "year_of_study",
    "status",
    "age",
    "mature_student",
    "entry_route",
    "returning_student",
    "support_need",
]
TUTOR_FIELDS = [
    "tutor_id",
    "tutor_name",
    "eligible_allocation_streams",
    *PIPELINE_STREAM_FIELDS,
    "dbs_checked",
    "experience_level",
    "preferred_capacity",
]
ALLOCATION_FIELDS = [
    "student_id",
    "programme",
    "programme_name",
    "allocation_stream",
    "tutor_id",
    "tutor_name",
    "group_number",
]


class WorkbookAdapterError(ValueError):
    pass


def _text(element):
    return "".join(
        node.text or "" for node in element.findall(f".//{{{MAIN_NS}}}t")
    ).strip()


def _cell_value(cell, shared_strings):
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return _text(cell)
    value = cell.findtext(f"{{{MAIN_NS}}}v", default="")
    if cell_type == "s" and value:
        return shared_strings[int(value)].strip()
    return value.strip()


def _archive_path(target):
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def read_xlsx(path):
    with ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [_text(item) for item in root.findall(f"{{{MAIN_NS}}}si")]

        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.get("Id"): _archive_path(relation.get("Target", ""))
            for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {}
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            name = sheet.get("name", "")
            relationship_id = sheet.get(f"{{{REL_NS}}}id")
            rows = []
            sheet_xml = ET.fromstring(archive.read(targets[relationship_id]))
            for row in sheet_xml.findall(f".//{{{MAIN_NS}}}row"):
                values = {}
                for cell in row.findall(f"{{{MAIN_NS}}}c"):
                    match = re.match(r"[A-Z]+", cell.get("r", ""))
                    if match:
                        values[match.group()] = _cell_value(cell, shared_strings)
                rows.append((int(row.get("r", "0")), values))
            sheets[name] = rows
        return sheets


def _normalise_name(value):
    return " ".join(value.split()).casefold()


def _student_stream(sheet_name, row):
    if sheet_name == "CS MSc ":
        return "computer_science_msc"
    if sheet_name == "Immersive Tech MSc":
        return "immersive_technologies_msc"
    if sheet_name == "Cyber MSc":
        return "cyber_msc"

    programme = f"{row.get('D', '')} {row.get('E', '')}".casefold()
    if "mathematics and computer science" in programme:
        return "maths_and_cs_year_1"
    if "artificial intelligence" in programme:
        return "cs_with_ai_year_1"
    if "innovation" in programme:
        return "cs_with_innov_year_1"
    if "computer science" in programme:
        return "cs_year_1"
    raise WorkbookAdapterError("unrecognised UG programme category")


def _is_student_row(row):
    return any(row.get(column, "") for column in "DEFGHIJ")


def adapt_workbook(path):
    sheets = read_xlsx(path)
    required = {"Tutor List", *STUDENT_SHEETS}
    missing = required - set(sheets)
    if missing:
        raise WorkbookAdapterError(f"missing sheets: {', '.join(sorted(missing))}")

    tutors = []
    tutor_ids = {}
    for row_number, row in sheets["Tutor List"]:
        source_name = row.get("A", "").strip()
        if row_number == 1 or not source_name:
            continue
        tutor_id = f"HIST-TUT-{len(tutors) + 1:03d}"
        markers = {stream: row.get(column, "").strip() for column, stream in STREAM_COLUMNS}
        eligible = [
            stream
            for _, stream in STREAM_COLUMNS
            if markers[stream].casefold().startswith("yes")
        ]
        tutors.append(
            {
                "tutor_id": tutor_id,
                "tutor_name": f"Historical Tutor {len(tutors) + 1:03d}",
                "eligible_allocation_streams": "|".join(eligible),
                **{stream: markers[stream] for stream in PIPELINE_STREAM_FIELDS},
                "dbs_checked": "",
                "experience_level": "",
                "preferred_capacity": "",
            }
        )
        name_key = _normalise_name(source_name)
        if name_key in tutor_ids:
            raise WorkbookAdapterError("duplicate Tutor List name")
        tutor_ids[name_key] = (tutor_id, tutors[-1]["tutor_name"])

    students = []
    allocations = []
    for sheet_name in STUDENT_SHEETS:
        prefix = SHEET_PREFIXES[sheet_name]
        for row_number, row in sheets[sheet_name]:
            if row_number == 1 or not _is_student_row(row):
                continue
            student_id = f"HIST-{prefix}-ROW-{row_number:04d}"
            allocation_stream = _student_stream(sheet_name, row)
            student = {
                "student_id": student_id,
                "programme": row.get("D", "").strip(),
                "programme_name": row.get("E", "").strip(),
                "allocation_stream": allocation_stream,
                "sex": row.get("F", "").strip(),
                "country": row.get("G", "").strip(),
                "fee_status": row.get("H", "").strip(),
                "year_of_study": row.get("I", "").strip(),
                "status": row.get("J", "").strip(),
                "age": "",
                "mature_student": "",
                "entry_route": "",
                "returning_student": "",
                "support_need": "",
            }
            students.append(student)

            source_tutor_name = row.get("K", "").strip()
            group_number = row.get("M", "").strip()
            if source_tutor_name or row.get("L", "").strip() or group_number:
                name_key = _normalise_name(source_tutor_name)
                if name_key and name_key not in tutor_ids:
                    tutor_id = f"HIST-TUT-{len(tutors) + 1:03d}"
                    tutor_name = f"Historical Tutor {len(tutors) + 1:03d}"
                    tutors.append(
                        {
                            "tutor_id": tutor_id,
                            "tutor_name": tutor_name,
                            "eligible_allocation_streams": "",
                            **{stream: "" for stream in PIPELINE_STREAM_FIELDS},
                            "dbs_checked": "",
                            "experience_level": "",
                            "preferred_capacity": "",
                        }
                    )
                    tutor_ids[name_key] = (tutor_id, tutor_name)
                tutor_id, tutor_name = tutor_ids.get(name_key, ("", ""))
                allocations.append(
                    {
                        "student_id": student_id,
                        "programme": student["programme"],
                        "programme_name": student["programme_name"],
                        "allocation_stream": allocation_stream,
                        "tutor_id": tutor_id,
                        "tutor_name": tutor_name,
                        "group_number": group_number,
                    }
                )

    student_ids = [student["student_id"] for student in students]
    if len(student_ids) != len(set(student_ids)):
        raise WorkbookAdapterError("duplicate generated student_id")
    return students, tutors, allocations


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(students, tutors, allocations, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "students.csv", STUDENT_FIELDS, students)
    _write_csv(output_dir / "tutors.csv", TUTOR_FIELDS, tutors)
    _write_csv(
        output_dir / "historical_allocations.csv",
        ALLOCATION_FIELDS,
        allocations,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", nargs="?", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        students, tutors, allocations = adapt_workbook(args.workbook)
        write_outputs(students, tutors, allocations, args.output_dir)
    except (OSError, BadZipFile, ET.ParseError, WorkbookAdapterError) as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 2
    print(f"students: {len(students)}")
    print(f"tutors: {len(tutors)}")
    print(f"historical allocations: {len(allocations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
