import argparse
import csv
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "output" / "allocations.csv"
OUTPUT_FIELDS = [
    "student_id",
    "programme",
    "programme_name",
    "allocation_stream",
    "tutor_id",
    "tutor_name",
    "group_number",
]
STUDENT_REQUIRED_COLUMNS = {
    "student_id",
    "programme",
    "programme_name",
    "allocation_stream",
    "sex",
    "country",
    "fee_status",
    "age",
    "mature_student",
    "entry_route",
    "returning_student",
    "support_need",
}
TUTOR_REQUIRED_COLUMNS = {
    "tutor_id",
    "tutor_name",
    "eligible_allocation_streams",
    "dbs_checked",
    "experience_level",
    "preferred_capacity",
}


class InputValidationError(ValueError):
    pass


def read_csv(path, required_columns):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise InputValidationError(
                f"{path}: missing required columns: {', '.join(sorted(missing))}"
            )
        return list(reader)


def validate_unique_ids(rows, field, label):
    seen = set()
    for row_number, row in enumerate(rows, start=2):
        value = (row.get(field) or "").strip()
        if not value:
            raise InputValidationError(f"{label} row {row_number}: {field} must be non-empty")
        if value in seen:
            raise InputValidationError(f"duplicate {field} '{value}'")
        row[field] = value
        seen.add(value)


def validate_students(students):
    validate_unique_ids(students, "student_id", "student")
    for row_number, student in enumerate(students, start=2):
        stream = (student.get("allocation_stream") or "").strip()
        if not stream:
            raise InputValidationError(
                f"student row {row_number}: allocation_stream must be non-empty"
            )
        student["allocation_stream"] = stream
        age = (student.get("age") or "").strip()
        try:
            int(age)
        except ValueError as error:
            raise InputValidationError(
                f"student '{student['student_id']}': age must be an integer"
            ) from error
        student["age"] = age


def validate_tutors(tutors):
    validate_unique_ids(tutors, "tutor_id", "tutor")
    for tutor in tutors:
        value = (tutor.get("dbs_checked") or "").strip()
        if value not in {"True", "False"}:
            raise InputValidationError(
                f"tutor '{tutor['tutor_id']}': dbs_checked must be True or False"
            )
        tutor["dbs_checked"] = value
        capacity = (tutor.get("preferred_capacity") or "").strip()
        try:
            if int(capacity) <= 0:
                raise ValueError
        except ValueError as error:
            raise InputValidationError(
                f"tutor '{tutor['tutor_id']}': preferred_capacity must be a positive integer"
            ) from error
        tutor["preferred_capacity"] = capacity


def is_true(value):
    return value == "True"


def tutor_streams(tutor):
    return {
        stream.strip()
        for stream in (tutor.get("eligible_allocation_streams") or "").split("|")
        if stream.strip()
    }


def allocate(students, tutors):
    tutor_data = [
        (tutor, tutor_streams(tutor), is_true(tutor["dbs_checked"]))
        for tutor in sorted(tutors, key=lambda row: row["tutor_id"])
    ]
    students_by_stream = defaultdict(list)
    for student in students:
        students_by_stream[student["allocation_stream"]].append(student)

    group_sizes = defaultdict(int)
    allocations = []
    unallocated = []

    for stream in sorted(students_by_stream):
        stream_students = sorted(
            students_by_stream[stream],
            key=lambda row: (int(row["age"]) >= 18, row["student_id"]),
        )
        eligible = [item for item in tutor_data if stream in item[1]]

        for student in stream_students:
            under_18 = int(student["age"]) < 18
            possible = [item for item in eligible if not under_18 or item[2]]
            if not possible:
                if under_18 and eligible:
                    reason = (
                        "under-18 safeguarding: no DBS-checked tutor eligible for "
                        f"allocation_stream '{stream}'"
                    )
                else:
                    reason = f"no tutor eligible for allocation_stream '{stream}'"
                unallocated.append((student["student_id"], reason))
                continue

            tutor = min(
                possible,
                key=lambda item: (
                    Fraction(
                        group_sizes[(stream, item[0]["tutor_id"])] + 1,
                        int(item[0]["preferred_capacity"]),
                    ),
                    item[0]["tutor_id"],
                ),
            )[0]
            group = (stream, tutor["tutor_id"])
            group_sizes[group] += 1
            allocations.append((student, tutor, group))

    groups_by_stream = defaultdict(list)
    for stream, tutor_id in sorted({item[2] for item in allocations}):
        groups_by_stream[stream].append(tutor_id)
    group_numbers = {
        (stream, tutor_id): f"G{number:02d}"
        for stream in sorted(groups_by_stream)
        for number, tutor_id in enumerate(groups_by_stream[stream], start=1)
    }
    rows = [
        {
            "student_id": student["student_id"],
            "programme": student["programme"],
            "programme_name": student["programme_name"],
            "allocation_stream": student["allocation_stream"],
            "tutor_id": tutor["tutor_id"],
            "tutor_name": tutor["tutor_name"],
            "group_number": group_numbers[group],
        }
        for student, tutor, group in sorted(allocations, key=lambda item: item[0]["student_id"])
    ]
    return rows, unallocated


def write_allocations(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("students_csv")
    parser.add_argument("tutors_csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    try:
        students = read_csv(args.students_csv, STUDENT_REQUIRED_COLUMNS)
        tutors = read_csv(args.tutors_csv, TUTOR_REQUIRED_COLUMNS)
        validate_students(students)
        validate_tutors(tutors)
    except (OSError, csv.Error, InputValidationError) as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 2

    allocations, unallocated = allocate(students, tutors)
    write_allocations(allocations, args.output)

    print(f"students allocated: {len(allocations)}")
    print(f"students unallocated: {len(unallocated)}")
    for student_id, reason in unallocated:
        print(f"UNALLOCATED {student_id}: {reason}", file=sys.stderr)
    return 1 if unallocated else 0


if __name__ == "__main__":
    raise SystemExit(main())
