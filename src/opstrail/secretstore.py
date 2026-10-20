"""Protect small secrets (LLM API keys) at rest.

Windows: DPAPI (CryptProtectData, current-user scope) – the file is useless on another account/machine.
Other OS: base64 in a 0600 file (prefer the OPSTRAIL_LLM_API_KEY environment variable there).
"""

from __future__ import annotations

import base64
import sys


class SecretError(RuntimeError):
    pass


def protect(value: str) -> str:
    raw = value.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, encrypt=True)).decode("ascii")
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unprotect(token: str) -> str:
    if not token:
        return ""
    scheme, _, payload = token.partition(":")
    data = base64.b64decode(payload.encode("ascii"))
    if scheme == "dpapi":
        if sys.platform != "win32":
            raise SecretError("this key was encrypted with Windows DPAPI on another machine")
        return _dpapi(data, encrypt=False).decode("utf-8")
    if scheme == "plain":
        return data.decode("utf-8")
    raise SecretError(f"unknown secret format {scheme!r}")


def _dpapi(data: bytes, encrypt: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,  # description (in: LPCWSTR / out: LPWSTR*) – unused
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    fn.restype = wintypes.BOOL

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not fn(ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise SecretError(f"DPAPI failed (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
