"""Mehrere CPU-Kerne für Ordnerläufe.

Die Platzhalter müssen in allen Dateien gleich sein und genauso nummeriert
werden wie bei einem Lauf mit einem Kern. Darum:

  Durchlauf 1 (lernen): Jeder Worker erkennt die Werte seiner Datei mit
      einem eigenen, leeren Mapping und gibt sie in der Reihenfolge ihres
      ersten Auftretens zurück. Erst der Hauptprozess vergibt Platzhalter,
      und zwar in der festen Dateireihenfolge.
  Durchlauf 2 (ersetzen): Jeder Worker bekommt eine Kopie des fertigen
      Mappings. Findet er doch einen neuen Wert, verwirft er seine Ausgabe
      und meldet das; der Hauptprozess bearbeitet die Datei dann selbst.

Werte wandern nur im Arbeitsspeicher (über interne Pipes) zwischen den
Prozessen, nie über die Festplatte. Abbrechen setzt ein gemeinsames Event,
das die Worker zwischen zwei Blöcken prüfen.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import pickle
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

# Ab hier lohnt sich der Start zusätzlicher Prozesse (Windows startet jeden
# Prozess neu und lädt Regeln neu, das kostet etwa eine halbe Sekunde).
PARALLEL_MIN_FILES = 4
PARALLEL_MIN_BYTES = 4 * 1024 * 1024
MAX_AUTO_WORKERS = 8

_W: dict = {}   # Zustand im Worker-Prozess


def worker_count(settings) -> int:
    """Anzahl Worker laut Einstellung: 0 = automatisch (Kerne - 1, höchstens 8),
    1 = aus."""
    configured = int(getattr(settings, "workers", 0) or 0)
    if configured > 0:
        return configured
    return max(1, min(MAX_AUTO_WORKERS, (os.cpu_count() or 1) - 1))


def should_parallelize(settings, file_count: int, total_bytes: int) -> bool:
    return worker_count(settings) > 1 and file_count >= PARALLEL_MIN_FILES and total_bytes >= PARALLEL_MIN_BYTES


# ----------------------------------------------------------------------
# Im Worker-Prozess
# ----------------------------------------------------------------------

def _init_worker(settings, ruleset, exclude, mapping_blob, language, cancel_event) -> None:
    from ..i18n import set_language
    from .pipeline import Sanitizer

    set_language(language)   # der gestartete (spawn) Prozess kennt die Sprache des Hauptprozesses nicht

    sanitizer = Sanitizer(settings, ruleset)
    _W.update(sanitizer=sanitizer, settings=settings, exclude=tuple(exclude), cancel=cancel_event,
              mapping_blob=mapping_blob)
    if mapping_blob is not None:
        sanitizer.mapping = pickle.loads(mapping_blob)


def _learn_task(src: str, encoding: str):
    from .files import learn_file

    sanitizer = _W["sanitizer"]
    sanitizer.mapping.clear()
    used = learn_file(sanitizer, Path(src), encoding, _W["settings"], _W["exclude"], _W["cancel"])
    # (Wert, Kategorie) in der Reihenfolge, in der sie Platzhalter bekamen
    return used, list(sanitizer.mapping._originals.values())


def _write_task(src: str, dest: str | None, encoding: str):
    """Durchlauf 2 für eine Datei. dest=None: nur zählen (--check).
    Rückgabe: (Zähler, Stichproben) oder None, wenn ein neuer Wert auftauchte."""
    from .files import NewValuesFound, process_file, write_file

    sanitizer = _W["sanitizer"]
    before = len(sanitizer.mapping._originals)
    samples: list = []

    def unchanged() -> bool:
        return len(sanitizer.mapping._originals) == before

    try:
        if dest is None:
            counts = process_file(sanitizer, Path(src), encoding, _W["settings"], _W["exclude"], _W["cancel"],
                                  None, samples)
            if not unchanged():
                raise NewValuesFound()
        else:
            counts = write_file(sanitizer, Path(src), Path(dest), encoding, _W["settings"], _W["exclude"],
                                _W["cancel"], samples, accept=unchanged)
    except NewValuesFound:
        # Mapping auf den sauberen Stand zurücksetzen, sonst würden spätere
        # Dateien dieses Workers anders nummeriert
        sanitizer.mapping = pickle.loads(_W["mapping_blob"])
        return None
    return counts, samples


# ----------------------------------------------------------------------
# Im Hauptprozess
# ----------------------------------------------------------------------

def run_tasks(task, jobs: list, workers: int, initargs: tuple, cancel, on_done) -> None:
    """Führt task(*args) für jeden Job (key, args) in einem Prozess-Pool aus und
    ruft on_done(key, future) im Hauptprozess auf, sobald ein Job fertig ist.
    cancel: threading.Event des Laufs; wird es gesetzt, stoppen die Worker."""
    ctx = mp.get_context("spawn")   # wie unter Windows, auch unter Linux (fork + Threads ist unsicher)
    event = ctx.Event()
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(jobs))), mp_context=ctx,
                             initializer=_init_worker, initargs=(*initargs, event)) as pool:
        futures = {pool.submit(task, *args): key for key, args in jobs}
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            if cancel is not None and cancel.is_set() and not event.is_set():
                event.set()
                for f in pending:
                    f.cancel()
            for f in done:
                on_done(futures[f], f)


def mapping_blob(mapping) -> bytes:
    """Mapping für die Worker (ohne zwischengespeicherte Suchmuster)."""
    matchers, mapping._matchers = mapping._matchers, None
    try:
        return pickle.dumps(mapping)
    finally:
        mapping._matchers = matchers
