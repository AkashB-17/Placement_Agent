"""One test per rule, multiple failures reported together, empty/None rules not enforced."""
from app.schemas import JDRequirements, PolicyRules
from app.services.eligibility import check_eligibility


def _student(**overrides):
    base = {"cgpa": 8.0, "active_backlogs": 0, "branch": "CSE", "batch": "2026", "is_placed": False}
    base.update(overrides)
    return base


def _rules(result):
    return {(r.rule, r.source) for r in result.failed_rules}


# ── CGPA ─────────────────────────────────────────────────────────────────────

def test_cgpa_at_or_above_policy_minimum_passes():
    assert check_eligibility(_student(cgpa=7.0), PolicyRules(min_cgpa=7.0), JDRequirements()).eligible


def test_cgpa_below_policy_minimum_fails():
    result = check_eligibility(_student(cgpa=6.9), PolicyRules(min_cgpa=7.0), JDRequirements())
    assert _rules(result) == {("min_cgpa", "policy")}
    assert result.failed_rules[0].student_value == 6.9
    assert result.failed_rules[0].required_value == 7.0


def test_stricter_jd_override_applies_and_is_attributed_to_jd():
    result = check_eligibility(
        _student(cgpa=7.5), PolicyRules(min_cgpa=7.0), JDRequirements(min_cgpa_override=8.0)
    )
    assert _rules(result) == {("min_cgpa", "jd")}
    assert result.failed_rules[0].required_value == 8.0


def test_looser_jd_override_does_not_relax_policy():
    result = check_eligibility(
        _student(cgpa=6.5), PolicyRules(min_cgpa=7.0), JDRequirements(min_cgpa_override=6.0)
    )
    assert _rules(result) == {("min_cgpa", "policy")}


def test_cgpa_not_stated_not_enforced():
    assert check_eligibility(_student(cgpa=0.0), PolicyRules(), JDRequirements()).eligible


# ── Active backlogs ──────────────────────────────────────────────────────────

def test_backlogs_within_limit_passes():
    assert check_eligibility(_student(active_backlogs=1), PolicyRules(max_active_backlogs=1), JDRequirements()).eligible


def test_backlogs_over_limit_fails():
    result = check_eligibility(_student(active_backlogs=1), PolicyRules(max_active_backlogs=0), JDRequirements())
    assert _rules(result) == {("max_active_backlogs", "policy")}


def test_backlogs_not_stated_not_enforced():
    assert check_eligibility(_student(active_backlogs=9), PolicyRules(), JDRequirements()).eligible


# ── Branch ───────────────────────────────────────────────────────────────────

def test_branch_not_in_policy_fails():
    result = check_eligibility(_student(branch="ME"), PolicyRules(allowed_branches=["CSE", "ECE"]), JDRequirements())
    assert _rules(result) == {("allowed_branches", "policy")}


def test_branch_not_in_jd_fails():
    result = check_eligibility(_student(branch="ECE"), PolicyRules(), JDRequirements(allowed_branches=["CSE"]))
    assert _rules(result) == {("allowed_branches", "jd")}


def test_branch_compared_after_normalization():
    result = check_eligibility(
        _student(branch="computer science and engineering"),
        PolicyRules(allowed_branches=[" cse "]),
        JDRequirements(),
    )
    assert result.eligible


def test_empty_branch_lists_not_enforced():
    assert check_eligibility(_student(branch="ANY"), PolicyRules(), JDRequirements()).eligible


# ── Batch ────────────────────────────────────────────────────────────────────

def test_batch_not_in_policy_fails():
    result = check_eligibility(_student(batch="2025"), PolicyRules(allowed_batches=["2026"]), JDRequirements())
    assert _rules(result) == {("allowed_batches", "policy")}


def test_batch_not_in_jd_fails():
    result = check_eligibility(_student(batch="2025"), PolicyRules(), JDRequirements(allowed_batches=["2026"]))
    assert _rules(result) == {("allowed_batches", "jd")}


def test_batch_compared_after_normalization():
    assert check_eligibility(_student(batch="2022-2026"), PolicyRules(allowed_batches=["2026"]), JDRequirements()).eligible


def test_empty_batch_list_not_enforced():
    assert check_eligibility(_student(batch="1999"), PolicyRules(), JDRequirements()).eligible


# ── Placed students ──────────────────────────────────────────────────────────

def test_placed_student_blocked_when_policy_forbids():
    result = check_eligibility(_student(is_placed=True), PolicyRules(placed_students_can_apply=False), JDRequirements())
    assert _rules(result) == {("placed_students_can_apply", "policy")}


def test_placed_student_allowed_when_policy_allows_or_silent():
    for value in (True, None):
        policy = PolicyRules(placed_students_can_apply=value)
        assert check_eligibility(_student(is_placed=True), policy, JDRequirements()).eligible


def test_unplaced_student_unaffected_by_placed_rule():
    assert check_eligibility(_student(), PolicyRules(placed_students_can_apply=False), JDRequirements()).eligible


# ── Combined ─────────────────────────────────────────────────────────────────

def test_every_failure_is_reported():
    result = check_eligibility(
        _student(cgpa=5.0, active_backlogs=2, branch="ME", batch="2025", is_placed=True),
        PolicyRules(
            min_cgpa=7.0,
            max_active_backlogs=0,
            allowed_branches=["CSE"],
            allowed_batches=["2026"],
            placed_students_can_apply=False,
        ),
        JDRequirements(allowed_branches=["CSE"]),
    )
    assert not result.eligible
    assert _rules(result) == {
        ("min_cgpa", "policy"),
        ("max_active_backlogs", "policy"),
        ("allowed_branches", "policy"),
        ("allowed_branches", "jd"),
        ("allowed_batches", "policy"),
        ("placed_students_can_apply", "policy"),
    }
    assert all(r.description for r in result.failed_rules)


def test_nothing_stated_means_everyone_eligible():
    result = check_eligibility(
        _student(cgpa=0.0, active_backlogs=99, branch="X", batch="0", is_placed=True),
        PolicyRules(),
        JDRequirements(),
    )
    assert result.eligible
    assert result.failed_rules == []
