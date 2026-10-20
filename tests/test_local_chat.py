import json

import httpx

from fussballdb.assistant import chat as chat_module


class FakeToolbox:
    def call(self, name, args):
        assert name == "predict_match"
        return json.dumps({"p_home": 0.18, "p_draw": 0.21, "p_away": 0.61})


def test_local_chat_runs_tool_loop(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "text-embedding-x"}, {"id": "qwen-test"}]})
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            msg = {"role": "assistant", "content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "predict_match", "arguments": json.dumps({"home": "Freiburg", "away": "Bayern"})}}]}
        else:
            msg = {"role": "assistant", "content": "<think>rechne</think>Bayern gewinnt mit 61 %."}
        return httpx.Response(200, json={"choices": [{"message": msg}]})

    monkeypatch.setattr(chat_module, "Toolbox", FakeToolbox)
    real_client = httpx.Client
    monkeypatch.setattr(chat_module.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    session = chat_module.LocalChat(base_url="http://local/v1", model="")
    assert session.model == "qwen-test"
    answer = session.ask("Freiburg gegen Bayern?")
    assert answer == "Bayern gewinnt mit 61 %."
    assert requests[0]["tools"][0]["type"] == "function"
    tool_msg = requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1" and "0.61" in tool_msg["content"]
