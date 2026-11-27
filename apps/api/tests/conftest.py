"""Never consult or mutate an owner's real cloud credential during automated checks."""
import pytest

from app.infrastructure import windows_credentials as credentials


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv(credentials.KEY_ENV, raising=False)
    monkeypatch.delenv(credentials.DEEPSEEK_KEY_ENV, raising=False)
    monkeypatch.setattr(credentials, "credential_gate_path", lambda *_: tmp_path / "credential.lock")
    monkeypatch.setattr(credentials, "mutation_gate_path", lambda: tmp_path / "mutation.lock")
    # The helper imports these names directly, so patch its local references too.
    from app.infrastructure import deepgram_credentials_helper as helper
    monkeypatch.setattr(helper, "credential_gate_path", lambda *_: tmp_path / "credential.lock")
    monkeypatch.setattr(helper, "mutation_gate_path", lambda: tmp_path / "mutation.lock")
    read = credentials.WindowsCredentialStore.read
    write = credentials.WindowsCredentialStore.write
    delete = credentials.WindowsCredentialStore.delete

    def safe_read(self):
        return None if self._target in {credentials.TARGET, credentials.DEEPSEEK_TARGET} else read(self)

    def safe_write(self, key):
        assert self._target.startswith("InterviewCopilot-CLOUD001-Test-"), "Real credential writes forbidden in tests"
        return write(self, key)

    def safe_delete(self):
        assert self._target.startswith("InterviewCopilot-CLOUD001-Test-"), "Real credential deletion forbidden in tests"
        return delete(self)

    monkeypatch.setattr(credentials.WindowsCredentialStore, "read", safe_read)
    monkeypatch.setattr(credentials.WindowsCredentialStore, "write", safe_write)
    monkeypatch.setattr(credentials.WindowsCredentialStore, "delete", safe_delete)
