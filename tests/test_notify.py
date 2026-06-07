"""Tests for notify: Telegram message splitting and chunked send (#11)."""

from unittest.mock import patch

from watchy.notify import (
    TelegramNotifier,
    _WORKING_LIMIT,
    _split_message,
)


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
