import re
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


SHEET_NAMES = [
    "Run Summary",
    "Proposed Allocations",
    "Group Summary",
    "Manual Review",
    "EDIA Diagnostics",
    "Unallocated",
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
GROUP_SUMMARY_FIELDS = [
    "allocation_stream",
    "tutor_id",
    "tutor_name",
    "group_number",
    "group_size",
    "preferred_capacity",
    "Home_count",
    "Overseas_count",
    "sex_counts",
    "mature_count",
    "pathway_count",
    "support_standard_count",
    "support_complex_count",
    "under_18_count",
    "returning_count",
    "soft_warning_count",
]
MANUAL_REVIEW_FIELDS = [
    "review_type",
    "student_id",
    "allocation_stream",
    "tutor_id",
    "tutor_name",
    "group_number",
    "detail",
]
UNALLOCATED_FIELDS = ["student_id", "reason"]
INVALID_XML = re.compile(
    r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _text(value):
    return INVALID_XML.sub("", "" if value is None else str(value))


def _column(number):
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _cell(reference, value, style):
    value = escape(_text(value))
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{value}</t></is></c>'
    )


def _sheet_xml(rows):
    column_count = len(rows[0])
    row_count = len(rows)
    last_cell = f"{_column(column_count)}{row_count}"
    widths = []
    for index in range(column_count):
        width = min(max(max(len(_text(row[index])) for row in rows) + 2, 10), 50)
        widths.append(
            f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
        )
    xml_rows = []
    for row_number, values in enumerate(rows, start=1):
        cells = "".join(
            _cell(f"{_column(index)}{row_number}", value, 1 if row_number == 1 else 2)
            for index, value in enumerate(values, start=1)
        )
        height = ' ht="22" customHeight="1"' if row_number == 1 else ""
        xml_rows.append(f'<row r="{row_number}"{height}>{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{MAIN_NS}">'
        f'<dimension ref="A1:{last_cell}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{"".join(widths)}</cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last_cell}"/>'
        '</worksheet>'
    )


def _table(fields, rows):
    return [fields] + [[_text(row.get(field, "")) for field in fields] for row in rows]


def _summary_table(summary_lines):
    rows = [["Metric", "Value"]]
    for line in summary_lines:
        metric, _, value = line.partition(":")
        rows.append([metric.strip(), value.strip()])
    return rows


def _manual_review_rows(students, allocations, warnings):
    allocations_by_student = {row["student_id"]: row for row in allocations}
    rows = []
    for student in sorted(students, key=lambda row: row["student_id"]):
        if _text(student.get("returning_student", "")).strip().lower() != "true":
            continue
        allocation = allocations_by_student.get(student["student_id"], {})
        rows.append(
            {
                "review_type": "Returning/repeating student",
                "student_id": student["student_id"],
                "allocation_stream": student["allocation_stream"],
                "tutor_id": allocation.get("tutor_id", ""),
                "tutor_name": allocation.get("tutor_name", ""),
                "group_number": allocation.get("group_number", ""),
                "detail": "Manual review required",
            }
        )
    rows.extend(
        {
            "review_type": "Adapter warning",
            "student_id": "",
            "allocation_stream": "",
            "tutor_id": "",
            "tutor_name": "",
            "group_number": "",
            "detail": warning,
        }
        for warning in warnings
    )
    return rows


def _workbook_xml():
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(SHEET_NAMES, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        '<bookViews><workbookView activeTab="0"/></bookViews>'
        f'<sheets>{sheets}</sheets>'
        '</workbook>'
    )


def _workbook_relationships():
    relationships = "".join(
        f'<Relationship Id="rId{index}" Type="{REL_NS}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(SHEET_NAMES) + 1)
    )
    relationships += (
        f'<Relationship Id="rId{len(SHEET_NAMES) + 1}" Type="{REL_NS}/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PACKAGE_REL_NS}">{relationships}</Relationships>'
    )


def _content_types():
    sheets = "".join(
        '<Override '
        f'PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(SHEET_NAMES) + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f'{sheets}</Types>'
    )


ROOT_RELATIONSHIPS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<Relationships xmlns="{PACKAGE_REL_NS}">'
    f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<styleSheet xmlns="{MAIN_NS}">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="3">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/>'
    '<bgColor indexed="64"/></patternFill></fill>'
    '</fills>'
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top/><bottom style="thin"><color rgb="FFFFFFFF"/>'
    '</bottom><diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" '
    'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
    '<alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" '
    'applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def _write_member(archive, name, content):
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    archive.writestr(info, content.encode("utf-8"))


def write_report(
    path,
    summary_lines,
    students,
    allocations,
    diagnostic_rows,
    warnings,
    unallocated,
    diagnostic_fields,
):
    sheet_rows = [
        _summary_table(summary_lines),
        _table(ALLOCATION_FIELDS, allocations),
        _table(GROUP_SUMMARY_FIELDS, diagnostic_rows),
        _table(
            MANUAL_REVIEW_FIELDS,
            _manual_review_rows(students, allocations, warnings),
        ),
        _table(diagnostic_fields, diagnostic_rows),
        _table(
            UNALLOCATED_FIELDS,
            [
                {"student_id": student_id, "reason": reason}
                for student_id, reason in unallocated
            ],
        ),
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        _write_member(archive, "[Content_Types].xml", _content_types())
        _write_member(archive, "_rels/.rels", ROOT_RELATIONSHIPS)
        _write_member(archive, "xl/workbook.xml", _workbook_xml())
        _write_member(archive, "xl/_rels/workbook.xml.rels", _workbook_relationships())
        _write_member(archive, "xl/styles.xml", STYLES)
        for index, rows in enumerate(sheet_rows, start=1):
            _write_member(
                archive,
                f"xl/worksheets/sheet{index}.xml",
                _sheet_xml(rows),
            )
