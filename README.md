# EDIA Personal Tutor Allocation Tool

This tool combines annual student and tutor information to produce proposed Personal Tutor allocations for the School of Computer Science.

It:

- validates and cleans the annual files;
- enforces tutor eligibility and under-18 safeguarding rules;
- creates capacity-aware baseline groups;
- improves EDIA grouping where possible without breaking mandatory rules or changing baseline group sizes;
- reports warnings, unallocated students, and cases needing manual review; and
- produces a staff-friendly Excel workbook.

The output is a decision-support proposal. It supports, but does not replace, staff review and professional judgement.

For the detailed operational rules, see [RULE_SPEC.md](RULE_SPEC.md).

## Annual workflow

```text
Annual Excel files + annual configuration CSVs
                     ↓
            Validation and cleaning
                     ↓
         Capacity-aware baseline allocation
                     ↓
              EDIA optimisation
                     ↓
                Diagnostics
                     ↓
          PT_Allocation_Output.xlsx
                     ↓
                 Staff review
```

## Annual inputs

Run the tool from the repository's top-level folder. Keep the two Excel files and populated copies of the CSV templates in an approved secure location.

| Input | Required? | Purpose |
|---|---:|---|
| Accepted Applicants workbook | Yes | Student number, programme, age, fee status, and other approved student fields |
| Annual Tutor List workbook | Yes | Tutor availability for each allocation stream |
| `config/programme_stream_mapping.csv` | Yes | Maps each programme code to an allocation stream |
| `config/manual_tutors.csv` | Yes | Supplies annual tutor ID, DBS, experience, and preferred capacity |
| `config/manual_students.csv` | No | Supplies approved support, entry-route, and returning/repeating markers |
| `config/qualification_route_mapping.csv` | No | Maps approved qualification name/level combinations to entry routes |

The CSV column names are strict. Do not rename them or add extra columns.

### 1. Accepted Applicants workbook

The workbook must contain a sheet named `Report` with these headers:

- `Programme code`
- `Programme`
- `Student number`
- `Sex`
- `Student status`
- `Country of domicile`
- `Home / overseas`
- `Age at entry`
- `IFP Progressor?`
- `Qualification name`
- `Qualification level`

Preparation rules:

- `Student number` is the authoritative student identifier and must be present and unique.
- `Programme code` must have an exact entry in `programme_stream_mapping.csv`.
- `Age at entry` must be a whole number. It is also used to derive `mature_student`: age 21 or over is mature.
- A positive `IFP Progressor?` value sets the entry route to `IFP`.
- `Home / overseas`, when populated, must be `Home` or `Overseas`.
- Disability fields may be present in the source workbook, but they are not used to infer support severity.
- The current source does not reliably populate year of study, so this remains blank and is reported as a warning.

### 2. Annual Tutor List workbook

The workbook must contain a sheet named `Tutor List` with `Tutor name` and these seven eligibility columns:

- `CS year 1`
- `Maths and CS year 1`
- `CS with AI year 1`
- `CS with Innov year 1`
- `Computer Science MSc`
- `Cyber Msc`
- `Immersive Technologies MSc`

Each eligibility cell must contain exactly `1` for eligible or `0` for not eligible. Tutor eligibility comes only from this annual matrix and the resulting allocation stream; programme names and codes are not used to select tutors.

A tutor with all zeroes is not included. Every tutor with at least one `1` must have a matching row in `manual_tutors.csv`.

### 3. Programme-to-stream mapping

`config/programme_stream_mapping.csv` has these columns:

```text
programme_code,allocation_stream
```

To add a new programme code without editing Python:

1. add one row containing the exact code used in Accepted Applicants;
2. assign it to the appropriate existing allocation stream; and
3. check that the relevant tutors have `1` in that stream's Tutor List column.

Multiple programme codes, such as BSc and MEng routes, may map to the same stream. Valid streams are:

- `cs_year_1`
- `maths_and_cs_year_1`
- `cs_with_ai_year_1`
- `cs_with_innov_year_1`
- `computer_science_msc`
- `cyber_msc`
- `immersive_technologies_msc`

Programme names are descriptive and are never used to guess a stream. A genuinely new allocation stream, rather than a new code within an existing stream, requires a maintained software change.

### 4. Annual tutor configuration

`config/manual_tutors.csv` has these columns:

```text
tutor_name,tutor_id,dbs_checked,experience_level,preferred_capacity,admin_role
```

Prepare one row for every tutor with at least one `1` in the Tutor List:

- `tutor_name` is used to join the files. Matching ignores case and repeated spaces, but names must still be unique.
- `tutor_id` is the stable staff-maintained identifier used in outputs and must be unique.
- `dbs_checked` must be explicitly `True` or `False`. Never assume DBS status.
- `experience_level` is manually maintained as `standard` or `experienced`. A blank value is allowed but produces a warning and cannot support experienced-tutor matching.
- `preferred_capacity` must be a positive whole number. Blank defaults to `8`.
- `admin_role` is optional reference information. It does not automatically change workload.

The preferred capacity is a soft target, not a hard maximum. Groups can exceed it. Lower the value for a tutor who should receive a proportionally smaller group because of workload or an administrative role.

The Tutor List currently has no stable staff ID, username, or email field. Normalised tutor-name matching is therefore the fallback join; do not invent an identifier in the workbook.

### 5. Optional manual student configuration

`config/manual_students.csv` has these columns:

```text
student_number,support_need,entry_route,returning_student
```

Only add approved information, keyed by the exact student number.

| `support_need` | Internal meaning |
|---:|---|
| `0` | `none` |
| `1` | `standard` |
| `2` | `complex` |

Leave support blank when it is unknown. Do not treat blank as `0`, and never infer severity from a disability code, name, or indicator.

Allowed manual entry routes are `A-level`, `BTEC`, `Access`, `Foundation`, `IFP`, `Postgraduate`, and `Other`. `returning_student` may be blank or explicitly `True`/`False`. Returning and repeating students are shown for manual review only and do not affect optimisation.

### 6. Optional qualification-to-route mapping

`config/qualification_route_mapping.csv` has these columns:

```text
qualification_name,qualification_level,entry_route
```

Each row is an approved mapping for a qualification name and level. Valid mapped routes are `A-level`, `BTEC`, `Access`, `Foundation`, `Postgraduate`, and `Other`. Do not map `IFP` here; it comes from the applicant report or an approved student-specific manual value.

Qualifications are not guessed. An unmapped qualification leaves entry route blank and creates a warning.

## Run the full allocation

Open a terminal or PowerShell in the repository's top-level folder. Put quotation marks around any path containing spaces.

Minimum command:

```text
python src/run_allocation.py AcceptedApplicants.xlsx "Tutor List 26-27.xlsx" --programme-map config/programme_stream_mapping.csv --tutor-config config/manual_tutors.csv --output-dir data/annual_output
```

Command including both optional student configuration files:

```text
python src/run_allocation.py AcceptedApplicants.xlsx "Tutor List 26-27.xlsx" --programme-map config/programme_stream_mapping.csv --tutor-config config/manual_tutors.csv --student-config config/manual_students.csv --qualification-map config/qualification_route_mapping.csv --output-dir data/annual_output
```

Replace the example filenames and output directory with the paths for the current year.

| Argument | Meaning |
|---|---|
| First workbook path | Accepted Applicants workbook |
| Second workbook path | Annual Tutor List workbook |
| `--programme-map` | Programme-code to allocation-stream CSV |
| `--tutor-config` | Required annual tutor configuration CSV |
| `--student-config` | Optional approved student-specific fields CSV |
| `--qualification-map` | Optional qualification-to-entry-route CSV |
| `--output-dir` | Folder in which every output file will be written |

Use a clearly named output folder for each run and archive an earlier run before reusing the same folder.

## Output files

The main staff report is:

```text
PT_Allocation_Output.xlsx
```

It contains six sheets:

| Sheet | What staff will find |
|---|---|
| `Run Summary` | Students supplied, allocated and unallocated; tutor groups; smallest/largest group; total soft warnings; manual-review groups |
| `Proposed Allocations` | One row per allocated student with programme, allocation stream, tutor, and group number |
| `Group Summary` | One row per allocation-stream/tutor group with size, preferred capacity, composition counts, and warning count |
| `Manual Review` | Identified returning/repeating students and adapter warnings relevant to staff |
| `EDIA Diagnostics` | The complete diagnostic table, including individual warning fields and stream-level information |
| `Unallocated` | Students who could not be allocated without breaking a hard rule, with the reason |

The workbook is still produced when the run completes with unallocated students. It is not produced for an invalid-input exit.

These supporting files are also written, mainly for transparency and debugging:

- `students.csv` and `tutors.csv`: cleaned internal inputs;
- `baseline_allocations.csv`: capacity-aware allocation before EDIA swaps;
- `final_allocations.csv`: allocation shown in the workbook;
- `diagnostics.csv`: full diagnostic data;
- `warnings.txt`: missing optional fields and other adapter warnings;
- `unallocated.csv`: hard-impossible students and reasons; and
- `run_summary.txt`: the summary figures shown in Excel.

## Exit codes

| Code | Meaning | What to do |
|---:|---|---|
| `0` | Successful run; every hard-feasible student was allocated | Review the workbook before publication |
| `1` | Run completed, but one or more students could not be safely allocated | Open `Unallocated` immediately; the workbook and CSVs are available |
| `2` | An input, configuration, workbook, validation, or processing error prevented a valid run | Correct the reported `INPUT ERROR`; do not use partial or earlier output as the new result |

Warnings are printed in the terminal and saved in `warnings.txt`. A warning is not necessarily a failed run, but it must be reviewed.

## Rules implemented

Personal Tutor groups are allocation-stream-specific and are identified by `(allocation_stream, tutor_id)`. A tutor can therefore have a separate group in more than one stream.

### Hard rules

Hard rules are never deliberately relaxed:

1. Every student who has a valid hard-feasible assignment is allocated exactly once.
2. The tutor must be eligible for the student's `allocation_stream`.
3. Every student under 18 must have an eligible DBS-checked tutor.

If these rules cannot be satisfied, the student is left unallocated with an explanation.

### Soft rules

The baseline balances workload in proportion to each tutor group's `preferred_capacity`. The optimiser then uses deterministic swaps within an allocation stream. It preserves the baseline group sizes and will not make any tracked EDIA metric worse than baseline.

Where the cohort and valid tutor choices allow, it tries to reduce:

- a sex category represented by exactly one student in an otherwise mixed group;
- exactly one Overseas student in a group containing Home students;
- concentration of all Overseas students in one group within a multi-group stream;
- repeated Overseas countries within the same group;
- a single mature student in a group;
- a single pathway student in a group, where pathway means BTEC, Access, Foundation, IFP, or Other; and
- complex support students assigned to a standard tutor when an experienced tutor is eligible for that stream.

`Overseas` fee status is the operational international-student proxy. It is useful for this workflow but imperfect. `Postgraduate` is not treated as a pathway route.

Approved support data is included in group counts. Current optimisation specifically checks complex-support/experienced-tutor matching; it does not claim to optimise every possible support distribution.

Returning/repeating markers never influence automatic allocation. They appear only in manual review.

## What staff must review

Before publishing or transferring any allocation:

1. Review every row in `Unallocated`. Never bypass a DBS or stream-eligibility rule to make the sheet complete.
2. Review every row in `Manual Review`, including returning/repeating students and missing-data warnings.
3. Read `warnings.txt`, especially unknown entry routes, support fields, tutor experience, or unmatched configuration rows.
4. Review `EDIA Diagnostics` and `Group Summary` for remaining isolation, support, country, and workload warnings.
5. Apply professional judgement to circumstances the tool does not model.
6. Check any staff-made changes again for allocation-stream eligibility and under-18 DBS safeguarding before publication.

The tool does not provide an editing UI and does not automatically revalidate manual changes made directly in Excel.

## New academic year checklist

- [ ] Obtain the new Accepted Applicants export and confirm the `Report` sheet and required headers.
- [ ] Obtain the new Tutor List and confirm all seven stream columns use only `0` or `1`.
- [ ] Add every current programme code to `programme_stream_mapping.csv` and remove or archive obsolete annual mappings as appropriate.
- [ ] Confirm each available tutor has one unique row in `manual_tutors.csv`.
- [ ] Reconfirm every tutor's DBS status; do not carry it forward without approval.
- [ ] Reconfirm manually maintained experience markers.
- [ ] Set preferred capacities, lowering them where staff workload requires a smaller proportional group.
- [ ] Prepare approved optional support, entry-route, and returning/repeating information.
- [ ] Prepare approved qualification mappings or accept and review blank-route warnings.
- [ ] Choose a new secure output directory and run the command.
- [ ] Check the exit code, workbook, warnings, unallocated students, diagnostics, and manual-review cases.
- [ ] Record who reviewed and approved the final allocation before publication.

## Troubleshooting

| Message or problem | Meaning and action |
|---|---|
| `unknown programme code` | The exact Accepted Applicants code is missing from `programme_stream_mapping.csv`. Add it with an approved existing stream; do not infer from the programme name. |
| `dbs_checked must be explicitly True or False` | Enter the tutor's confirmed annual DBS value in `manual_tutors.csv` using exactly `True` or `False`. |
| `available tutor is missing annual config and DBS` | A Tutor List row has at least one `1` but no matching `manual_tutors.csv` row. Add the tutor using the same name and complete the required fields. |
| `duplicate Student number` | The Accepted Applicants report contains the same student number more than once. Correct the source/export before running again. |
| `no applicant records found` | Check that the correct Accepted Applicants export was selected and that the `Report` sheet contains populated rows below the required headers. |
| `invalid entry_route` | Use only the exact allowed values. `IFP` must not be placed in the qualification mapping file. |
| Entry route is unknown and left blank | No approved manual or qualification mapping exists. Add an approved mapping if available; otherwise review the warning and leave it unknown. |
| `under-18 safeguarding: no DBS-checked tutor eligible` | No tutor satisfies both the student's stream and DBS requirement. The student remains unallocated. Verify the factual Tutor List and DBS data, then escalate for staff action; never change DBS merely to force an allocation. |

Other common errors include duplicate IDs or configuration keys, extra or renamed CSV columns, invalid tutor eligibility markers, non-integer ages, and missing workbook headers. Correct the source or configuration and rerun; do not edit Python.

## Testing and evidence

- The clean handover repository passes **56 production-relevant tests, 0 failed**, including the 601-student end-to-end smoke test.
- The final fictional end-to-end smoke test supplied **601 students, 21 tutors, and 7 allocation streams**.
- It allocated **600 students** and correctly reported **1 deliberately impossible under-18 student** rather than making an unsafe allocation.
- The first pipeline run completed in approximately **5 seconds** in the test environment. This is evidence from one fictional test run, not a performance guarantee for every computer or cohort.
- Repeated runs with identical inputs produced deterministic, identical output files.

The smoke test uses fictional data only.

## Known limitations

- The scalable optimiser uses deterministic local swaps. It improves the tracked grouping measures but does not guarantee the mathematical global optimum.
- `Overseas` fee status is the operational but imperfect international-student proxy.
- Tutor experience is not supplied automatically and must be maintained by staff.
- Support severity is accepted only from manual, approved data and is never inferred from disability information.
- The tutor workbook has no stable staff identifier, so normalised tutor-name matching is the current fallback join to the manually maintained tutor ID.
- Returning/repeating students require an approved manual source and remain staff-review cases.
- Programme-stream and qualification-route mappings require named annual owners and approval/version control.
- The first populated live Accepted Applicants export must be validated against the adapter before operational use.
- Group size 8 is a soft preferred target, not a hard cap.

## Data protection and privacy

- Do not commit real student data, live input workbooks, populated annual configuration, or allocation outputs to GitHub.
- Store and transfer live files only in School-approved secure locations.
- Use only fields approved for this allocation purpose.
- Do not infer sensitive attributes or support severity from other data.
- Limit access to staff who need it and follow the University's retention and data-handling requirements.
- Human review and approval remain required before any allocation is published or used operationally.
