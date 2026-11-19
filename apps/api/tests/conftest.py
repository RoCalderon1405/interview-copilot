"""Never consult or mutate an owner's real cloud credential during automated checks."""
import pytest

from app.infrastructure import windows_credentials as credentials


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv(credentials.KEY_ENV, raising=False)
    monkeypatch.setattr(credentials, "credential_gate_path", lambda: tmp_path / "credential.lock")
    read = credentials.WindowsCredentialStore.read
    write = credentials.WindowsCredentialStore.write
    delete = credentials.WindowsCredentialStore.delete

    def safe_read(self):
        return None if self._target == credentials.TARGET else read(self)

    def safe_write(self, key):
        assert self._target.startswith("InterviewCopilot-CLOUD001-Test-"), "Real credential writes forbidden in tests"
        return write(self, key)

    def safe_delete(self):
        assert self._target.startswith("InterviewCopilot-CLOUD001-Test-"), "Real credential deletion forbidden in tests"
        return delete(self)

    monkeypatch.setattr(credentials.WindowsCredentialStore, "read", safe_read)
    monkeypatch.setattr(credentials.WindowsCredentialStore, "write", safe_write)
    monkeypatch.setattr(credentials.WindowsCredentialStore, "delete", safe_delete)
