"""`min_word_count_for_similarity` must reject values that disable the short-result skip.

The field is documented as "shorter content skips near-duplicate detection
entirely", and `is_near_duplicate()` implements that as `len(current) < min_words`.
A bound of 0 or below inverts the guard (`len(...) < 0` is never true), so every
one-word tool result becomes a near-duplicate of itself and repeated legitimate
short results — an empty `ls`, a one-line command output — escalate through
WARNED to BLOCKED. A boolean is worse: Pydantic coerces `true` to `1`, which is
accepted silently. Zero is not a meaningful value here; it changes the documented
semantics rather than relaxing them.
"""

import pytest
from pydantic import ValidationError

from deerflow.agents.middlewares.tool_progress_middleware import is_near_duplicate, word_set
from deerflow.config.tool_progress_config import ToolProgressConfig


@pytest.mark.parametrize("value", [0, -1, -5, True, False])
def test_min_word_count_rejects_values_below_one(value: object) -> None:
    with pytest.raises(ValidationError):
        ToolProgressConfig(min_word_count_for_similarity=value)


def test_min_word_count_keeps_valid_integers() -> None:
    assert ToolProgressConfig().min_word_count_for_similarity == 10
    assert ToolProgressConfig(min_word_count_for_similarity=1).min_word_count_for_similarity == 1
    assert ToolProgressConfig(min_word_count_for_similarity="8").min_word_count_for_similarity == 8


def test_bound_of_one_still_compares_single_word_results() -> None:
    """The lowest accepted bound keeps the guard armed for one-word content."""
    single = word_set("alpha")
    assert is_near_duplicate(single, [single], 0.8, 1) is True
    assert is_near_duplicate(single, [single], 0.8, 2) is False
