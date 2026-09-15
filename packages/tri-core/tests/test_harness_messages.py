from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.harness.messages import last_ai_text, text_of


def test_text_of_returns_string_content_unchanged():
    assert text_of(AIMessage(content="plain")) == "plain"


def test_text_of_joins_text_blocks_and_bare_strings_and_skips_other_blocks():
    msg = AIMessage(
        content=[
            {"type": "text", "text": "a"},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            "b",
            {"type": "text", "text": "c"},
        ]
    )
    assert text_of(msg) == "abc"


def test_last_ai_text_is_the_last_message_without_tool_calls():
    call = AIMessage(
        content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    messages = [
        HumanMessage("q"),
        AIMessage(content="first"),
        call,
        ToolMessage("r", tool_call_id="c1"),
        AIMessage(content=[{"type": "text", "text": "final"}]),
    ]
    assert last_ai_text(messages) == "final"


def test_last_ai_text_skips_tool_calling_messages_and_is_empty_when_none_match():
    call = AIMessage(
        content="thinking",
        tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}],
    )
    assert last_ai_text([HumanMessage("q"), call]) == ""
    assert last_ai_text([]) == ""
