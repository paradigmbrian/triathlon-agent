from typing import Any

import pytest

from tri_core.config import Settings
from tri_core.llm import (
    DEFAULTS,
    STRUCTURED_ROLES,
    Role,
    fallbacks_of,
    make_model,
    resolve,
)
from tri_core.testing import ScriptedChatModel


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, anthropic_api_key="k", **kw)


# resolve


def test_every_role_launches_on_opus_5_at_default_effort():
    assert set(DEFAULTS) == set(Role)
    for role in Role:
        spec = resolve(settings(), role)
        assert spec.model == "claude-opus-5" and spec.effort is None
        assert spec.fallbacks == ("claude-opus-4-8", "claude-sonnet-5")
    assert resolve(settings(), Role.LAB_EXTRACT).max_tokens == 32000
    assert resolve(settings(), Role.LAB_REPORT).max_tokens == 32000
    assert resolve(settings(), Role.COACH).max_tokens == 16000


def test_role_override_beats_tri_model_which_beats_the_default():
    s = settings(tri_model="claude-sonnet-5", tri_model_analyst="claude-haiku-4-5")
    assert resolve(s, Role.ANALYST).model == "claude-haiku-4-5"
    assert resolve(s, Role.COACH).model == "claude-sonnet-5"


def test_effort_override_applies_and_a_model_override_does_not_reset_it():
    s = settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium")
    assert resolve(s, Role.ANALYST).effort == "medium"
    assert resolve(settings(tri_effort_coach="high"), Role.COACH).effort == "high"


def test_default_chain_is_the_first_two_other_models():
    assert resolve(settings(tri_model="claude-opus-4-8"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-sonnet-5",
    )
    assert resolve(settings(tri_model="claude-sonnet-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )
    assert resolve(settings(tri_model="claude-haiku-4-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )


def test_tri_model_fallbacks_is_parsed_and_drops_the_primary():
    s = settings(tri_model_fallbacks=" claude-sonnet-5 , claude-opus-5,claude-sonnet-5 ")
    assert resolve(s, Role.COACH).fallbacks == ("claude-sonnet-5",)
    assert resolve(settings(tri_model_fallbacks=""), Role.COACH).fallbacks == ()


def test_an_effort_the_model_does_not_list_raises_naming_the_env_var():
    s = settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low")
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST=low is not supported by claude-haiku"):
        resolve(s, Role.ANALYST)
    assert resolve(settings(tri_model_analyst="claude-haiku-4-5"), Role.ANALYST).effort is None


def test_structured_roles_refuse_an_effort():
    assert {
        Role.PLANNING_DESIGN,
        Role.NUTRITION_FUEL,
        Role.LAB_EXTRACT,
        Role.JUDGE,
    } == STRUCTURED_ROLES
    with pytest.raises(ValueError, match="TRI_EFFORT_JUDGE=low is not allowed"):
        resolve(settings(tri_effort_judge="low"), Role.JUDGE)
    with pytest.raises(ValueError, match="TRI_EFFORT_NUTRITION_FUEL=medium is not allowed"):
        resolve(settings(tri_effort_nutrition_fuel="medium"), Role.NUTRITION_FUEL)


# make_model


def test_make_model_builds_the_role_spec_with_its_metadata():
    m = make_model(
        settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium"), Role.ANALYST
    )
    assert m.model == "claude-sonnet-5" and m.max_tokens == 16000 and m.effort == "medium"
    assert m.anthropic_api_key.get_secret_value() == "k"
    meta = m.metadata or {}
    assert meta["tri_role"] == "analyst"
    assert meta["tri_fallbacks"] == ["claude-opus-5", "claude-opus-4-8"]
    lab = make_model(settings(), Role.LAB_EXTRACT)
    assert lab.max_tokens == 32000 and lab.effort is None


def test_make_model_raises_before_any_call_for_a_bad_override():
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST"):
        make_model(
            settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low"), Role.ANALYST
        )


# fallbacks_of


def test_fallbacks_of_is_empty_for_models_make_model_did_not_build():
    from langchain_anthropic import ChatAnthropic

    assert fallbacks_of(ScriptedChatModel(script=[])) == []
    assert fallbacks_of(ChatAnthropic(model="claude-opus-5")) == []
    assert fallbacks_of(make_model(settings(tri_model_fallbacks=""), Role.COACH)) == []


def test_fallbacks_of_builds_each_model_with_its_own_profile_and_effort():
    primary = make_model(settings(), Role.COACH)
    fbs = fallbacks_of(primary)
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert [f.effort for f in fbs] == ["high", "high"]  # primary at default: run fallbacks at high
    assert all(f.max_tokens == 16000 for f in fbs)
    assert all(f.anthropic_api_key.get_secret_value() == "k" for f in fbs)
    assert all((f.metadata or {})["tri_fallback_from"] == "claude-opus-5" for f in fbs)
    assert all((f.metadata or {})["tri_role"] == "coach" for f in fbs)


def test_fallbacks_keep_the_primary_effort_when_listed_and_drop_it_for_haiku():
    s = settings(
        tri_effort_analyst="medium", tri_model_fallbacks="claude-sonnet-5,claude-haiku-4-5"
    )
    fbs = fallbacks_of(make_model(s, Role.ANALYST))
    assert [(f.model, f.effort) for f in fbs] == [
        ("claude-sonnet-5", "medium"),
        ("claude-haiku-4-5", None),
    ]


def test_structured_roles_fall_back_without_effort():
    fbs = fallbacks_of(make_model(settings(), Role.NUTRITION_FUEL))
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert all(f.effort is None for f in fbs)
