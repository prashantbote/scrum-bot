import time
import uuid

import pytest

from scrum_core.security.crypto import LocalKek, seal, unseal
from scrum_core.security.tokens import InvalidToken, blocker_token, checkin_token, sign, verify, verify_payload

ORG = uuid.uuid4()


def test_blocker_token_roundtrip():
    bid = uuid.uuid4()
    c = verify(blocker_token(org_id=ORG, blocker_id=bid, recipient="amit@acme.example"))
    assert (c.kind, c.org_id, c.blocker_id, c.recipient, c.expired) == ("blocker", ORG, bid, "amit@acme.example", False)


def test_checkin_token_and_expiry_is_reported_not_raised():
    c = verify(
        checkin_token(org_id=ORG, session_id=uuid.uuid4(), user_id=uuid.uuid4(), expires_at=int(time.time()) - 5)
    )
    assert c.kind == "checkin" and c.expired


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),  # signature
        lambda t: "x" + t,  # payload
        lambda t: t.split(".")[0],  # no signature
        lambda t: "garbage",
    ],
)
def test_tampered_tokens_are_rejected(mangle):
    with pytest.raises(InvalidToken):
        verify(mangle(blocker_token(org_id=ORG, blocker_id=uuid.uuid4(), recipient="a@b.c")))


def test_oauth_state_payload():
    tok = sign({"k": "oauth", "org": str(ORG), "exp": int(time.time()) + 60})
    assert verify_payload(tok, kind="oauth")["org"] == str(ORG)
    with pytest.raises(InvalidToken):
        verify_payload(tok, kind="file")
    with pytest.raises(InvalidToken):
        verify_payload(sign({"k": "oauth", "exp": 1}), kind="oauth")


def test_envelope_encryption_binds_ciphertext_to_its_row():
    kek = LocalKek(b"k" * 32, "kek-test")
    sealed = seal('{"access_token":"secret"}', aad="integration:org-a:jira", kek=kek)
    assert b"secret" not in sealed.ciphertext and sealed.key_id == "kek-test"
    assert unseal(sealed, aad="integration:org-a:jira", kek=kek) == '{"access_token":"secret"}'
    with pytest.raises(Exception):
        unseal(sealed, aad="integration:org-b:jira", kek=kek)  # swapped between tenants
    with pytest.raises(ValueError):
        unseal(sealed, aad="integration:org-a:jira", kek=LocalKek(b"z" * 32, "other"))
