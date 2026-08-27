import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import diagnostics
except ImportError:
    import diagnostics


OUTPUT_FIELDS = [
    "student_id",
    "programme",
    "programme_name",
    "allocation_stream",
    "tutor_id",
    "tutor_name",
    "group_number",
]
TRACKED_METRICS = (
    "gender_isolation_warning",
    "overseas_isolation_warning",
    "mature_isolation_warning",
    "pathway_isolation_warning",
    "complex_support_tutor_warning",
    "overseas_stream_concentration_warning",
    "same_country_overseas_repeat_penalty",
)


def is_true(value):
    return str(value).strip().lower() == "true"


def tutor_streams(tutor):
    return {
        stream.strip()
        for stream in tutor["eligible_allocation_streams"].split("|")
        if stream.strip()
    }


def warning_is_true(value):
    return value is True or str(value).strip().lower() == "true"


def tracked_metric_values(students, tutors, allocations):
    rows = diagnostics.build_diagnostics(students, tutors, allocations)
    group_warnings = [
        sum(warning_is_true(row[warning]) for row in rows)
        for warning in TRACKED_METRICS[:5]
    ]
    concentration = 0
    country_repeats = 0
    seen_streams = set()
    for row in rows:
        stream = row["allocation_stream"]
        if stream in seen_streams:
            continue
        seen_streams.add(stream)
        concentration += warning_is_true(row["overseas_stream_concentration_warning"])
        distribution = json.loads(row["overseas_country_group_distribution"])
        country_repeats += sum(
            max(int(count) - 1, 0)
            for group_counts in distribution.values()
            for count in group_counts.values()
        )
    return (*group_warnings, concentration, country_repeats)


def objective_from_metrics(metrics):
    return (
        metrics[0] + metrics[1],
        metrics[2] + metrics[3],
        metrics[4],
        metrics[5],
        metrics[6],
    )


def allocation_objective(students, tutors, allocations):
    return objective_from_metrics(tracked_metric_values(students, tutors, allocations))


def baseline_groups(baseline_allocations):
    sizes = Counter(
        (row["allocation_stream"], row["tutor_id"]) for row in baseline_allocations
    )
    metadata = {}
    for row in baseline_allocations:
        metadata[(row["allocation_stream"], row["tutor_id"])] = {
            "tutor_id": row["tutor_id"],
            "tutor_name": row["tutor_name"],
            "group_number": row["group_number"],
        }
    groups = defaultdict(list)
    for (stream, tutor_id), size in sorted(sizes.items()):
        groups[stream].append({**metadata[(stream, tutor_id)], "size": size})
    return groups


def feasible_assignments(stream_students, groups, tutors_by_id):
    students = sorted(
        stream_students,
        key=lambda student: (int(student["age"]) >= 18, student["student_id"]),
    )
    groups = sorted(groups, key=lambda group: group["tutor_id"])
    remaining = {group["tutor_id"]: group["size"] for group in groups}
    assignment = {}

    def search(index):
        if index == len(students):
            if all(capacity == 0 for capacity in remaining.values()):
                yield dict(assignment)
            return
        student = students[index]
        stream = student["allocation_stream"]
        under_18 = int(student["age"]) < 18
        for group in groups:
            tutor_id = group["tutor_id"]
            tutor = tutors_by_id[tutor_id]
            if remaining[tutor_id] == 0:
                continue
            if stream not in tutor_streams(tutor):
                continue
            if under_18 and not is_true(tutor["dbs_checked"]):
                continue
            assignment[student["student_id"]] = tutor_id
            remaining[tutor_id] -= 1
            yield from search(index + 1)
            remaining[tutor_id] += 1
            del assignment[student["student_id"]]

    yield from search(0)


def allocation_rows(stream_students, groups, assignment):
    groups_by_tutor = {group["tutor_id"]: group for group in groups}
    return [
        {
            "student_id": student["student_id"],
            "programme": student["programme"],
            "programme_name": student["programme_name"],
            "allocation_stream": student["allocation_stream"],
            "tutor_id": assignment[student["student_id"]],
            "tutor_name": groups_by_tutor[assignment[student["student_id"]]]["tutor_name"],
            "group_number": groups_by_tutor[assignment[student["student_id"]]]["group_number"],
        }
        for student in sorted(stream_students, key=lambda row: row["student_id"])
    ]


def assignment_tie_break(rows):
    return tuple(
        (row["student_id"], row["tutor_id"])
        for row in sorted(rows, key=lambda row: row["student_id"])
    )


def build_candidate_sets(students, tutors, baseline_allocations):
    tutors_by_id = {tutor["tutor_id"]: tutor for tutor in tutors}
    groups_by_stream = baseline_groups(baseline_allocations)
    students_by_stream = defaultdict(list)
    for student in students:
        students_by_stream[student["allocation_stream"]].append(student)

    candidate_sets = {}
    for stream in sorted(students_by_stream):
        stream_students = students_by_stream[stream]
        groups = groups_by_stream[stream]
        candidates_by_metrics = {}
        for assignment in feasible_assignments(stream_students, groups, tutors_by_id):
            rows = allocation_rows(stream_students, groups, assignment)
            metrics = tracked_metric_values(stream_students, tutors, rows)
            tie_break = assignment_tie_break(rows)
            current = candidates_by_metrics.get(metrics)
            if current is None or tie_break < current["tie_break"]:
                candidates_by_metrics[metrics] = {
                    "metrics": metrics,
                    "rows": rows,
                    "tie_break": tie_break,
                }
        if not candidates_by_metrics:
            raise ValueError(f"no hard-feasible assignment for allocation_stream '{stream}'")
        candidate_sets[stream] = sorted(
            candidates_by_metrics.values(),
            key=lambda candidate: (candidate["metrics"], candidate["tie_break"]),
        )
    return candidate_sets


def combine_candidate_sets(candidate_sets, limits):
    zero = (0,) * len(TRACKED_METRICS)
    states = {zero: []}
    for stream in sorted(candidate_sets):
        next_states = {}
        for totals, rows in states.items():
            for candidate in candidate_sets[stream]:
                combined_metrics = tuple(
                    total + value for total, value in zip(totals, candidate["metrics"])
                )
                if any(
                    limit is not None and value > limit
                    for value, limit in zip(combined_metrics, limits)
                ):
                    continue
                combined_rows = rows + candidate["rows"]
                current = next_states.get(combined_metrics)
                if current is None or assignment_tie_break(combined_rows) < assignment_tie_break(
                    current
                ):
                    next_states[combined_metrics] = combined_rows
        states = next_states
    return states


def select_refined(candidate_sets, baseline_metrics):
    states = combine_candidate_sets(candidate_sets, baseline_metrics)
    if not states:
        raise ValueError("no assignment satisfies baseline non-regression limits")
    _, rows = min(
        states.items(),
        key=lambda item: (objective_from_metrics(item[0]), assignment_tie_break(item[1])),
    )
    return sorted(rows, key=lambda row: row["student_id"])


def lower_bounds(candidate_sets, baseline_metrics):
    bounds = {}
    for index, metric in enumerate(TRACKED_METRICS):
        limits = list(baseline_metrics)
        limits[index] = None
        states = combine_candidate_sets(candidate_sets, limits)
        if not states:
            raise ValueError(f"no assignment satisfies non-regression limits for '{metric}'")
        bounds[metric] = min(values[index] for values in states)
    return bounds


def optimize_with_bounds(students, tutors, baseline_allocations):
    baseline_metrics = tracked_metric_values(students, tutors, baseline_allocations)
    candidate_sets = build_candidate_sets(students, tutors, baseline_allocations)
    return (
        select_refined(candidate_sets, baseline_metrics),
        lower_bounds(candidate_sets, baseline_metrics),
    )


def optimize(students, tutors, baseline_allocations):
    baseline_metrics = tracked_metric_values(students, tutors, baseline_allocations)
    candidate_sets = build_candidate_sets(students, tutors, baseline_allocations)
    return select_refined(candidate_sets, baseline_metrics)


def optimize_unconstrained(students, tutors, baseline_allocations):
    candidate_sets = build_candidate_sets(students, tutors, baseline_allocations)
    rows = []
    for stream in sorted(candidate_sets):
        candidate = min(
            candidate_sets[stream],
            key=lambda item: (
                objective_from_metrics(item["metrics"]),
                item["tie_break"],
            ),
        )
        rows.extend(candidate["rows"])
    return sorted(rows, key=lambda row: row["student_id"])


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
    parser.add_argument("baseline_allocations_csv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    students = diagnostics.read_csv(args.students_csv)
    tutors = diagnostics.read_csv(args.tutors_csv)
    baseline = diagnostics.read_csv(args.baseline_allocations_csv)
    write_allocations(optimize(students, tutors, baseline), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
