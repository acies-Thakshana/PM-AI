"""Tests of file_store (downloads kept per user and session in S3) using moto, a fake AWS.

moto runs a pretend S3 inside this Python process. The app's own boto3 calls go to it unchanged,
so nothing real is read or written and no AWS account is needed.
"""
import boto3
import pytest
from moto import mock_aws

from app.services.common import aws_clients, file_store, request_context

BUCKET = "pmai-test-bucket"
REGION = "eu-north-1"


@pytest.fixture
def s3_bucket(monkeypatch):
    """A fake S3 with one empty bucket, wired into file_store."""
    # moto insists on credentials existing; these are dummies and never leave the process
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        aws_clients._clients.clear()  # the app caches its client: make it build one inside the fake
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        monkeypatch.setattr(file_store, "S3_BUCKET", BUCKET)
        yield client
        aws_clients._clients.clear()


@pytest.fixture
def as_user():
    """as_user('user-a') makes the next calls run as that user, like a request would."""
    tokens = []

    def _set(user_id):
        tokens.append(request_context.current_user_id.set(user_id))

    yield _set
    for token in reversed(tokens):
        request_context.current_user_id.reset(token)


def _keys(client):
    return [o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


def test_put_then_get_round_trip(s3_bucket, as_user):
    """Happy path: what is stored comes back byte for byte."""
    as_user("user-a")
    assert file_store.put("sess1", "reports/r.pptx", b"deck-bytes") is True
    assert file_store.get("sess1", "reports/r.pptx") == b"deck-bytes"


def test_object_key_holds_user_and_session(s3_bucket, as_user):
    """The key is users/<user>/sessions/<session>/<name>, so each user's files sit under their own prefix."""
    as_user("user-a")
    file_store.put("sess1", "x.xlsx", b"1")
    assert _keys(s3_bucket) == ["users/user-a/sessions/sess1/x.xlsx"]


def test_other_user_cannot_read_the_file(s3_bucket, as_user):
    """Negative / isolation (TC-SEC IDOR): user B asking for A's session and file name gets nothing."""
    as_user("user-a")
    file_store.put("sess1", "x.xlsx", b"secret")
    as_user("user-b")
    assert file_store.get("sess1", "x.xlsx") is None


def test_missing_file_is_none_not_an_error(s3_bucket, as_user):
    """Edge case: a file that was never stored."""
    as_user("user-a")
    assert file_store.get("sess1", "nope.pptx") is None


def test_delete_removes_the_file(s3_bucket, as_user):
    """Happy path: after delete the file is gone, and deleting again is harmless."""
    as_user("user-a")
    file_store.put("sess1", "x.xlsx", b"1")
    file_store.delete("sess1", "x.xlsx")
    assert file_store.get("sess1", "x.xlsx") is None
    file_store.delete("sess1", "x.xlsx")


@pytest.mark.parametrize("name", ["../x", "/abs/x", "a b.xlsx", "x" * 201, ""])
def test_unsafe_file_names_are_refused(s3_bucket, as_user, name):
    """Negative: path tricks and odd names are not stored (put returns False) and nothing lands in the bucket."""
    as_user("user-a")
    assert file_store.put("sess1", name, b"x") is False
    assert _keys(s3_bucket) == []


@pytest.mark.parametrize("session_id", ["../other", "a/b", "", "x y"])
def test_unsafe_session_ids_are_refused(s3_bucket, as_user, session_id):
    """Negative: a session id from a URL cannot climb out of its folder."""
    as_user("user-a")
    assert file_store.put(session_id, "x.xlsx", b"x") is False
    assert _keys(s3_bucket) == []


def test_odd_characters_in_user_id_are_made_safe(s3_bucket, as_user):
    """Edge case: a user id with slashes cannot add folders to the key."""
    as_user("a/../b")
    file_store.put("sess1", "x.xlsx", b"1")
    assert _keys(s3_bucket) == ["users/a_.._b/sessions/sess1/x.xlsx"]


def test_s3_failure_does_not_crash_the_request(monkeypatch, as_user):
    """Error handling: if S3 is down, put says False and get says None; the caller serves the file it just built.
    No moto here: monkeypatch makes the S3 client itself blow up."""

    def boom():
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(file_store, "S3_BUCKET", "any-bucket")
    monkeypatch.setattr(aws_clients, "s3", boom)
    as_user("user-a")
    assert file_store.put("sess1", "x.xlsx", b"1") is False
    assert file_store.get("sess1", "x.xlsx") is None
