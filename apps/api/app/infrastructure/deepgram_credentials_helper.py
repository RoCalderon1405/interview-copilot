"""Fixed-path Windows helper for allowlisted provider credentials.

The command line and output never carry a credential. Deepgram keeps its
existing argument shape; other providers append one allowlisted provider name.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import threading
import uuid

# -I deliberately excludes cwd/PYTHONPATH; import only the adjacent trusted API package.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.infrastructure.windows_credentials import (CREDENTIAL_SPECS, CredentialBusy, CredentialError,
                                                     CredentialGate, WindowsCredentialStore, credential_spec,
                                                     credential_gate_path, mutation_gate_path)


class _Info(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hwndParent", wintypes.HWND),
                ("pszMessageText", wintypes.LPCWSTR), ("pszCaptionText", wintypes.LPCWSTR),
                ("hbmBanner", wintypes.HBITMAP)]


def prompt(owner: int, language: str, provider: str = "deepgram") -> str | None:
    """Show an empty generic Windows credential prompt, not a Windows logon request."""
    spec = credential_spec(provider)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindow.argtypes = [wintypes.HWND]
    if not user.IsWindow(owner):
        raise CredentialError("invalid_owner")
    es = language == "es"
    info = _Info(ctypes.sizeof(_Info), owner,
                 f"Introduce tu API Key de {spec.display_name} en Contraseña. NO introduzcas la contraseña de Windows."
                 if es else f"Enter your {spec.display_name} API Key in Password. Do NOT enter your Windows password.",
                 f"Interview Copilot - {spec.display_name} API Key", None)
    username = ctypes.create_unicode_buffer(spec.display_name + " API Key", 128)
    password = ctypes.create_unicode_buffer(257)
    save = wintypes.BOOL(False)
    ui = ctypes.WinDLL("credui", use_last_error=True)
    ui.CredUIPromptForCredentialsW.argtypes = [ctypes.POINTER(_Info), wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, wintypes.LPWSTR, wintypes.ULONG, wintypes.LPWSTR, wintypes.ULONG,
        ctypes.POINTER(wintypes.BOOL), wintypes.DWORD]
    ui.CredUIPromptForCredentialsW.restype = wintypes.DWORD
    try:
        # Generic, always show, do not let CredUI persist, lock the non-secret username.
        result = ui.CredUIPromptForCredentialsW(ctypes.byref(info), f"InterviewCopilot/{spec.display_name}-entry-" + str(uuid.uuid4()), None,
            0, username, len(username), password, len(password), ctypes.byref(save), 0x40000 | 0x80 | 2 | 0x100000)
        if result == 1223:
            return None
        if result or not spec.validate(password.value):
            raise CredentialError("dialog_or_input_failed")
        return password.value
    finally:
        ctypes.memset(password, 0, ctypes.sizeof(password))
        ctypes.memset(username, 0, ctypes.sizeof(username))


def emit(result: str, stored: bool | None = None) -> None:
    """Write only the fixed status schema, never exceptions or provider responses."""
    print(json.dumps({"result": result, "stored": stored}), flush=True)


def _watch_parent(timeout_ms: int, parent_pid: int) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Windows venv launchers may insert an intermediate process. Watch Electron itself.
    parent = kernel.OpenProcess(0x100000, False, parent_pid)
    if not parent:
        os._exit(2)
    result = kernel.WaitForSingleObject(parent, timeout_ms)
    kernel.CloseHandle(parent)
    try:
        emit("cancelled" if result == 0 else "timed_out")
    except OSError:
        pass
    finally:
        os._exit(2)


def _watch_cancel() -> None:
    # EOF survives a venv launcher: never rely on killing just its outer PID.
    os.read(sys.stdin.fileno(), 1)
    try:
        emit("cancelled")
    except OSError:
        pass
    finally:
        os._exit(2)


def run(arguments: list[str], *, store: WindowsCredentialStore | None = None,
        gate_path: Path | None = None, mutation_path: Path | None = None) -> None:
    """Execute one bounded operation; injected targets are Python-test-only.

    The fifth argument, when present, selects one allowlisted provider profile.
    Deepgram keeps the original four-argument form and remains the only provider
    allowed to hold a capture lease.
    """
    if os.name != "nt":
        emit("unsupported")
        return
    provider = arguments[4] if len(arguments) == 5 else "deepgram"
    if (len(arguments) not in {4, 5} or arguments[0] not in {"status", "configure", "replace", "delete", "lease"}
            or arguments[2] not in {"en", "es"} or provider not in CREDENTIAL_SPECS):
        emit("error")
        return
    operation, raw_owner, language, raw_parent = arguments[:4]
    if operation == "lease" and provider != "deepgram":
        emit("error")
        return
    try:
        owner = int(raw_owner)
        parent_pid = int(raw_parent)
        if parent_pid < 1:
            raise CredentialError("invalid_parent")
        spec = CREDENTIAL_SPECS[provider]
        store = store if store is not None else WindowsCredentialStore(spec.target, validate=spec.validate)
        if operation == "status":
            emit("status", store.read() is not None)
            return
        # One global lease serializes native dialogs across providers; the
        # provider lease keeps each namespace independent and conflicts across
        # processes. Capture leases also share the global lock.
        with CredentialGate(exclusive=operation != "lease", path=mutation_path or mutation_gate_path()):
            with CredentialGate(exclusive=operation != "lease", path=gate_path or credential_gate_path(provider)):
                if operation == "lease":
                    # The native parent retains stdin until its capture window closes.
                    threading.Thread(target=_watch_parent, args=(0xFFFFFFFF, parent_pid), daemon=True).start()
                    emit("leased")
                    sys.stdin.buffer.read(1)
                    return
                threading.Thread(target=_watch_parent, args=(120000, parent_pid), daemon=True).start()
                threading.Thread(target=_watch_cancel, daemon=True).start()
                exists = store.read() is not None
                if operation == "delete":
                    store.delete()
                    emit("deleted", False)
                elif (operation == "configure" and exists) or (operation == "replace" and not exists):
                    emit("conflict", exists)
                else:
                    key = prompt(owner, language, provider)
                    if key is None:
                        emit("cancelled", exists)
                    elif not spec.validate(key):
                        # Re-check even with an injected store/prompt override.
                        emit("error")
                    else:
                        store.write(key)
                        key = None
                        emit("configured", True)
    except CredentialBusy:
        emit("busy")
    except Exception:
        # No traceback: exceptions can retain native buffers/paths in their context.
        emit("error")


if __name__ == "__main__":
    run(sys.argv[1:])
