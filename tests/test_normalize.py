import pytest

from app.services.normalize import normalize_batch, normalize_branch, normalize_list


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
