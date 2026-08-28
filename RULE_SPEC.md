# RULE_SPEC.md

## Personal Tutor Allocation Prototype

### Goal

Automatically allocate students to Personal Tutor groups while:

1. satisfying mandatory constraints;
2. reducing student isolation;
3. encouraging mixed and inclusive groups;
4. distributing transition/support needs reasonably;
5. keeping group sizes balanced;
6. producing transparent diagnostics so staff can review the result.

The tool supports staff decision-making. It does not replace human review.

Where current Faculty guidance conflicts with historical workbook rules or annotations, current Faculty guidance takes precedence. Historical rules remain contextual evidence only.

---

## Staff user guide

For step-by-step annual operating instructions, see the [User Guide](docs/user_guide.pdf).

---

## 1. Input: students

Each student should have:

* `student_id`
* `programme`
* `programme_name`
* `allocation_stream`
* `sex`
* `country`
* `fee_status` (`Home` / `Overseas`)
* `year_of_study`
* `status`
* `age`
* `mature_student` (`True` / `False`)
* `entry_route` (`A-level`, `BTEC`, `Access`, `Foundation`, `IFP`, `Postgraduate`, `Other`)
* `returning_student` (`True` / `False`)
* `support_need` (`none`, `standard`, `complex`)

`programme` and `programme_name` are descriptive fields.

`allocation_stream` is the field used to determine tutor compatibility.

**Programme and allocation stream must not be assumed to have a one-to-one relationship. Multiple programme codes/routes may map to the same `allocation_stream`.**

For the synthetic dataset these fields are known explicitly.

For production, `Student number` is the authoritative `student_id` and duplicate student numbers are input errors. Accepted Applicants supplies programme code/name, sex, country of domicile, Home/Overseas fee status, age at entry, IFP status, disability fields and qualification fields.

Production `allocation_stream` is obtained exclusively from an exact, user-maintained programme-code mapping table. Programme names must never be used to infer a stream, and multiple programme codes may map to the same stream.

An explicit positive `IFP Progressor?` value maps to `entry_route = IFP`. Every other qualification-to-route mapping must be supplied through configuration or a student-specific manual entry; it must not be guessed. If no approved mapping is available, `entry_route` remains blank and produces a warning.

Production `mature_student` is derived from `Age at entry`: `True` when age is 21 or above, otherwise `False`. Production `support_need` may be supplied only by the optional manual student file keyed by `Student number`: `0` maps to `none`, `1` to `standard`, and `2` to `complex`; every other non-blank value is invalid. Disability fields must not populate or affect `support_need`. Unavailable `year_of_study` and returning/repeating markers remain blank unless explicitly supplied through an approved manual field.

---

## 2. Input: tutors

Each tutor should have:

* `tutor_id`
* `tutor_name`
* `eligible_allocation_streams`
* `dbs_checked` (`True` / `False`)
* `experience_level` (`standard` / `experienced`)
* `preferred_capacity`

Production tutor eligibility comes from the annual Tutor List's seven 1/0 allocation-stream columns. The free-text annual-status column does not define eligibility.

Each tutor with at least one eligible stream requires annual configuration containing a stable `tutor_id` and explicit `dbs_checked`. `experience_level` is a manually maintained marker and must not be inferred. Blank `preferred_capacity` defaults to the soft preferred maximum of 8. Optional `admin_role` is configuration-only administrative metadata: it is not emitted in the current tutor schema and does not affect eligibility or allocation in version 1.

The annual Tutor List contains no stable username, email or staff-ID field. Normalized `tutor_name` matching is therefore the fallback join to annual tutor configuration, which must supply the stable `tutor_id`. Duplicate normalized tutor names are input errors.

The production adapter must fail clearly with a non-zero status for missing required workbook fields, unknown programme codes, duplicate student numbers or configuration keys, missing DBS values, malformed 1/0 eligibility markers, or invalid configuration values. Optional unknown fields remain blank and generate warnings rather than inferred defaults.

Tutor eligibility is determined by `allocation_stream`.

A tutor may only receive students whose `allocation_stream` is included in that tutor's `eligible_allocation_streams`.

Programme code and programme name must not be used directly to determine tutor compatibility.

**`eligible_allocation_streams` is the canonical field used by the allocation algorithm. Any separate yes/no stream columns retained to resemble the historical workbook are input-format fields only and must not define separate eligibility logic.**

---

## **3. Allocation unit and Personal Tutor groups**

**Personal Tutor groups are allocation-stream-specific.**

**A tutor group is identified internally by:**

**`(allocation_stream, tutor_id)`**

**A tutor may therefore have separate Personal Tutor groups for different allocation streams.**

**For example, the same tutor could have:**

* **one `cs_year_1` group;**
* **one `computer_science_msc` group.**

**These are treated as separate Personal Tutor groups.**

**`preferred_capacity` applies to a tutor group within an allocation stream, rather than to the tutor's total number of students across all allocation streams.**

**Students from different allocation streams must not be mixed into the same Personal Tutor group in version 1.**

**Group-size balancing and all within-group soft criteria are evaluated within the relevant allocation stream rather than across unrelated streams.**

**The School has confirmed that tutor groups are allocation-stream-specific and are identified by `(allocation_stream, tutor_id)`.**

---

# HARD CONSTRAINTS

Hard constraints may never be deliberately violated.

### H1 — One allocation

Every student whose hard constraints are satisfiable must be assigned to exactly one Personal Tutor group. Students for whom no valid assignment exists must remain unallocated and be explicitly reported under H4.

### H2 — Allocation-stream compatibility

A student may only be assigned to a tutor who is eligible for that student's `allocation_stream`.

Programme code and programme name are descriptive fields and must not determine tutor compatibility directly.

**Different programme codes mapped to the same `allocation_stream` must therefore be treated equivalently for tutor eligibility.**

In production, missing or duplicate programme-code mappings and unknown programme codes are input errors. Programme names must not be used as fallback compatibility logic.

### H3 — Under-18 safeguarding

Every student under 18 must be assigned to a DBS-checked tutor.

This takes priority over every other grouping consideration.

Production `age` is populated from `Age at entry`. A missing or invalid age is an input error because safeguarding eligibility could not otherwise be established.

### H4 — Impossible hard constraints

If the input data make a hard constraint impossible to satisfy, the program must NOT silently produce an invalid allocation.

It must:

* identify the affected student(s);
* explain which hard constraint cannot be satisfied;
* flag the allocation for staff review.

---

# SOFT CONSTRAINTS

Soft constraints should be optimised rather than treated as absolute requirements.

When trade-offs are necessary, priority is:

1. safeguarding;
2. reducing isolation;
3. supporting transition to HE;
4. reasonable overall balance.

**Soft constraints should not be assigned arbitrary policy weights where the guidance does not specify them. The implementation should preserve this priority ordering as clearly as practical.**

---

## S1 — Balanced group sizes

Keep tutor groups as similar in size as reasonably possible **within each allocation stream**.

`preferred_capacity = 8`

The School has confirmed this as a soft preferred maximum, not a hard capacity constraint.

**`preferred_capacity` applies separately to each `(allocation_stream, tutor_id)` group. It does not represent a tutor-wide capacity across all streams.**

---

## S2 — Gender isolation

Where possible, avoid creating a group containing exactly one student of a minority gender surrounded by students of another gender.

Where numbers allow, allocate students so that a gender represented in a group has at least two members.

If pairing cannot be achieved, grouping three students of that gender may be preferable to leaving one isolated.

This is a soft constraint because cohort composition can make perfect balancing impossible.

---

## S3 — International / Home isolation

For operational allocation, `fee_status == Overseas` is the international-student proxy. This is an acknowledged imperfect proxy and must be described as such in diagnostics and staff-facing outputs.

Where possible:

* do not leave exactly one Overseas student in an otherwise Home group;
* avoid putting all Overseas students into one tutor group;
* distribute Overseas students reasonably across tutor groups.

---

## S4 — Country distribution

Where possible, students from the same international country should be distributed across different tutor groups rather than concentrated into one group.

This should not create isolated students in order to achieve country distribution.

Isolation reduction therefore takes priority over country spreading.

---

## S5 — Mature students

For production, a student is marked mature when `Age at entry >= 21`.

Where numbers allow:

* avoid leaving a mature student as the only mature student in a tutor group;
* aim for at least two mature students in a group;
* do not cluster all mature students into a small number of groups.

Students with greater support needs may preferentially be assigned to experienced tutors only where an explicitly supplied, manually maintained `experience_level` marker is available.

---

## S6 — Non-A-level / pathway students

Pathway students include:

* BTEC
* Access to HE
* Foundation Year
* IFP
* other non-A-level routes where specified

Where possible:

* avoid concentrating all pathway students into one tutor group;
* avoid leaving a pathway student completely isolated;
* place pathway students with at least one or two students with similar transition experience while maintaining wider integration.

`Postgraduate` is not treated as a pathway category for this rule.

Production entry routes come only from an explicit IFP flag, an exact configured qualification mapping, or a student-specific manual entry. Unmapped qualifications remain blank and generate a warning.

---

## S7 — Support needs

Where support information is available:

* spread students with additional support needs across tutor groups;
* avoid concentrating a large proportion in one group;
* preferentially match students with complex needs to experienced tutors where feasible.

This rule must only use information that the School has explicitly approved for this purpose.

Do not infer support severity from a `disabled` or disability indicator. In production, support severity comes only from the optional manual 0/1/2 support marker. Absence means unknown and remains blank; it must not default to `none`.

---

# MANUAL / NOT AUTOMATED IN VERSION 1

The following should NOT automatically affect allocation in the prototype.

### M1 — Countries in conflict

Do not create an automated list of countries in conflict.

Any such consideration requires professional judgement and must remain a manual review step.

### M2 — Ethnicity

Do not optimise allocations based on ethnicity in version 1.

The supplied guidance does not currently provide sufficiently clear operational rules for doing so.

### M3 — Returning and repeating students

Returning and repeating students must be flagged for manual review when explicitly identified. They must not trigger automatic reallocation.

### M4 — Missing sensitive information

Do not infer:

* disability;
* health conditions;
* caring responsibilities;
* first-generation status;
* commuter status;
* support severity from a `disabled` or disability indicator;

from other fields.

Only explicitly supplied and approved data may be used.

---

# OUTPUT

The allocation program should create:

## allocations.csv

At minimum:

* `student_id`
* `programme`
* `programme_name`
* `allocation_stream`
* `tutor_id`
* `tutor_name`
* `group_number`

**`group_number` should identify the Personal Tutor group within the relevant allocation stream.**

## diagnostics.csv

For each tutor group:

* allocation stream
* tutor ID/name
* group size
* Home count
* Overseas count
* gender counts
* mature student count
* pathway student count
* support-needs count
* under-18 count
* hard constraint violations
* soft constraint warnings

The program should also print an overall summary such as:

* students allocated
* students unallocated
* hard violations
* soft warnings
* smallest group
* largest group

**Diagnostics should make unavoidable trade-offs visible rather than hiding them.**

---

# SYNTHETIC DATA REQUIREMENTS

Synthetic data must contain fake student and tutor identifiers only.

Do not copy any real student IDs, student names, tutor IDs, tutor names, notes, or other personal data from the historical workbook.

Non-personal structural and categorical information from the historical workbook, such as column structure, programme codes/names, allocation-stream labels, and status/category formats, may be reused where useful so that the synthetic data resembles the real input structure.

Use a fixed random seed:

`seed = 42`

Create a main synthetic cohort of approximately 32 students.

The dataset must deliberately include enough examples to test every major rule:

* several Home students;
* several Overseas students;
* multiple Overseas students from the same country;
* at least two students under 18;
* both DBS and non-DBS tutors;
* a gender imbalance;
* enough minority-gender students that pairing should normally be possible;
* several mature students;
* several pathway students;
* students with standard and complex support needs;
* at least one returning student;
* multiple programmes;
* all relevant allocation streams;
* tutors who are eligible for different allocation streams.

**At least some allocation streams should contain multiple programme codes/routes mapping to the same `allocation_stream`. This ensures that the prototype genuinely tests stream-based rather than programme-code-based tutor matching.**

Under-18 students in the synthetic data should be undergraduate students.

MSc students should be aged 21 or above in the synthetic prototype.

A-level, BTEC, Access, Foundation and IFP entry routes should occur only among undergraduate synthetic students.

MSc synthetic students should use `Postgraduate` as their `entry_route`.

The synthetic cohort should be constructed so that at least one valid allocation satisfying all HARD constraints exists.

Also create a very small EDGE-CASE dataset containing at least one deliberately impossible situation, for example:

* an under-18 student whose `allocation_stream` has no DBS-checked eligible tutor.

The program must detect this rather than silently violating the safeguarding rule.

---

# TESTS

At minimum test:

### Hard constraints

* every allocated student appears exactly once;
* no student is assigned to a tutor who is ineligible for their `allocation_stream`;
* every under-18 student has a DBS-checked tutor;
* impossible hard constraints are explicitly reported;
* **students from different allocation streams are not mixed into the same tutor group.**

### Basic allocation behaviour

* all feasible students are assigned;
* group sizes are reasonably balanced **within allocation streams**;
* **capacity is interpreted per `(allocation_stream, tutor_id)` group rather than as a tutor-wide total;**
* no group exceeds a configured hard capacity if a hard capacity is later enabled.

### Stream-based eligibility

**Tests should explicitly verify that:**

* **two students with different programme codes but the same `allocation_stream` are subject to the same tutor-eligibility rules;**
* **changing a descriptive programme code without changing `allocation_stream` does not change tutor eligibility.**

### Soft-rule diagnostics

Tests should detect:

* lone minority-gender students;
* lone Home/Overseas students;
* mature-student isolation;
* pathway-student isolation;
* excessive concentration of same-country students.

### Reproducibility

Running the allocator twice with the same input and seed should produce the same result.

---

# REMAINING PRODUCTION INTEGRATION QUESTIONS

Before production use, resolve:

1. Who will own, approve and version the annual programme-stream and qualification-route mappings?
2. Who will own and validate the manually maintained tutor `experience_level` and optional student support markers?
3. What approved source, if any, will populate returning/repeating status?
