"""Windows-only provider credential storage and crash-released edit exclusion."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
from collections.abc import Callable, Mapping

TARGET = "InterviewCopilot/Deepgram"
KEY_ENV = "COPILOT_DEEPGRAM_API_KEY"
DEEPSEEK_TARGET = "InterviewCopilot/DeepSeek"
DEEPSEEK_KEY_ENV = "COPILOT_DEEPSEEK_API_KEY"


class CredentialError(Exception):
    """Report a bounded failure without including OS payloads or secrets."""


class CredentialBusy(CredentialError):
    """Indicate a conflicting capture or credential operation."""


class _Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def _libraries():
    if os.name != "nt":
        raise CredentialError("windows_required")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(_Credential)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [pointer, wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api


def valid_key(value: str) -> bool:
    """Accept bounded printable ASCII tokens, never whitespace or header controls."""
    return 1 <= len(value) <= 256 and all(33 <= ord(char) <= 126 for char in value)


def valid_deepseek_key(value: str) -> bool:
    """Match the DeepSeek adapter: 16-200 URL-safe token characters, nothing else."""
    return 16 <= len(value) <= 200 and all(
        char.isascii() and (char.isalnum() or char in "._-") for char in value
    )


@dataclass(frozen=True)
class CredentialSpec:
    """Explicit allowlisted identity for one provider credential namespace.

    The target, environment override and lock name never come from a renderer or
    helper argument; callers can only select a key from ``CREDENTIAL_SPECS``.
    """

    name: str
    display_name: str
    target: str
    env: str
    gate_name: str
    validate: Callable[[str], bool]


CREDENTIAL_SPECS = {
    "deepgram": CredentialSpec("deepgram", "Deepgram", TARGET, KEY_ENV, "deepgram.lock", valid_key),
    "deepseek": CredentialSpec("deepseek", "DeepSeek", DEEPSEEK_TARGET, DEEPSEEK_KEY_ENV,
                              "deepseek.lock", valid_deepseek_key),
}


def credential_spec(provider: str) -> CredentialSpec:
    """Return only a fixed provider profile; reject unknown names."""
    try:
        return CREDENTIAL_SPECS[provider]
    except (KeyError, TypeError):
        raise CredentialError("unknown_provider") from None


class WindowsCredentialStore:
    """Read/write one user-scoped generic credential; never enumerate credentials."""

    def __init__(self, target: str = TARGET, *, validate: Callable[[str], bool] = valid_key):
        self._target = target
        self._validate = validate

    def read(self) -> str | None:
        """Read a token into backend memory, clearing the native buffer before release."""
        api = _libraries()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self._target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise CredentialError("credential_read_failed")
        try:
            credential = pointer.contents
            if credential.CredentialBlobSize > 512 or credential.CredentialBlobSize % 2:
                raise CredentialError("invalid_stored_credential")
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode("utf-16-le")
        except UnicodeError:
            raise CredentialError("invalid_stored_credential") from None
        finally:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
            api.CredFree(pointer)

    def write(self, key: str) -> None:
        """Persist a token validated for this store's provider only."""
        if not self._validate(key):
            raise CredentialError("invalid_key")
        api = _libraries()
        buffer = ctypes.create_unicode_buffer(key)
        try:
            credential = _Credential()
            credential.Type = 1  # CRED_TYPE_GENERIC
            credential.TargetName = self._target
            credential.UserName = "Interview Copilot"
            credential.Persist = 2  # Same user, subsequent logons, this computer; not roaming.
            credential.CredentialBlobSize = len(key) * 2
            credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE))
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError("credential_write_failed")
        finally:
            ctypes.memset(buffer, 0, ctypes.sizeof(buffer))

    def delete(self) -> None:
        """Delete only this application's target; absence is an idempotent success."""
        api = _libraries()
        if not api.CredDeleteW(self._target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError("credential_delete_failed")


def resolve_provider_key(spec: CredentialSpec, environ: Mapping[str, str],
                         store: WindowsCredentialStore) -> tuple[str | None, str]:
    """Resolve one provider's environment override, then its own Windows target only."""
    if spec.env in environ:
        key = environ[spec.env]
        if not spec.validate(key):
            raise CredentialError("invalid_environment")
        return key, "environment"
    key = store.read() if os.name == "nt" else None
    if key is not None and not spec.validate(key):
        raise CredentialError("invalid_stored_credential")
    return key, "windows" if key is not None else "none"


def resolve_key(environ: Mapping[str, str], store: WindowsCredentialStore) -> tuple[str | None, str]:
    """Resolve the Deepgram key; an explicitly invalid override never falls back."""
    return resolve_provider_key(CREDENTIAL_SPECS["deepgram"], environ, store)


def _security_directory() -> Path:
    """Use a fixed per-user location independent of COPILOT_DATA_DIR and shell overrides."""
    if os.name != "nt":
        raise CredentialError("windows_required")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(260)
    if shell.SHGetFolderPathW(None, 0x1C, None, 0, buffer) != 0:
        raise CredentialError("profile_unavailable")
    return Path(buffer.value) / "InterviewCopilot" / "security"


def credential_gate_path(provider: str = "deepgram") -> Path:
    """Return the fixed per-provider capture/edit lock; never a caller path."""
    return _security_directory() / credential_spec(provider).gate_name


def mutation_gate_path() -> Path:
    """Serialize native credential dialogs across providers and processes."""
    return _security_directory() / "credentials.lock"


class CredentialGate:
    """Hold a shared capture lease or an exclusive mutation lease until close/crash."""

    def __init__(self, *, exclusive: bool, path: Path | None = None):
        self._handle = None
        self._kernel = None
        if os.name != "nt":
            if exclusive:
                raise CredentialError("windows_required")
            return  # Non-Windows API/tests retain local STT; Windows persistence is unavailable.
        path = path if path is not None else credential_gate_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(path), 0x80000000 | (0x40000000 if exclusive else 0),
                                    0 if exclusive else 1, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error == 32:
                raise CredentialBusy("credential_busy")
            raise CredentialError("credential_gate_failed")
        self._kernel, self._handle = kernel, handle

    def close(self) -> None:
        """Release once; handles are noninheritable and also released by Windows on exit."""
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> CredentialGate:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
