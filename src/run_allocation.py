import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile

try:
    from . import (
        allocator,
        diagnostics,
        excel_report,
        production_adapter,
        production_optimizer,
    )
except ImportError:
    import allocator
    import diagnostics
    import excel_report
    import production_adapter
    import production_optimizer


UNALLOCATED_FIELDS = ["student_id", "reason"]


def _write_unallocated(path, unallocated):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNALLOCATED_FIELDS)
        writer.writeheader()
        writer.writerows(
            {"student_id": student_id, "reason": reason}
            for student_id, reason in unallocated
        )


def _write_text(path, lines):
    text = "".join(f"{line}\n" for line in lines)
    path.write_text(text, encoding="utf-8")


def _summary(students, final_allocations, diagnostic_rows, unallocated):
    sizes = [int(row["group_size"]) for row in diagnostic_rows]
    return [
        f"students supplied: {len(students)}",
        f"students allocated: {len(final_allocations)}",
        f"students unallocated: {len(unallocated)}",
        f"tutor groups: {len(diagnostic_rows)}",
        f"smallest group: {min(sizes) if sizes else 0}",
        f"largest group: {max(sizes) if sizes else 0}",
        f"total soft warnings: {sum(int(row['soft_warning_count']) for row in diagnostic_rows)}",
        "returning/manual-review groups: "
        f"{sum(diagnostics.is_true(row['returning_manual_review']) for row in diagnostic_rows)}",
    ]


def run_pipeline(
    applicants_workbook,
    tutors_workbook,
    programme_map,
    tutor_config,
    output_dir,
    student_config=None,
    qualification_map=None,
):
    students, tutors, warnings = production_adapter.adapt_production(
        applicants_workbook,
        tutors_workbook,
        programme_map,
        tutor_config,
        student_config,
        qualification_map,
    )
    if not students:
        raise production_adapter.ProductionInputError(
            "no applicant records found; check the Accepted Applicants report"
        )
    allocator.validate_students(students)
    allocator.validate_tutors(tutors)
    baseline, unallocated = allocator.allocate(students, tutors)
    final_allocations = production_optimizer.optimize(students, tutors, baseline)
    production_optimizer.validate_baseline(students, tutors, final_allocations)
    diagnostic_rows = diagnostics.build_diagnostics(
        students, tutors, final_allocations
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    production_adapter.write_outputs(students, tutors, output_dir)
    allocator.write_allocations(
        baseline, output_dir / "baseline_allocations.csv"
    )
    allocator.write_allocations(
        final_allocations, output_dir / "final_allocations.csv"
    )
    diagnostics.write_diagnostics(
        diagnostic_rows, output_dir / "diagnostics.csv"
    )
    _write_text(output_dir / "warnings.txt", warnings)
    _write_unallocated(output_dir / "unallocated.csv", unallocated)
    summary_lines = _summary(
        students, final_allocations, diagnostic_rows, unallocated
    )
    _write_text(
        output_dir / "run_summary.txt",
        summary_lines,
    )
    excel_report.write_report(
        output_dir / "PT_Allocation_Output.xlsx",
        summary_lines,
        students,
        final_allocations,
        diagnostic_rows,
        warnings,
        unallocated,
        diagnostics.DIAGNOSTIC_FIELDS,
    )
    return warnings, unallocated


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("applicants_workbook", type=Path)
    parser.add_argument("tutors_workbook", type=Path)
    parser.add_argument("--programme-map", type=Path, required=True)
    parser.add_argument("--tutor-config", type=Path, required=True)
    parser.add_argument("--student-config", type=Path)
    parser.add_argument("--qualification-map", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        warnings, unallocated = run_pipeline(
            args.applicants_workbook,
            args.tutors_workbook,
            args.programme_map,
            args.tutor_config,
            args.output_dir,
            args.student_config,
            args.qualification_map,
        )
    except (
        OSError,
        csv.Error,
        BadZipFile,
        ET.ParseError,
        production_adapter.ProductionInputError,
        allocator.InputValidationError,
        production_optimizer.ProductionOptimizationError,
    ) as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for student_id, reason in unallocated:
        print(f"UNALLOCATED {student_id}: {reason}", file=sys.stderr)
    return 1 if unallocated else 0


if __name__ == "__main__":
    raise SystemExit(main())
