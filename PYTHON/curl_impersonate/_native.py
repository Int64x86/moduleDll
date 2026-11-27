import atexit
import ctypes
import json
import os
import re
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import NativeLibraryError


def get_loaded_dll_path(name):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p

    kernel32.GetModuleFileNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetModuleFileNameW.restype = ctypes.c_uint32

    handle = kernel32.GetModuleHandleW(name)

    if not handle:
        return None

    buffer = ctypes.create_unicode_buffer(32768)
    kernel32.GetModuleFileNameW(handle, buffer, len(buffer))

    return buffer.value


class NativeRuntime:
    def __init__(self, library_path: Optional[os.PathLike] = None):
        self.path = self._find_library(library_path)
        dll_dir = str(self.path.parent)
        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        self._dll_directory = os.add_dll_directory(dll_dir)
        self.dll = None
        self._dependencies = []
        dependency_names = (
            "libeay32.dll",
            "ssleay32.dll",
            "Qt5Core.dll",
            "Qt5Network.dll",
            "Qt5Gui.dll",
            "Qt5Widgets.dll",
            "Qt5Xml.dll",
        )

        try:
            for name in dependency_names:
                expected = self.path.parent / name
                loaded = get_loaded_dll_path(name)
                if loaded and os.path.normcase(loaded) != os.path.normcase(str(expected)):
                    raise NativeLibraryError(
                        f"{name} is already loaded from another directory: {loaded}"
                    )
                self._dependencies.append(ctypes.CDLL(str(expected)))

            self.dll = ctypes.CDLL(str(self.path))
            self._bind()
            self._clients = weakref.WeakSet()
            self._lock = threading.RLock()
            result = self.dll.ci_initialize(b"{}")
            if result != 0:
                message = self.dll.ci_last_error()
                error = message.decode("utf-8") if message else "unknown loader error"
                raise NativeLibraryError(
                    f"ci_initialize failed with code {result}: {error}"
                )
        except Exception as error:
            self.dll = None
            self._dependencies.clear()
            self._dll_directory.close()
            if isinstance(error, NativeLibraryError):
                raise
            raise NativeLibraryError(str(error)) from error

    @staticmethod
    def _find_library(library_path: Optional[os.PathLike]) -> Path:
        candidates = []
        if library_path:
            candidates.append(Path(library_path))
        candidates.extend(
            [
                Path(__file__).resolve().parent / "bin" / "moduledll.dll",
                Path.cwd() / "moduledll.dll",
            ]
        )
        for candidate in candidates:
            path = candidate.expanduser().resolve()
            if path.is_file():
                return path
        raise NativeLibraryError(
            "moduledll.dll not found; place it in curl_impersonate/bin or the current directory"
        )

    def _bind(self) -> None:
        self.dll.ci_initialize.argtypes = [ctypes.c_char_p]
        self.dll.ci_initialize.restype = ctypes.c_int
        self.dll.ci_last_error.argtypes = []
        self.dll.ci_last_error.restype = ctypes.c_char_p
        self.dll.ci_client_create.argtypes = []
        self.dll.ci_client_create.restype = ctypes.c_void_p
        self.dll.ci_client_call.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.dll.ci_client_call.restype = ctypes.c_int
        self.dll.ci_client_cancel.argtypes = [ctypes.c_void_p]
        self.dll.ci_client_cancel.restype = None
        self.dll.ci_client_destroy.argtypes = [ctypes.c_void_p]
        self.dll.ci_client_destroy.restype = None
        self.dll.ci_free.argtypes = [ctypes.c_void_p]
        self.dll.ci_free.restype = None
        self.dll.ci_shutdown.argtypes = []
        self.dll.ci_shutdown.restype = None

    def create_client(self) -> ctypes.c_void_p:
        handle = self.dll.ci_client_create()
        if not handle:
            raise NativeLibraryError("ci_client_create failed")
        return handle

    def call(self, handle: ctypes.c_void_p, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(
            request, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        output = ctypes.c_void_p()
        output_size = ctypes.c_size_t()
        code = self.dll.ci_client_call(
            handle, payload, ctypes.byref(output), ctypes.byref(output_size)
        )
        if not output.value:
            raise NativeLibraryError(f"ci_client_call failed with code {code}")
        try:
            data = ctypes.string_at(output, output_size.value)
        finally:
            self.dll.ci_free(output)
        return json.loads(data.decode("utf-8"))

    def shutdown(self) -> None:
        with self._lock:
            for client in list(self._clients):
                client.close()
            if self.dll:
                self.dll.ci_shutdown()
                self.dll = None
                self._dependencies.clear()
                self._dll_directory.close()


_runtime = None
_runtime_lock = threading.Lock()


def get_runtime(library_path: Optional[os.PathLike] = None) -> NativeRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = NativeRuntime(library_path)
        elif library_path and Path(library_path).resolve() != _runtime.path:
            raise NativeLibraryError("the native runtime is already initialized with another DLL")
        return _runtime


def set_module_version(version: str) -> None:
    """
    Set the native module version to use.

    If the specified version is not installed locally, the native loader
    will automatically download and install it during initialization.

    Call this function before creating the first Client instance.

    Args:
        version: Target module version (e.g. "4.5.8").
            Empty strings are not supported.

    Raises:
        RuntimeError: If the native runtime is already loaded.
        ValueError: If the version contains a line break.
        NativeLibraryError: If the loader configuration cannot be read or updated.
    """
    if not isinstance(version, str):
        raise TypeError("version must be a string")
    if "\r" in version or "\n" in version:
        raise ValueError("version must be a single line")
    if not version.strip() or "\r" in version or "\n" in version:
        raise ValueError("version must be a non-empty single line")

    with _runtime_lock:
        if _runtime is not None:
            raise RuntimeError(
                "set_module_version() must be called before creating Client"
            )

        config_path = (
            NativeRuntime._find_library(None).parent / "RemoteConfig.ini"
        )
        try:
            content = config_path.read_bytes()
            updated, replacements = re.subn(
                br"(?mi)^VERSION[ \t]*=[^\r\n]*",
                b"VERSION=" + version.strip().encode("utf-8"),
                content,
                count=1,
            )
            if replacements != 1:
                raise NativeLibraryError(
                    f"VERSION not found in {config_path}"
                )
            config_path.write_bytes(updated)
        except NativeLibraryError:
            raise
        except OSError as error:
            raise NativeLibraryError(
                f"Unable to update {config_path}: {error}"
            ) from error


def shutdown() -> None:
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            _runtime.shutdown()
            _runtime = None


atexit.register(shutdown)
