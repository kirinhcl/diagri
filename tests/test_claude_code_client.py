"""The development client that runs model turns on the local Claude Code CLI (scripts/)."""

import asyncio
import importlib.util
import json
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "claude_code_client.py"
TOOLS = [
    {
        "name": "validate_run_sheet",
        "description": "Validate a run sheet.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {"run_sheet": {"type": "object"}}},
    }
]


@pytest.fixture(scope="module")
def cc():
    spec = importlib.util.spec_from_file_location("claude_code_client", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_prompt_lists_the_tools_then_every_turn_in_order(cc):
    messages = [
        {"role": "user", "content": "Your task record"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "t1", "name": "validate_run_sheet", "input": {"a": 1}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "bad", "is_error": True}
            ],
        },
    ]

    prompt = cc.render_prompt(messages, TOOLS)

    assert prompt.index("<tools>") < prompt.index("Your task record") < prompt.index("checking")
    assert '"input_schema"' in prompt and '"strict"' not in prompt
    assert '<tool_use id="t1" name="validate_run_sheet">{"a": 1}</tool_use>' in prompt
    assert '<tool_result id="t1" error="true">\nbad\n</tool_result>' in prompt


def test_an_answer_with_calls_is_a_tool_use_turn_and_one_without_is_the_end(cc):
    usage = {"input_tokens": 2, "cache_read_input_tokens": 100, "output_tokens": 7}
    answer = {"text": "validating", "tool_calls": [{"name": "validate_run_sheet", "input": {}}]}

    reply = cc.to_reply(answer, usage)
    final = cc.to_reply({"text": "done", "tool_calls": []}, {})

    assert reply.stop_reason == "tool_use" and reply.input_tokens == 102
    (call,) = reply.tool_calls
    assert reply.content[1] == {"type": "tool_use", "id": call.id, "name": call.name, "input": {}}
    assert final.stop_reason == "end_turn" and final.tool_calls == ()


def test_a_failed_cli_run_is_an_error(cc):
    with pytest.raises(RuntimeError, match="error_max_turns"):
        cc.parse_answer({"is_error": True, "subtype": "error_max_turns", "result": ""})
    assert cc.parse_answer({"result": '{"text": "x", "tool_calls": []}'})["text"] == "x"


def test_the_cli_runs_without_its_own_tools_and_without_a_redirected_endpoint(
    cc, tmp_path, monkeypatch
):
    """A fake ``claude`` records its arguments, input and environment and answers once."""
    record = tmp_path / "record.json"
    fake = tmp_path / "claude"
    answer = {"structured_output": {"text": "", "tool_calls": [{"name": "x", "input": {}}]}}
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), "
        f"'base_url': os.environ.get('ANTHROPIC_BASE_URL')}}, open({str(record)!r}, 'w'))\n"
        f"print({json.dumps(json.dumps(answer))})\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:11435")
    client = cc.ClaudeCodeClient(executable=str(fake))

    reply = asyncio.run(
        client.create(
            model="claude-sonnet-5-5",
            system="You plan.",
            messages=[{"role": "user", "content": "task"}],
            tools=TOOLS,
            max_tokens=100,
            effort="medium",
        )
    )

    seen = json.loads(record.read_text())
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--system-prompt") + 1].startswith("You plan.")
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"] == [
        "validate_run_sheet"
    ]
    assert "task" in seen["stdin"] and seen["base_url"] is None
    assert reply.stop_reason == "tool_use" and reply.tool_calls[0].name == "x"
