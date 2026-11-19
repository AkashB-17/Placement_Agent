import pytest

from app.services.normalize import expand_branches, normalize_batch, normalize_branch, normalize_branches, normalize_list


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CSE", "CSE"),
        ("cse", "CSE"),
        (" Computer Science and Engineering ", "CSE"),
        ("Computer Science & Engineering", "CSE"),
        ("B.Tech CSE", "CSE"),
        ("Electronics & Communication Engineering", "ECE"),
        ("Electrical and Electronics Engineering", "EEE"),
        ("Mechanical Engineering", "ME"),
        ("Civil", "CE"),
        ("Information Technology", "IT"),
        ("AI&ML", "AI-ML"),
        ("CSE (AI-ML)", "AI-ML"),
        ("Data Science", "DS"),
        ("Electronics & Comm.", "ECE"),
        ("Electronics and Communications", "ECE"),
        ("E&C", "ECE"),
        ("Computer Science & Engg.", "CSE"),
        ("Biotechnology", "BIOTECHNOLOGY"),
        ("", ""),
    ],
)
def test_normalize_branch(raw: str, expected: str) -> None:
    assert normalize_branch(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2027", "2027"),
        (" 2027 ", "2027"),
        ("2023-2027", "2027"),
        ("2023 - 27", "2027"),
        ("2023/27", "2027"),
        ("Class of 2026", "2026"),
        ("final year", "final year"),
    ],
)
def test_normalize_batch(raw: str, expected: str) -> None:
    assert normalize_batch(raw) == expected


def test_normalize_list_dedupes_and_drops_empty() -> None:
    raw = ["CSE", "Computer Science", "", "ECE"]
    assert normalize_list(raw, normalize_branch) == ["CSE", "ECE"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CSE/IT", ["CSE", "IT"]),
        ("B.Tech CSE/IT/ECE", ["CSE", "IT", "ECE"]),
        ("CSE, IT", ["CSE", "IT"]),
        ("CSE or IT", ["CSE", "IT"]),
        ("AI/ML", ["AI-ML"]),  # a known name is never split
        ("CSE/Biotech", ["CSE/BIOTECH"]),  # an unknown part: keep whole rather than guess
        ("Computer Science & Engineering", ["CSE"]),
        ("", []),
    ],
)
def test_expand_branches(raw: str, expected: list[str]) -> None:
    assert expand_branches(raw) == expected


def test_normalize_branches_flattens_and_dedupes() -> None:
    assert normalize_branches(["CSE/IT", "IT", "ECE"]) == ["CSE", "IT", "ECE"]


@pytest.mark.parametrize(
    "raw",
    ["all branches", "All Branches", "B.Tech all streams", "any branch", "All branches are eligible to apply",
     "open to all disciplines", "ALL"],
)
def test_all_branches_means_no_rule(raw: str) -> None:
    assert normalize_branches([raw]) == []
    assert normalize_branches(["CSE", raw]) == []  # "all" anywhere lifts the restriction


def test_circuit_branches_shorthand() -> None:
    assert normalize_branches(["Any circuit branch"]) == ["CSE", "IT", "AI-ML", "DS", "ECE", "EEE", "EE"]


def test_a_real_branch_is_not_mistaken_for_all() -> None:
    assert normalize_branches(["Allied Sciences"]) == ["ALLIED SCIENCES"]
