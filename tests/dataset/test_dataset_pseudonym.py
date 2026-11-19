import re
import stat

import pytest

from growbridge.dataset.pseudonym import Pseudonymizer, load_or_create_key


def test_pseudonyms(tmp_path):
    key = load_or_create_key(tmp_path / "export" / "pseudonym.key")
    assert len(key) == 32 and load_or_create_key(tmp_path / "export" / "pseudonym.key") == key
    assert stat.S_IMODE((tmp_path / "export" / "pseudonym.key").stat().st_mode) == 0o600
    p = Pseudonymizer(key)
    assert re.fullmatch(r"op-[0-9a-f]{12}", p("alice"))
    assert p("alice") == p("alice") != p("bob") and p(None) is None


def test_key_changes_the_pseudonym():
    assert Pseudonymizer(b"a" * 32)("alice") != Pseudonymizer(b"b" * 32)("alice")


def test_key_of_wrong_length_is_refused(tmp_path):
    (tmp_path / "k").write_bytes(b"short")
    with pytest.raises(ValueError):
        load_or_create_key(tmp_path / "k")
