import csv
import random
from pathlib import Path


SEED = 42
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic"

PROGRAMMES = {
    "4COSC006UU": "Computer Science (BSc)",
    "4COSC019UU": "Mathematics and Computer Science (BSc)",
    "4COSC018UU": "Mathematics and Computer Science (MEng)",
    "4COMS002UU": "Computer Science with Artificial Intelligence (BSc)",
    "4COMS001UU": "Computer Science with Artificial Intelligence (MEng)",
    "4COSC005T": "Computer Science (MSc)",
    "4COSC012DT": "Cyber Security (Infrastructures Security) (MSc)",
    "4COSC024DT": "Immersive Technologies (MSc)",
}

PROGRAMME_STREAMS = {
    "4COSC006UU": "cs_year_1",
    "4COSC019UU": "maths_and_cs_year_1",
    "4COSC018UU": "maths_and_cs_year_1",
    "4COMS002UU": "cs_with_ai_year_1",
    "4COMS001UU": "cs_with_ai_year_1",
    "4COSC005T": "computer_science_msc",
    "4COSC012DT": "cyber_msc",
    "4COSC024DT": "immersive_technologies_msc",
}

ALLOCATION_STREAMS = (
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
    *ALLOCATION_STREAMS,
    "dbs_checked",
    "experience_level",
    "preferred_capacity",
]


def shuffled(rng, values):
    values = list(values)
    rng.shuffle(values)
    return values


def make_feasible_students(rng):
    programmes = shuffled(
        rng,
        ["4COSC006UU"] * 8
        + ["4COSC019UU"] * 4
        + ["4COSC018UU"] * 4
        + ["4COMS002UU"] * 4
        + ["4COMS001UU"] * 4
        + ["4COSC005T"] * 3
        + ["4COSC012DT"] * 3
        + ["4COSC024DT"] * 2,
    )
    sexes = shuffled(rng, ["M"] * 22 + ["F"] * 10)
    domiciles = shuffled(
        rng,
        [("England", "Home")] * 15
        + [("Wales", "Home")] * 3
        + [("Scotland", "Home")] * 2
        + [("Northern Ireland", "Home")] * 2
        + [("China", "Overseas")] * 4
        + [("India", "Overseas")] * 3
        + [("Nigeria", "Overseas")] * 2
        + [("Malaysia", "Overseas")],
    )
    ug_ages = shuffled(
        rng,
        [(17, False)] * 2
        + [(18, False)] * 6
        + [(19, False)] * 6
        + [(20, False)] * 6
        + [(age, True) for age in (21, 24, 31, 46)],
    )
    ug_entry_routes = shuffled(
        rng,
        ["A-level"] * 12
        + ["BTEC"] * 4
        + ["Access"] * 3
        + ["Foundation"] * 3
        + ["IFP"] * 2,
    )
    pgt_ages = shuffled(
        rng,
        [(age, True) for age in (21, 22, 23, 24, 26, 29, 34, 41)],
    )
    registrations = shuffled(
        rng,
        [("Registered online", False)] * 17
        + [("Registered student", False)] * 8
        + [("Provisionally Registered", False)] * 4
        + [("Provisional Returner", True)] * 3,
    )
    support_needs = shuffled(
        rng,
        ["none"] * 19 + ["standard"] * 9 + ["complex"] * 4,
    )
    ug_profiles = iter(zip(ug_ages, ug_entry_routes))
    pgt_profiles = iter(zip(pgt_ages, ["Postgraduate"] * 8))

    students = []
    for index, values in enumerate(
        zip(
            programmes,
            sexes,
            domiciles,
            registrations,
            support_needs,
        ),
        start=1,
    ):
        programme, sex, domicile, registration, support_need = values
        allocation_stream = PROGRAMME_STREAMS[programme]
        if allocation_stream.endswith("_msc"):
            age, entry_route = next(pgt_profiles)
        else:
            age, entry_route = next(ug_profiles)
        country, fee_status = domicile
        years_old, mature_student = age
        status, returning_student = registration
        students.append(
            {
                "student_id": f"SYN-STU-{index:03d}",
                "programme": programme,
                "programme_name": PROGRAMMES[programme],
                "allocation_stream": allocation_stream,
                "sex": sex,
                "country": country,
                "fee_status": fee_status,
                "year_of_study": "1",
                "status": status,
                "age": years_old,
                "mature_student": mature_student,
                "entry_route": entry_route,
                "returning_student": returning_student,
                "support_need": support_need,
            }
        )
    return students


def make_tutor(tutor_id, eligible_allocation_streams, dbs_checked, experience_level):
    eligible = set(eligible_allocation_streams)
    tutor = {
        "tutor_id": tutor_id,
        "tutor_name": f"Synthetic Tutor {tutor_id[-2:]}",
        "eligible_allocation_streams": "|".join(
            stream for stream in ALLOCATION_STREAMS if stream in eligible
        ),
        "dbs_checked": dbs_checked,
        "experience_level": experience_level,
        "preferred_capacity": 8,
    }
    for stream in ALLOCATION_STREAMS:
        tutor[stream] = "yes" if stream in eligible else "no"
    return tutor


def make_feasible_tutors():
    return [
        make_tutor(
            "SYN-TUT-01",
            ["cs_year_1", "maths_and_cs_year_1"],
            True,
            "experienced",
        ),
        make_tutor(
            "SYN-TUT-02",
            ["cs_year_1", "computer_science_msc"],
            False,
            "standard",
        ),
        make_tutor(
            "SYN-TUT-03",
            [
                "maths_and_cs_year_1",
                "computer_science_msc",
                "immersive_technologies_msc",
            ],
            True,
            "experienced",
        ),
        make_tutor(
            "SYN-TUT-04",
            ["maths_and_cs_year_1", "cs_with_ai_year_1"],
            False,
            "standard",
        ),
        make_tutor(
            "SYN-TUT-05",
            ["cs_with_ai_year_1", "cyber_msc"],
            True,
            "experienced",
        ),
        make_tutor(
            "SYN-TUT-06",
            ["cyber_msc", "immersive_technologies_msc"],
            False,
            "standard",
        ),
    ]


def make_impossible_students():
    return [
        {
            "student_id": "IMP-STU-001",
            "programme": "4COMS002UU",
            "programme_name": PROGRAMMES["4COMS002UU"],
            "allocation_stream": "cs_with_ai_year_1",
            "sex": "F",
            "country": "China",
            "fee_status": "Overseas",
            "year_of_study": "1",
            "status": "Provisionally Registered",
            "age": 17,
            "mature_student": False,
            "entry_route": "IFP",
            "returning_student": False,
            "support_need": "complex",
        }
    ]


def make_impossible_tutors():
    return [
        make_tutor("IMP-TUT-01", ["cs_with_ai_year_1"], False, "standard"),
        make_tutor("IMP-TUT-02", ["cs_year_1"], True, "experienced"),
    ]


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    rng = random.Random(SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_DIR / "feasible_students.csv", STUDENT_FIELDS, make_feasible_students(rng))
    write_csv(OUTPUT_DIR / "feasible_tutors.csv", TUTOR_FIELDS, make_feasible_tutors())
    write_csv(OUTPUT_DIR / "impossible_students.csv", STUDENT_FIELDS, make_impossible_students())
    write_csv(OUTPUT_DIR / "impossible_tutors.csv", TUTOR_FIELDS, make_impossible_tutors())


if __name__ == "__main__":
    main()
