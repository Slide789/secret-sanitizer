"""PDF: Text herausziehen; ausgegeben wird eine bereinigte .txt-Datei.

Die PDF selbst wird nicht geschwärzt: Text ist in PDFs oft so zerstückelt
gespeichert, dass beim Schwärzen Reste stehen bleiben können. Zum Weitergeben
reicht der Text.

Sicherheit: PDFs sind ein beliebtes Angriffsformat. Der Text wird darum in
einem eigenen Prozess gelesen (pypdf, reines Python) mit
  - Zeitlimit (pdf_timeout_s): hängt der Parser, wird der Prozess beendet,
  - hartem Speicherlimit (pdf_max_memory_mb; Windows: Job-Objekt,
    Linux/macOS: rlimit), Seiten- und Textlimit.
Der Text kommt nur über eine interne Pipe zurück, nie über die Festplatte.
Verschlüsselte PDFs (mit Kennwort) und gescannte PDFs ohne Text werden
übersprungen.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
from pathlib import Path

MAX_PAGES = 5000
PAGE_SEPARATOR = "\n\n"


class PdfError(Exception):
    """PDF kann nicht gelesen werden. Meldung ohne Inhalte."""


class PdfSkipped(PdfError):
    """PDF wird bewusst nicht verarbeitet (verschlüsselt, ohne Text, pypdf fehlt)."""


def is_pdf(name: str) -> bool:
    return name.lower().endswith(".pdf")


def available() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


# ----------------------------------------------------------------------
# Im Kindprozess
# ----------------------------------------------------------------------

def _limit_memory(max_bytes: int) -> None:
    """Linux/macOS: harte Speichergrenze für den Kindprozess (rlimit).
    Unter Windows setzt der Hauptprozess ein Job-Objekt (siehe _windows_job);
    hier wird nur der Absturz-Dialog abgeschaltet, damit ein Abbruch wegen
    Speichermangels nicht bis zum Zeitlimit hängen bleibt."""
    if sys.platform.startswith("win"):
        import ctypes

        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        ctypes.WinDLL("kernel32").SetErrorMode(0x0001 | 0x0002 | 0x8000)
    else:  # pragma: no cover - auf Windows nicht testbar
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))


def _extract_child(path: str, max_chars: int, max_bytes: int, conn) -> None:
    try:
        _limit_memory(max_bytes)
        # Keine Parser-Warnungen von pypdf auf der Konsole (nur in diesem Leseprozess)
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted:
            # Viele PDFs sind nur "verschlüsselt" mit leerem Kennwort (Rechte-Einschränkung)
            try:
                if not reader.decrypt(""):
                    conn.send(("skip", "PDF ist mit Kennwort verschlüsselt"))
                    return
            except Exception:  # noqa: BLE001
                conn.send(("skip", "PDF ist verschlüsselt (Verfahren nicht unterstützt)"))
                return
        if len(reader.pages) > MAX_PAGES:
            conn.send(("error", f"PDF hat mehr als {MAX_PAGES} Seiten"))
            return
        parts, total = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            total += len(text)
            if total > max_chars:
                conn.send(("error", "Text der PDF zu groß (max_file_size_mb)"))
                return
            parts.append(text.strip())
        conn.send(("ok", PAGE_SEPARATOR.join(p for p in parts if p) + "\n"))
    except MemoryError:
        conn.send(("error", "PDF braucht zu viel Speicher"))
    except Exception as exc:  # noqa: BLE001 - nur die Fehlerart, nie den Text
        conn.send(("error", f"PDF beschädigt oder nicht lesbar ({type(exc).__name__})"))
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Im Hauptprozess
# ----------------------------------------------------------------------

def _windows_job(pid: int, max_bytes: int):
    """Windows: Kindprozess in ein Job-Objekt mit hartem Speicherlimit stecken.
    Das Betriebssystem verweigert dann mehr Speicher; wird das Job-Handle
    geschlossen, beendet Windows den Prozess (KILL_ON_JOB_CLOSE).
    Rückgabe: Job-Handle (zum Schließen) oder None, falls nicht möglich."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes",
                                                          "WriteBytes", "OtherBytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x100 | 0x2000   # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    limits.ProcessMemoryLimit = max_bytes
    process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
    ok = bool(process) and kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) \
        and kernel.AssignProcessToJobObject(job, process)
    if process:
        kernel.CloseHandle(process)
    if not ok:
        kernel.CloseHandle(job)
        return None
    return job


def _close_job(job) -> None:
    if job:
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(job)


def extract_text(src: Path, settings) -> str:
    """Text einer PDF (Seiten durch Leerzeilen getrennt). Wirft PdfError."""
    if not available():
        raise PdfSkipped("PDF-Unterstützung nicht installiert (Paket pypdf fehlt)")
    timeout = float(getattr(settings, "pdf_timeout_s", 60))
    max_bytes = int(getattr(settings, "pdf_max_memory_mb", 1024)) * 1024 * 1024
    max_chars = int(settings.max_file_size_mb * 1024 * 1024)
    ctx = mp.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_extract_child, args=(str(src), max_chars, max_bytes, send), daemon=True)
    process.start()
    send.close()
    job = _windows_job(process.pid, max_bytes)
    try:
        if not receive.poll(timeout):
            raise PdfError(f"Zeitlimit beim Lesen der PDF überschritten ({timeout:g} s)")
        try:
            status, value = receive.recv()
        except EOFError:
            raise PdfError("PDF braucht zu viel Speicher oder hat den Leser abstürzen lassen") from None
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
        process.join(5)
        _close_job(job)
    if status == "skip":
        raise PdfSkipped(value)
    if status != "ok":
        raise PdfError(value)
    if not value.strip():
        raise PdfSkipped("kein Text in der PDF (gescannt?)")
    return value
