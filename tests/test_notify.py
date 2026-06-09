"""Tests for notify: Telegram message splitting and chunked send (#11)."""

import json
from unittest.mock import patch

from watchy.notify import (
    TelegramNotifier,
    _WORKING_LIMIT,
    _split_message,
)


class _FakeResp:
    def __init__(self, payload=b'{"ok": true}'):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class TestPostPayload:
    """The real _post must include chat_id — sendMessage 400s without it."""

    def test_post_includes_chat_id(self):
        notifier = TelegramNotifier(bot_token="tok", chat_id="999")
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = json.loads(req.data)
            return _FakeResp()

        with patch("urllib.request.urlopen", fake_urlopen):
            ok = notifier._post("sendMessage", {"text": "hi", "parse_mode": "HTML"})

        assert ok is True
        assert captured["data"]["chat_id"] == "999"
        assert captured["data"]["text"] == "hi"
        assert captured["data"]["parse_mode"] == "HTML"
        assert "bottok/sendMessage" in captured["url"]


class TestSplitMessage:
    def test_short_message_single_chunk(self):
        chunks = _split_message("hello world")
        assert chunks == ["hello world"]

    def test_long_message_splits(self):
        # 200 lines of ~50 chars = ~10k chars → multiple chunks
        text = "\n".join(f"<b>line {i}:</b> some content here" for i in range(200))
        chunks = _split_message(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= _WORKING_LIMIT

    def test_no_chunk_splits_an_html_tag(self):
        # each line has a balanced <b>…</b>; chunks must never cut mid-tag
        text = "\n".join(f"<b>tag {i}</b> body text padding padding" for i in range(300))
        chunks = _split_message(text)
        for chunk in chunks:
            # every opening tag has a matching close within the same chunk
            assert chunk.count("<b>") == chunk.count("</b>")

    def test_oversized_single_line_hard_split(self):
        # one plain line longer than the limit (advisor detail paragraph)
        long_line = " ".join(["word"] * 2000)  # ~10k chars, no newlines
        chunks = _split_message(long_line)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= _WORKING_LIMIT

    def test_single_word_longer_than_limit(self):
        word = "x" * (_WORKING_LIMIT * 2 + 5)
        chunks = _split_message(word)
        assert len(chunks) >= 3
        for chunk in chunks:
            assert len(chunk) <= _WORKING_LIMIT
        assert "".join(chunks) == word

    def test_reassembly_preserves_content(self):
        text = "\n".join(f"line {i}" for i in range(500))
        chunks = _split_message(text)
        assert "\n".join(chunks) == text


class TestSendChunking:
    def _notifier(self):
        return TelegramNotifier(bot_token="tok", chat_id="123")

    def test_send_posts_each_chunk(self):
        notifier = self._notifier()
        text = "\n".join(f"<b>line {i}:</b> padding content" for i in range(400))
        expected = len(_split_message(text))
        assert expected >= 2

        with patch.object(notifier, "_post", return_value=True) as mock_post:
            ok = notifier.send(text)
        assert ok is True
        assert mock_post.call_count == expected
        for call in mock_post.call_args_list:
            assert len(call.args[1]["text"]) <= _WORKING_LIMIT

    def test_send_short_single_post(self):
        notifier = self._notifier()
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            ok = notifier.send("short message")
        assert ok is True
        assert mock_post.call_count == 1

    def test_send_returns_false_if_any_chunk_fails(self):
        notifier = self._notifier()
        text = "\n".join(f"line {i}" for i in range(2000))
        with patch.object(notifier, "_post", side_effect=[True, False, True]):
            ok = notifier.send(text)
        assert ok is False


class TestPipelineResultContent:
    """#3: richer pipeline_result — verdict headline + longer summary, chunk-safe."""

    def _notifier(self):
        return TelegramNotifier(bot_token="tok", chat_id="123")

    def _sent_text(self, mock_post):
        # concatenate every chunk's text payload
        return "\n".join(call.args[1]["text"] for call in mock_post.call_args_list)

    def test_verdict_line_and_count_present(self):
        notifier = self._notifier()
        result = {
            "verdict": "BUY",
            "analyst_count": 4,
            "recommendations": ["[Market] strong"],
            "risk_assessment": "moderate",
            "summary": "short summary",
        }
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result("AAPL", "golden_cross", result)
        text = self._sent_text(mock_post)
        assert "Verdict:" in text
        assert "BUY" in text
        assert "4 analysts" in text

    def test_no_verdict_line_when_absent(self):
        notifier = self._notifier()
        result = {"summary": "x", "recommendations": []}
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result("AAPL", "golden_cross", result)
        assert "Verdict:" not in self._sent_text(mock_post)

    def test_trader_plan_and_risk_rendered_in_full(self):
        notifier = self._notifier()
        plan = "P" * 800
        risk = "R" * 800
        result = {"trader_plan": plan, "risk_assessment": risk, "recommendations": []}
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result("AAPL", "golden_cross", result)
        text = self._sent_text(mock_post)
        # Both digested blocks present in full — no 300/400/500-char truncation.
        assert plan in text
        assert risk in text
        assert "Trader Plan" in text
        assert "Risk / Final Call" in text

    def test_raw_analyst_reports_not_in_message(self):
        notifier = self._notifier()
        result = {
            "verdict": "BUY",
            "analyst_count": 2,
            "recommendations": ["[Market] raw analyst dump that should not appear"],
            "trader_plan": "Action: Buy.",
            "risk_assessment": "Rating: Overweight.",
        }
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result("AAPL", "golden_cross", result)
        text = self._sent_text(mock_post)
        assert "raw analyst dump" not in text
        assert "Recommendation:" not in text

    def test_falls_back_to_summary_when_no_plan_or_risk(self):
        notifier = self._notifier()
        result = {"verdict": "HOLD", "analyst_count": 1, "summary": "S" * 350,
                  "recommendations": []}
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result("AAPL", "golden_cross", result)
        text = self._sent_text(mock_post)
        assert "S" * 350 in text  # full summary, untruncated

    def test_advice_sent_as_separate_message(self):
        notifier = self._notifier()
        result = {"verdict": "BUY", "analyst_count": 4, "summary": "s",
                  "recommendations": []}
        advice = {"decision": "HOLD", "urgency": "LOW",
                  "detail": "Hold the position; trim only above $400."}
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            notifier.pipeline_result(
                "GOOG", "scheduled_daily", result,
                position_text="Current position in GOOG:\n  Shares: 1",
                advice=advice,
            )
        texts = [call.args[1]["text"] for call in mock_post.call_args_list]
        # The analysis message and the position/advice message are distinct posts.
        analysis_msgs = [t for t in texts if "Verdict:" in t]
        advice_msgs = [t for t in texts if "Position Advice" in t]
        assert analysis_msgs and advice_msgs
        # No single message mixes the analyst verdict with the advisor block.
        assert not any("Verdict:" in t and "Position Advice" in t for t in texts)
        # The advice detail and the position context ride with the advice message.
        assert any("trim only above $400" in t for t in advice_msgs)
        assert any("Current position in GOOG" in t for t in advice_msgs)

    def test_long_message_is_chunk_safe(self):
        notifier = self._notifier()
        result = {
            "verdict": "SELL",
            "analyst_count": 4,
            "trader_plan": "x" * 5000,  # force >4096
            "risk_assessment": "r",
        }
        with patch.object(notifier, "_post", return_value=True) as mock_post:
            ok = notifier.pipeline_result("AAPL", "death_cross", result)
        assert ok is True
        assert mock_post.call_count >= 2
        for call in mock_post.call_args_list:
            assert len(call.args[1]["text"]) <= _WORKING_LIMIT
