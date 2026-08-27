import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


PATHWAY_ROUTES = {"BTEC", "Access", "Foundation", "IFP", "Other"}
DIAGNOSTIC_FIELDS = [
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
    "gender_isolation_warning",
    "overseas_isolation_warning",
    "mature_isolation_warning",
    "pathway_isolation_warning",
    "complex_support_tutor_warning",
    "returning_manual_review",
    "soft_warning_count",
    "stream_group_size_min",
    "stream_group_size_max",
    "stream_group_size_range",
    "stream_group_sizes",
    "overseas_country_group_distribution",
    "overseas_stream_concentration_warning",
]


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_true(value):
    return str(value).strip().lower() == "true"


def tutor_streams(tutor):
    return {
        stream.strip()
        for stream in tutor["eligible_allocation_streams"].split("|")
        if stream.strip()
    }


def compact_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def build_diagnostics(students, tutors, allocations):
    students_by_id = {student["student_id"]: student for student in students}
    tutors_by_id = {tutor["tutor_id"]: tutor for tutor in tutors}
    groups = defaultdict(list)
    for allocation in allocations:
        group = (allocation["allocation_stream"], allocation["tutor_id"])
        groups[group].append((allocation, students_by_id[allocation["student_id"]]))

    experienced_streams = {
        stream
        for tutor in tutors
        if tutor["experience_level"].strip().lower() == "experienced"
        for stream in tutor_streams(tutor)
    }
    details = {}

    for (stream, tutor_id), members in sorted(groups.items()):
        tutor = tutors_by_id[tutor_id]
        group_number = members[0][0]["group_number"]
        group_students = [student for _, student in members]
        sex_counts = Counter(
            student["sex"].strip() for student in group_students if student["sex"].strip()
        )
        home_count = sum(student["fee_status"] == "Home" for student in group_students)
        overseas_count = sum(student["fee_status"] == "Overseas" for student in group_students)
        mature_count = sum(is_true(student["mature_student"]) for student in group_students)
        pathway_count = sum(student["entry_route"] in PATHWAY_ROUTES for student in group_students)
        standard_count = sum(student["support_need"] == "standard" for student in group_students)
        complex_count = sum(student["support_need"] == "complex" for student in group_students)
        under_18_count = sum(int(student["age"]) < 18 for student in group_students)
        returning_count = sum(is_true(student["returning_student"]) for student in group_students)

        warnings = {
            "gender_isolation_warning": (
                len(group_students) > 1
                and len(sex_counts) > 1
                and any(count == 1 for count in sex_counts.values())
            ),
            "overseas_isolation_warning": overseas_count == 1 and home_count >= 1,
            "mature_isolation_warning": mature_count == 1,
            "pathway_isolation_warning": pathway_count == 1,
            "complex_support_tutor_warning": (
                complex_count >= 1
                and tutor["experience_level"].strip().lower() == "standard"
                and stream in experienced_streams
            ),
        }
        row = {
            "allocation_stream": stream,
            "tutor_id": tutor_id,
            "tutor_name": tutor["tutor_name"],
            "group_number": group_number,
            "group_size": len(group_students),
            "preferred_capacity": tutor["preferred_capacity"],
            "Home_count": home_count,
            "Overseas_count": overseas_count,
            "sex_counts": compact_json(dict(sex_counts)),
            "mature_count": mature_count,
            "pathway_count": pathway_count,
            "support_standard_count": standard_count,
            "support_complex_count": complex_count,
            "under_18_count": under_18_count,
            "returning_count": returning_count,
            **warnings,
            "returning_manual_review": returning_count > 0,
            "soft_warning_count": sum(warnings.values()),
        }
        overseas_countries = Counter(
            student["country"]
            for student in group_students
            if student["fee_status"] == "Overseas"
        )
        details[(stream, tutor_id)] = (row, overseas_countries)

    details_by_stream = defaultdict(list)
    for (stream, tutor_id), detail in details.items():
        details_by_stream[stream].append((tutor_id, *detail))

    for stream, stream_details in details_by_stream.items():
        stream_details.sort()
        sizes = {tutor_id: row["group_size"] for tutor_id, row, _ in stream_details}
        country_distribution = defaultdict(dict)
        for tutor_id, _, countries in stream_details:
            for country, count in countries.items():
                country_distribution[country][tutor_id] = count
        total_overseas = sum(row["Overseas_count"] for _, row, _ in stream_details)
        overseas_groups = sum(row["Overseas_count"] > 0 for _, row, _ in stream_details)
        concentrated = len(stream_details) > 1 and total_overseas > 0 and overseas_groups == 1
        minimum = min(sizes.values())
        maximum = max(sizes.values())
        for _, row, _ in stream_details:
            row.update(
                {
                    "stream_group_size_min": minimum,
                    "stream_group_size_max": maximum,
                    "stream_group_size_range": maximum - minimum,
                    "stream_group_sizes": compact_json(sizes),
                    "overseas_country_group_distribution": compact_json(country_distribution),
                    "overseas_stream_concentration_warning": concentrated,
                }
            )

    return [detail[0] for _, detail in sorted(details.items())]


def write_diagnostics(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DIAGNOSTIC_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("students_csv")
    parser.add_argument("tutors_csv")
    parser.add_argument("allocations_csv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = build_diagnostics(
        read_csv(args.students_csv),
        read_csv(args.tutors_csv),
        read_csv(args.allocations_csv),
    )
    write_diagnostics(rows, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
