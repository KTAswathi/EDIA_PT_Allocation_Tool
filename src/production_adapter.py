import argparse
import csv
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from excel_adapter import MAIN_NS, PACKAGE_REL_NS, REL_NS, _archive_path, _cell_value, _text
from generate_synthetic import ALLOCATION_STREAMS, STUDENT_FIELDS, TUTOR_FIELDS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "production_clean"
ENTRY_ROUTES = {"A-level", "BTEC", "Access", "Foundation", "IFP", "Postgraduate", "Other"}
QUALIFICATION_ENTRY_ROUTES = ENTRY_ROUTES - {"IFP"}
SUPPORT_LEVELS = {"0": "none", "1": "standard", "2": "complex"}

APPLICANT_HEADERS = {
    "Programme code": "programme",
    "Programme": "programme_name",
    "Student number": "student_id",
    "Sex": "sex",
    "Student status": "status",
    "Country of domicile": "country",
    "Home / overseas": "fee_status",
    "Age at entry": "age",
    "IFP Progressor?": "ifp_progressor",
    "Qualification name": "qualification_name",
    "Qualification level": "qualification_level",
}
TUTOR_STREAM_HEADERS = {
    "CS year 1": "cs_year_1",
    "Maths and CS year 1": "maths_and_cs_year_1",
    "CS with AI year 1": "cs_with_ai_year_1",
    "CS with Innov year 1": "cs_with_innov_year_1",
    "Computer Science MSc": "computer_science_msc",
    "Cyber Msc": "cyber_msc",
    "Immersive Technologies MSc": "immersive_technologies_msc",
}
TUTOR_HEADERS = {"Tutor name": "tutor_name", **TUTOR_STREAM_HEADERS}


class ProductionInputError(ValueError):
    pass


def _normalise(value):
    return " ".join((value or "").split()).casefold()


def _column(cell_reference):
    match = re.match(r"[A-Z]+", cell_reference or "")
    return match.group() if match else ""


def _read_table(path, sheet_name, header_fields):
    expected = {_normalise(header): field for header, field in header_fields.items()}
    display_headers = {_normalise(header): header for header in header_fields}
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
        sheet = next(
            (
                item
                for item in workbook.findall(f".//{{{MAIN_NS}}}sheet")
                if item.get("name") == sheet_name
            ),
            None,
        )
        if sheet is None:
            raise ProductionInputError(f"{path}: missing sheet '{sheet_name}'")
        relationship_id = sheet.get(f"{{{REL_NS}}}id")
        sheet_xml = ET.fromstring(archive.read(targets[relationship_id]))

        selected_columns = None
        header_row = None
        best_present = set()
        rows = sheet_xml.findall(f".//{{{MAIN_NS}}}row")
        for row in rows:
            cells = {_column(cell.get("r")): cell for cell in row.findall(f"{{{MAIN_NS}}}c")}
            values = {
                column: _cell_value(cell, shared_strings)
                for column, cell in cells.items()
            }
            normalised = {}
            duplicates = set()
            for column, value in values.items():
                key = _normalise(value)
                if key:
                    if key in normalised:
                        duplicates.add(key)
                    else:
                        normalised[key] = column
            present = set(expected) & set(normalised)
            if len(present) > len(best_present):
                best_present = present
            if set(expected) <= set(normalised):
                duplicated_required = set(expected) & duplicates
                if duplicated_required:
                    names = ", ".join(
                        display_headers[key] for key in sorted(duplicated_required)
                    )
                    raise ProductionInputError(
                        f"{path}: duplicate required headers on row {row.get('r')}: {names}"
                    )
                selected_columns = {
                    normalised[key]: field
                    for key, field in expected.items()
                    if field is not None
                }
                header_row = int(row.get("r", "0"))
                break
        if selected_columns is None:
            missing = ", ".join(
                display_headers[key] for key in sorted(set(expected) - best_present)
            )
            raise ProductionInputError(
                f"{path}: missing required headers on sheet '{sheet_name}': {missing}"
            )

        records = []
        for row in rows:
            row_number = int(row.get("r", "0"))
            if row_number <= header_row:
                continue
            cells = {_column(cell.get("r")): cell for cell in row.findall(f"{{{MAIN_NS}}}c")}
            record = {
                field: _cell_value(cells[column], shared_strings) if column in cells else ""
                for column, field in selected_columns.items()
            }
            if any(record.values()):
                records.append((row_number, record))
        return records


def _read_config(path, required, optional=()):
    allowed = set(required) | set(optional)
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise ProductionInputError(f"{path}: duplicate config column")
        missing = set(required) - set(fields)
        unknown = set(fields) - allowed
        if missing:
            raise ProductionInputError(
                f"{path}: missing config columns: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ProductionInputError(
                f"{path}: unknown config columns: {', '.join(sorted(unknown))}"
            )
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row and any((value or "").strip() for value in row[None]):
                raise ProductionInputError(f"{path} row {row_number}: surplus config values")
            cleaned = {field: (row.get(field) or "").strip() for field in fields}
            if any(cleaned.values()):
                rows.append((row_number, cleaned))
        return rows


def load_programme_map(path):
    mapping = {}
    for row_number, row in _read_config(path, ("programme_code", "allocation_stream")):
        code = row["programme_code"]
        stream = row["allocation_stream"]
        if not code or not stream:
            raise ProductionInputError(f"{path} row {row_number}: programme mapping cannot be blank")
        if stream not in ALLOCATION_STREAMS:
            raise ProductionInputError(
                f"{path} row {row_number}: invalid allocation_stream '{stream}'"
            )
        if code in mapping:
            raise ProductionInputError(f"{path}: duplicate programme_code '{code}'")
        mapping[code] = stream
    if not mapping:
        raise ProductionInputError(f"{path}: programme mapping is empty")
    return mapping


def load_qualification_map(path):
    if path is None:
        return {}
    mapping = {}
    required = ("qualification_name", "qualification_level", "entry_route")
    for row_number, row in _read_config(path, required):
        name = _normalise(row["qualification_name"])
        level = _normalise(row["qualification_level"])
        route = row["entry_route"]
        if not name or not level:
            raise ProductionInputError(
                f"{path} row {row_number}: qualification name and level are required"
            )
        if route not in QUALIFICATION_ENTRY_ROUTES:
            raise ProductionInputError(f"{path} row {row_number}: invalid entry_route '{route}'")
        key = (name, level)
        if key in mapping:
            raise ProductionInputError(f"{path} row {row_number}: duplicate qualification mapping")
        mapping[key] = route
    return mapping


def load_student_config(path):
    if path is None:
        return {}
    required = ("student_number", "support_need", "entry_route", "returning_student")
    config = {}
    for row_number, row in _read_config(path, required):
        student_id = row["student_number"]
        if not student_id:
            raise ProductionInputError(f"{path} row {row_number}: student_number is required")
        if student_id in config:
            raise ProductionInputError(f"{path}: duplicate student_number '{student_id}'")
        support = row["support_need"]
        route = row["entry_route"]
        returning = row["returning_student"]
        if support and support not in SUPPORT_LEVELS:
            raise ProductionInputError(
                f"{path} row {row_number}: support_need must be 0, 1 or 2"
            )
        if route and route not in ENTRY_ROUTES:
            raise ProductionInputError(f"{path} row {row_number}: invalid entry_route '{route}'")
        if returning and returning not in {"True", "False"}:
            raise ProductionInputError(
                f"{path} row {row_number}: returning_student must be True or False"
            )
        config[student_id] = {
            "support_need": SUPPORT_LEVELS.get(support, ""),
            "entry_route": route,
            "returning_student": returning,
        }
    return config


def load_tutor_config(path):
    required = (
        "tutor_name",
        "tutor_id",
        "dbs_checked",
        "experience_level",
        "preferred_capacity",
    )
    config = {}
    tutor_ids = set()
    for row_number, row in _read_config(path, required, ("admin_role",)):
        name_key = _normalise(row["tutor_name"])
        tutor_id = row["tutor_id"]
        if not name_key or not tutor_id:
            raise ProductionInputError(
                f"{path} row {row_number}: tutor_name and tutor_id are required"
            )
        if name_key in config:
            raise ProductionInputError(f"{path} row {row_number}: duplicate tutor_name")
        if tutor_id in tutor_ids:
            raise ProductionInputError(f"{path}: duplicate tutor_id '{tutor_id}'")
        dbs = row["dbs_checked"]
        if dbs not in {"True", "False"}:
            raise ProductionInputError(
                f"{path} row {row_number}: dbs_checked must be explicitly True or False"
            )
        experience = row["experience_level"]
        if experience and experience not in {"standard", "experienced"}:
            raise ProductionInputError(
                f"{path} row {row_number}: invalid experience_level '{experience}'"
            )
        capacity = row["preferred_capacity"] or "8"
        try:
            if int(capacity) <= 0 or str(int(capacity)) != capacity:
                raise ValueError
        except ValueError as error:
            raise ProductionInputError(
                f"{path} row {row_number}: preferred_capacity must be a positive integer"
            ) from error
        config[name_key] = {
            "tutor_id": tutor_id,
            "dbs_checked": dbs,
            "experience_level": experience,
            "preferred_capacity": capacity,
            "admin_role": row.get("admin_role", ""),
        }
        tutor_ids.add(tutor_id)
    return config


def _ifp_value(value, student_id):
    normalised = _normalise(value)
    if not normalised:
        return None
    if normalised in {"1", "y", "yes", "true"}:
        return True
    if normalised in {"0", "n", "no", "false"}:
        return False
    raise ProductionInputError(
        f"student '{student_id}': IFP Progressor? must be an explicit yes/no value"
    )


def _age(value, student_id):
    value = value.strip()
    try:
        age = int(value)
    except ValueError as error:
        raise ProductionInputError(
            f"student '{student_id}': Age at entry must be an integer"
        ) from error
    if age < 0:
        raise ProductionInputError(f"student '{student_id}': Age at entry is invalid")
    return str(age)


def adapt_students(records, programme_map, student_config, qualification_map):
    students = []
    warnings = []
    if not records:
        warnings.append("Accepted Applicants contains no applicant rows")
        for student_id in sorted(student_config):
            warnings.append(f"manual student config '{student_id}' has no Accepted Applicants row")
        return students, warnings
    seen = set()
    for row_number, source in records:
        student_id = source["student_id"].strip()
        if not student_id:
            raise ProductionInputError(f"applicant row {row_number}: Student number is required")
        if student_id in seen:
            raise ProductionInputError(f"duplicate Student number '{student_id}'")
        seen.add(student_id)

        programme = source["programme"].strip()
        if programme not in programme_map:
            raise ProductionInputError(
                f"student '{student_id}': unknown programme code '{programme}'"
            )
        manual = student_config.get(student_id, {})
        ifp = _ifp_value(source["ifp_progressor"], student_id)
        manual_route = manual.get("entry_route", "")
        if ifp is True and manual_route and manual_route != "IFP":
            raise ProductionInputError(
                f"student '{student_id}': manual entry_route conflicts with IFP Progressor?"
            )
        if ifp is True:
            entry_route = "IFP"
        elif manual_route:
            entry_route = manual_route
        else:
            qualification_key = (
                _normalise(source["qualification_name"]),
                _normalise(source["qualification_level"]),
            )
            entry_route = qualification_map.get(qualification_key, "")

        age = _age(source["age"], student_id)

        fee_status = source["fee_status"].strip()
        if fee_status:
            fee_status = {"home": "Home", "overseas": "Overseas"}.get(
                fee_status.casefold(), ""
            )
            if not fee_status:
                raise ProductionInputError(
                    f"student '{student_id}': Home / overseas must be Home or Overseas"
                )

        student = {
            "student_id": student_id,
            "programme": programme,
            "programme_name": source["programme_name"].strip(),
            "allocation_stream": programme_map[programme],
            "sex": source["sex"].strip(),
            "country": source["country"].strip(),
            "fee_status": fee_status,
            "year_of_study": "",
            "status": source["status"].strip(),
            "age": age,
            "mature_student": "True" if int(age) >= 21 else "False",
            "entry_route": entry_route,
            "returning_student": manual.get("returning_student", ""),
            "support_need": manual.get("support_need", ""),
        }
        students.append(student)
        for field in ("year_of_study", "entry_route", "returning_student", "support_need"):
            if not student[field]:
                warnings.append(f"student '{student_id}': {field} is unknown and left blank")
        for field in ("programme_name", "sex", "country", "fee_status", "status"):
            if not student[field]:
                warnings.append(f"student '{student_id}': {field} is blank in Accepted Applicants")

    for student_id in sorted(set(student_config) - seen):
        warnings.append(f"manual student config '{student_id}' has no Accepted Applicants row")
    return students, warnings


def adapt_tutors(records, tutor_config):
    tutors = []
    warnings = []
    seen_names = set()
    used_config = set()
    for row_number, source in records:
        tutor_name = source["tutor_name"].strip()
        markers = {stream: source[stream].strip() for stream in ALLOCATION_STREAMS}
        if not tutor_name:
            raise ProductionInputError(f"Tutor List row {row_number}: Tutor name is required")
        name_key = _normalise(tutor_name)
        if name_key in seen_names:
            raise ProductionInputError(f"Tutor List: duplicate Tutor name on row {row_number}")
        seen_names.add(name_key)
        for stream, marker in markers.items():
            if marker not in {"0", "1"}:
                raise ProductionInputError(
                    f"Tutor List row {row_number}: {stream} availability must be 0 or 1"
                )
        eligible = [stream for stream in ALLOCATION_STREAMS if markers[stream] == "1"]
        if not eligible:
            continue
        if name_key not in tutor_config:
            raise ProductionInputError(
                f"Tutor List row {row_number}: available tutor is missing annual config and DBS"
            )
        manual = tutor_config[name_key]
        used_config.add(name_key)
        tutor = {
            "tutor_id": manual["tutor_id"],
            "tutor_name": tutor_name,
            "eligible_allocation_streams": "|".join(eligible),
            **{stream: "yes" if stream in eligible else "no" for stream in ALLOCATION_STREAMS},
            "dbs_checked": manual["dbs_checked"],
            "experience_level": manual["experience_level"],
            "preferred_capacity": manual["preferred_capacity"],
        }
        tutors.append(tutor)
        if not tutor["experience_level"]:
            warnings.append(
                f"tutor '{tutor['tutor_id']}': experience_level is unknown and left blank"
            )
    for name_key in sorted(set(tutor_config) - used_config):
        warnings.append(f"annual tutor config '{name_key}' is not an available Tutor List row")
    if not tutors:
        warnings.append("Tutor List contains no tutors with a 1 eligibility marker")
    return tutors, warnings


def adapt_production(
    applicants_workbook,
    tutors_workbook,
    programme_map_path,
    tutor_config_path,
    student_config_path=None,
    qualification_map_path=None,
):
    programme_map = load_programme_map(programme_map_path)
    tutor_config = load_tutor_config(tutor_config_path)
    student_config = load_student_config(student_config_path)
    qualification_map = load_qualification_map(qualification_map_path)
    applicant_rows = _read_table(applicants_workbook, "Report", APPLICANT_HEADERS)
    tutor_rows = _read_table(tutors_workbook, "Tutor List", TUTOR_HEADERS)
    students, student_warnings = adapt_students(
        applicant_rows, programme_map, student_config, qualification_map
    )
    tutors, tutor_warnings = adapt_tutors(tutor_rows, tutor_config)
    return students, tutors, student_warnings + tutor_warnings


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(students, tutors, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "students.csv", STUDENT_FIELDS, students)
    _write_csv(output_dir / "tutors.csv", TUTOR_FIELDS, tutors)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("applicants_workbook", type=Path)
    parser.add_argument("tutors_workbook", type=Path)
    parser.add_argument("--programme-map", type=Path, required=True)
    parser.add_argument("--tutor-config", type=Path, required=True)
    parser.add_argument("--student-config", type=Path)
    parser.add_argument("--qualification-map", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        students, tutors, warnings = adapt_production(
            args.applicants_workbook,
            args.tutors_workbook,
            args.programme_map,
            args.tutor_config,
            args.student_config,
            args.qualification_map,
        )
        write_outputs(students, tutors, args.output_dir)
    except (OSError, csv.Error, BadZipFile, ET.ParseError, ProductionInputError) as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"students: {len(students)}")
    print(f"tutors: {len(tutors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
