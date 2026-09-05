import pytest

from mcmt.tree.codecs import command


def test_decode_returns_the_text_unchanged():
    assert command.decode("say hello") == "say hello"


def test_decode_rejects_non_string_input():
    with pytest.raises(TypeError):
        command.decode(123)


def test_encode_returns_the_text_unchanged():
    assert command.encode("say hello") == "say hello"
