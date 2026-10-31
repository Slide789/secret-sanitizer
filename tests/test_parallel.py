"""Tests für Ordnerläufe mit mehreren CPU-Kernen (parallel.py).

Wichtigste Eigenschaft: Ein Lauf mit mehreren Kernen liefert byte-genau
dasselbe Ergebnis wie ein Lauf mit einem Kern (gleiche Platzhalter-Nummern).
"""

import hashlib
import pickle
import threading
import unittest
import zipfile
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

from tests.helpers import SECRETS, SecretAssertions, TempDirTestCase, copy_fake_data, make_sanitizer

from secret_sanitizer.core import files as files_mod
from secret_sanitizer.core import parallel
from secret_sanitizer.core.files import REPORT_NAME, FileRun
from secret_sanitizer.core.replacer import PlaceholderMapping

S = SECRETS


def _digest(path: Path) -> str:
    if path.suffix == ".zip":
        # ZIP speichert Zeitstempel; verglichen wird der Inhalt der Einträge
        with zipfile.ZipFile(path) as zf:
            data = b"".join(n.encode() + zf.read(n) for n in sorted(zf.namelist()))
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): _digest(p)
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != REPORT_NAME}


def no_thresholds():
    return mock.patch.multiple(parallel, PARALLEL_MIN_FILES=0, PARALLEL_MIN_BYTES=0)


class ParallelRunTests(SecretAssertions, TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.input = self.tmp / "eingabe"
        copy_fake_data(self.input)
        # weitere Dateien, die Werte aus anderen Dateien wiederverwenden (Konsistenz über Prozesse)
        for i in range(6):
            (self.input / f"extra_{i}.log").write_text(
                f"Verbindung {i} zu {S['hostname']} als {S['email']} mit password=Extra{i}Geheim!\n" * 50,
                encoding="utf-8")
        with zipfile.ZipFile(self.input / "archiv.zip", "w") as zf:
            zf.writestr("innen.log", f"host {S['hostname']} token={S['github']}\n")

    def run_with(self, workers: int, out: str, **kwargs):
        sanitizer = make_sanitizer(workers=workers, **kwargs)
        with no_thresholds():
            report, out_root = FileRun(sanitizer).run(self.input, output_dir=self.tmp / out)
        return report, out_root, sanitizer

    def test_same_result_as_single_core(self):
        for kwargs in ({}, {"sanitize_filenames": True}):
            seq, seq_out, seq_san = self.run_with(1, f"seq{len(kwargs)}", **kwargs)
            par, par_out, par_san = self.run_with(3, f"par{len(kwargs)}", **kwargs)
            self.assertEqual(seq.workers, 1)
            self.assertEqual(par.workers, 3)
            self.assertEqual(tree(seq_out), tree(par_out), kwargs)
            self.assertEqual([(e.rel_path, e.status, e.counts) for e in seq.entries],
                             [(e.rel_path, e.status, e.counts) for e in par.entries])
            self.assertEqual(seq.samples, par.samples)
            self.assertEqual(seq_san.mapping.placeholders(), par_san.mapping.placeholders())
            for path in par_out.rglob("*.log"):
                self.assertNoSecrets(path.read_text(encoding="utf-8"), msg=str(path))

    def test_check_mode_parallel(self):
        sanitizer = make_sanitizer(workers=2)
        with no_thresholds():
            report, out = FileRun(sanitizer).run(self.input, output_dir=self.tmp / "nie", dry_run=True)
        self.assertEqual(report.workers, 2)
        self.assertFalse((self.tmp / "nie").exists())
        self.assertTrue(any(e.counts for e in report.entries if e.rel_path.startswith("extra_")))

    def test_thresholds(self):
        settings = make_sanitizer(workers=4).settings
        self.assertFalse(parallel.should_parallelize(settings, 2, 10**9))
        self.assertFalse(parallel.should_parallelize(settings, 100, 1000))
        self.assertTrue(parallel.should_parallelize(settings, 100, 10**9))
        self.assertFalse(parallel.should_parallelize(make_sanitizer(workers=1).settings, 100, 10**9))
        self.assertGreaterEqual(parallel.worker_count(make_sanitizer().settings), 1)

    def test_cancel_during_parallel_run(self):
        cancel = threading.Event()
        sanitizer = make_sanitizer(workers=2)
        with no_thresholds():
            report, out = FileRun(sanitizer, cancel=cancel, progress=lambda *a: cancel.set()).run(
                self.input, output_dir=self.tmp / "abbruch")
        self.assertTrue(report.aborted)
        self.assertFalse([e for e in report.entries if e.status == "processed"])

    def test_new_value_in_pass_two_falls_back_to_single_core(self):
        # Simuliert einen Worker, der im 2. Durchlauf einen neuen Wert meldet (Ergebnis None)
        def fake_run_tasks(task, jobs, workers, initargs, cancel, on_done):
            if task is parallel._learn_task:
                return real_run_tasks(task, jobs, workers, initargs, cancel, on_done)
            for key, _args in jobs:
                future = Future()
                future.set_result(None)
                on_done(key, future)

        real_run_tasks = parallel.run_tasks
        seq, seq_out, _ = self.run_with(1, "seq")
        sanitizer = make_sanitizer(workers=2)
        with no_thresholds(), mock.patch.object(parallel, "run_tasks", fake_run_tasks):
            report, out = FileRun(sanitizer).run(self.input, output_dir=self.tmp / "fallback")
        self.assertEqual(tree(seq_out), tree(out))
        self.assertEqual([e.counts for e in seq.entries], [e.counts for e in report.entries])


class WorkerTaskTests(TempDirTestCase):
    """Die Worker-Funktionen direkt im Testprozess."""

    def test_write_task_rejects_unknown_values(self):
        src = self.tmp / "a.log"
        src.write_text(f"password={S['db_password']}\n", encoding="utf-8")
        dest = self.tmp / "aus" / "a.log"
        sanitizer = make_sanitizer()
        empty = pickle.dumps(PlaceholderMapping(sanitizer.settings.placeholder_style))
        parallel._init_worker(sanitizer.settings, sanitizer.ruleset, (), empty, threading.Event())
        self.assertIsNone(parallel._write_task(str(src), str(dest), "utf-8"))
        self.assertFalse(dest.exists())
        self.assertFalse(list(dest.parent.glob(".tmp_*")))
        self.assertEqual(len(parallel._W["sanitizer"].mapping), 0)   # sauberer Stand wiederhergestellt

        # Mit vollständigem Mapping: wird geschrieben
        used, values = (lambda r: r)(self._learn(src, sanitizer))
        full = PlaceholderMapping(sanitizer.settings.placeholder_style)
        for value, category in values:
            full.placeholder_for(value, category)
        parallel._init_worker(sanitizer.settings, sanitizer.ruleset, (), pickle.dumps(full), threading.Event())
        counts, samples = parallel._write_task(str(src), str(dest), used)
        self.assertEqual(counts, {"PASSWORD": 1})
        self.assertEqual(dest.read_text(encoding="utf-8"), "password=[PASSWORD_1]\n")

    def _learn(self, src, sanitizer):
        parallel._init_worker(sanitizer.settings, sanitizer.ruleset, (), None, threading.Event())
        return parallel._learn_task(str(src), "utf-8")

    def tearDown(self):
        parallel._W.clear()
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
