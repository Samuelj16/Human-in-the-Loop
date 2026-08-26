"""Cost estimation is shown to users before they approve spend, so it is tested."""
from app.pricing import CACHE_READ_MULTIPLIER, cost_usd, estimate_task_cost, is_priced

OPUS = "claude-opus-5"


def test_cost_matches_list_price():
    # Opus 5: $5/Mtok in, $25/Mtok out.
    assert cost_usd(OPUS, input_tokens=1_000_000) == 5.0
    assert cost_usd(OPUS, output_tokens=1_000_000) == 25.0


def test_cached_input_is_billed_at_a_discount():
    fresh = cost_usd(OPUS, input_tokens=100_000)
    cached = cost_usd(OPUS, cache_read_tokens=100_000)
    assert cached == round(fresh * CACHE_READ_MULTIPLIER, 6)
    assert cached < fresh


def test_unknown_model_is_flagged_rather_than_silently_guessed():
    assert is_priced(OPUS)
    assert not is_priced("some-model-we-have-no-price-for")
    estimate = estimate_task_cost(
        ["a"], model="some-model-we-have-no-price-for", max_searches=8, max_iterations=12
    )
    assert estimate.priced is False


def test_estimate_brackets_the_expected_value():
    estimate = estimate_task_cost(
        ["one", "two", "three"], model=OPUS, max_searches=8, max_iterations=12
    )
    assert estimate.low_usd <= estimate.expected_usd <= estimate.high_usd
    assert estimate.expected_usd > 0


def test_a_longer_plan_costs_more():
    short = estimate_task_cost(["a"], model=OPUS, max_searches=8, max_iterations=12)
    long = estimate_task_cost(
        ["a", "b", "c", "d", "e"], model=OPUS, max_searches=8, max_iterations=12
    )
    assert long.expected_usd > short.expected_usd
    assert long.expected_searches > short.expected_searches


def test_estimate_respects_the_hard_caps():
    """A ten-step plan cannot be estimated above what the caps permit."""
    estimate = estimate_task_cost(
        ["step"] * 10, model=OPUS, max_searches=3, max_iterations=4
    )
    assert estimate.expected_searches <= 3
    assert estimate.expected_turns <= 4


def test_prompt_caching_lowers_the_estimate():
    kwargs = dict(model=OPUS, max_searches=8, max_iterations=12)
    cached = estimate_task_cost(["a", "b", "c"], cached=True, **kwargs)
    uncached = estimate_task_cost(["a", "b", "c"], cached=False, **kwargs)
    assert cached.expected_usd < uncached.expected_usd
