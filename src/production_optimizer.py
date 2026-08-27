import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import allocator, diagnostics, optimizer
except ImportError:
    import allocator
    import diagnostics
    import optimizer


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "output" / "production_allocations.csv"
)


class ProductionOptimizationError(ValueError):
    pass


def _indexed(rows, field, label):
    result = {}
    for row in rows:
        key = row[field]
        if not key or key in result:
            raise ProductionOptimizationError(
                f"{label} {field} values must be unique and non-empty"
            )
        result[key] = row
    return result


def _can_assign(student, tutor):
    return (
        student["allocation_stream"] in optimizer.tutor_streams(tutor)
        and (int(student["age"]) >= 18 or optimizer.is_true(tutor["dbs_checked"]))
    )


def validate_baseline(students, tutors, baseline_allocations):
    students_by_id = _indexed(students, "student_id", "student")
    tutors_by_id = _indexed(tutors, "tutor_id", "tutor")
    counts = Counter()
    group_metadata = {}

    for row in baseline_allocations:
        student_id = row["student_id"]
        tutor_id = row["tutor_id"]
        if student_id not in students_by_id:
            raise ProductionOptimizationError(f"baseline contains unknown student '{student_id}'")
        if tutor_id not in tutors_by_id:
            raise ProductionOptimizationError(f"baseline contains unknown tutor '{tutor_id}'")
        student = students_by_id[student_id]
        tutor = tutors_by_id[tutor_id]
        if row["allocation_stream"] != student["allocation_stream"]:
            raise ProductionOptimizationError(
                f"baseline allocation_stream does not match student '{student_id}'"
            )
        if not _can_assign(student, tutor):
            raise ProductionOptimizationError(
                f"baseline violates a hard constraint for student '{student_id}'"
            )
        counts[student_id] += 1
        key = (row["allocation_stream"], tutor_id)
        metadata = (row["tutor_name"], row["group_number"])
        if key in group_metadata and group_metadata[key] != metadata:
            raise ProductionOptimizationError(
                f"inconsistent baseline group metadata for {key}"
            )
        group_metadata[key] = metadata

    feasible = {
        student_id
        for student_id, student in students_by_id.items()
        if any(_can_assign(student, tutor) for tutor in tutors)
    }
    allocated = set(counts)
    if feasible != allocated or any(count != 1 for count in counts.values()):
        raise ProductionOptimizationError(
            "baseline must allocate every hard-feasible student exactly once"
        )


class _StreamState:
    def __init__(self, stream, students_by_id, tutors, rows):
        self.stream = stream
        self.students = students_by_id
        self.tutors = {tutor["tutor_id"]: tutor for tutor in tutors}
        self.assignment = {row["student_id"]: row["tutor_id"] for row in rows}
        self.metadata = {
            row["tutor_id"]: {
                "tutor_name": row["tutor_name"],
                "group_number": row["group_number"],
            }
            for row in rows
        }
        self.groups = {tutor_id: self._empty_group() for tutor_id in self.metadata}
        self.experienced_available = any(
            tutor["experience_level"].strip().lower() == "experienced"
            and stream in optimizer.tutor_streams(tutor)
            for tutor in tutors
        )
        for student_id, tutor_id in self.assignment.items():
            self._update_group(tutor_id, self.students[student_id], 1)

    @staticmethod
    def _empty_group():
        return {
            "size": 0,
            "sex": Counter(),
            "home": 0,
            "overseas": 0,
            "mature": 0,
            "pathway": 0,
            "complex": 0,
            "countries": Counter(),
            "country_repeats": 0,
        }

    def _update_group(self, tutor_id, student, change):
        group = self.groups[tutor_id]
        group["size"] += change
        sex = student["sex"].strip()
        if sex:
            group["sex"][sex] += change
            if group["sex"][sex] == 0:
                del group["sex"][sex]
        group["home"] += change * (student["fee_status"] == "Home")
        group["overseas"] += change * (student["fee_status"] == "Overseas")
        group["mature"] += change * diagnostics.is_true(student["mature_student"])
        group["pathway"] += change * (student["entry_route"] in diagnostics.PATHWAY_ROUTES)
        group["complex"] += change * (student["support_need"] == "complex")
        if student["fee_status"] == "Overseas":
            country = student["country"]
            before = group["countries"][country]
            if change == 1:
                group["country_repeats"] += before >= 1
            else:
                group["country_repeats"] -= before >= 2
            group["countries"][country] += change
            if group["countries"][country] == 0:
                del group["countries"][country]

    def _transfer(self, student_id, source, destination):
        student = self.students[student_id]
        self._update_group(source, student, -1)
        self._update_group(destination, student, 1)
        self.assignment[student_id] = destination

    def _group_metrics(self, tutor_id):
        group = self.groups[tutor_id]
        tutor = self.tutors[tutor_id]
        return (
            int(
                group["size"] > 1
                and len(group["sex"]) > 1
                and any(count == 1 for count in group["sex"].values())
            ),
            int(group["overseas"] == 1 and group["home"] >= 1),
            int(group["mature"] == 1),
            int(group["pathway"] == 1),
            int(
                group["complex"] >= 1
                and tutor["experience_level"].strip().lower() == "standard"
                and self.experienced_available
            ),
        )

    def metrics(self):
        group_metrics = [self._group_metrics(tutor_id) for tutor_id in self.groups]
        warnings = tuple(sum(values) for values in zip(*group_metrics))
        total_overseas = sum(group["overseas"] for group in self.groups.values())
        overseas_groups = sum(group["overseas"] > 0 for group in self.groups.values())
        concentration = int(
            len(self.groups) > 1 and total_overseas > 0 and overseas_groups == 1
        )
        repeats = sum(group["country_repeats"] for group in self.groups.values())
        return (*warnings, concentration, repeats)

    def _destination_is_valid(self, student_id, tutor_id):
        return _can_assign(self.students[student_id], self.tutors[tutor_id])

    def candidates(self):
        student_ids = sorted(self.assignment)
        for index, first in enumerate(student_ids):
            first_tutor = self.assignment[first]
            for second in student_ids[index + 1 :]:
                second_tutor = self.assignment[second]
                if first_tutor == second_tutor:
                    continue
                if not self._destination_is_valid(first, second_tutor):
                    continue
                if not self._destination_is_valid(second, first_tutor):
                    continue
                self._transfer(first, first_tutor, second_tutor)
                self._transfer(second, second_tutor, first_tutor)
                metrics = self.metrics()
                self._transfer(second, first_tutor, second_tutor)
                self._transfer(first, second_tutor, first_tutor)
                yield ("swap", first, second), metrics

    def apply(self, operation):
        _, first, second = operation
        first_tutor = self.assignment[first]
        second_tutor = self.assignment[second]
        self._transfer(first, first_tutor, second_tutor)
        self._transfer(second, second_tutor, first_tutor)

    def rows(self):
        rows = []
        for student_id in sorted(self.assignment):
            student = self.students[student_id]
            tutor_id = self.assignment[student_id]
            metadata = self.metadata[tutor_id]
            rows.append(
                {
                    "student_id": student_id,
                    "programme": student["programme"],
                    "programme_name": student["programme_name"],
                    "allocation_stream": self.stream,
                    "tutor_id": tutor_id,
                    "tutor_name": metadata["tutor_name"],
                    "group_number": metadata["group_number"],
                }
            )
        return rows


def _sum_metrics(values):
    values = list(values)
    if not values:
        return (0,) * len(optimizer.TRACKED_METRICS)
    return tuple(sum(metric) for metric in zip(*values))


def optimize(students, tutors, baseline_allocations):
    validate_baseline(students, tutors, baseline_allocations)
    students_by_id = {student["student_id"]: student for student in students}
    rows_by_stream = defaultdict(list)
    for row in baseline_allocations:
        rows_by_stream[row["allocation_stream"]].append(row)
    states = {
        stream: _StreamState(stream, students_by_id, tutors, rows)
        for stream, rows in sorted(rows_by_stream.items())
    }

    baseline_metrics = optimizer.tracked_metric_values(
        students, tutors, baseline_allocations
    )
    stream_metrics = {stream: state.metrics() for stream, state in states.items()}
    current_metrics = _sum_metrics(stream_metrics.values())
    if current_metrics != baseline_metrics:
        raise ProductionOptimizationError("local metric state does not match diagnostics")

    while optimizer.objective_from_metrics(current_metrics) != (0, 0, 0, 0, 0):
        current_objective = optimizer.objective_from_metrics(current_metrics)
        best = None
        for stream, state in states.items():
            before = stream_metrics[stream]
            for operation, after in state.candidates():
                candidate_metrics = tuple(
                    total - old + new
                    for total, old, new in zip(current_metrics, before, after)
                )
                if any(
                    candidate > baseline
                    for candidate, baseline in zip(candidate_metrics, baseline_metrics)
                ):
                    continue
                candidate_objective = optimizer.objective_from_metrics(candidate_metrics)
                if candidate_objective >= current_objective:
                    continue
                key = (candidate_objective, stream, operation)
                if best is None or key < best[0]:
                    best = (key, stream, operation, after, candidate_metrics)
        if best is None:
            break
        _, stream, operation, after, current_metrics = best
        states[stream].apply(operation)
        stream_metrics[stream] = after

    rows = [row for stream in sorted(states) for row in states[stream].rows()]
    rows.sort(key=lambda row: row["student_id"])
    actual_metrics = optimizer.tracked_metric_values(students, tutors, rows)
    baseline_sizes = Counter(
        (row["allocation_stream"], row["tutor_id"])
        for row in baseline_allocations
    )
    optimized_sizes = Counter(
        (row["allocation_stream"], row["tutor_id"]) for row in rows
    )
    if optimized_sizes != baseline_sizes:
        raise ProductionOptimizationError("optimized group sizes differ from baseline")
    if actual_metrics != current_metrics:
        raise ProductionOptimizationError("optimized metrics do not match diagnostics")
    if any(after > before for before, after in zip(baseline_metrics, actual_metrics)):
        raise ProductionOptimizationError("optimized metrics regress from baseline")
    return rows


def allocate_and_optimize(students, tutors):
    baseline, unallocated = allocator.allocate(students, tutors)
    return optimize(students, tutors, baseline), unallocated


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("students_csv")
    parser.add_argument("tutors_csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    try:
        students = allocator.read_csv(
            args.students_csv, allocator.STUDENT_REQUIRED_COLUMNS
        )
        tutors = allocator.read_csv(args.tutors_csv, allocator.TUTOR_REQUIRED_COLUMNS)
        allocator.validate_students(students)
        allocator.validate_tutors(tutors)
        rows, unallocated = allocate_and_optimize(students, tutors)
    except (
        OSError,
        csv.Error,
        allocator.InputValidationError,
        ProductionOptimizationError,
    ) as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 2

    allocator.write_allocations(rows, args.output)
    print(f"students allocated: {len(rows)}")
    print(f"students unallocated: {len(unallocated)}")
    for student_id, reason in unallocated:
        print(f"UNALLOCATED {student_id}: {reason}", file=sys.stderr)
    return 1 if unallocated else 0


if __name__ == "__main__":
    raise SystemExit(main())
