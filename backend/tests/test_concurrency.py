"""Two tills in one store must never get the same invoice number."""
import subprocess
import sys
import unittest
from pathlib import Path

from pos.domain.invoice_series import InvoiceSeriesManager
from pos.domain.till import TillSessionManager
from pos.domain.money import Money
from tests.helpers import tmpdir

ROOT = Path(__file__).resolve().parent.parent
WORKER = (
    "import sys;"
    "from pos.domain.invoice_series import InvoiceSeriesManager;"
    "m=InvoiceSeriesManager(sys.argv[1]);"
    "print(' '.join(m.next_invoice_number('HSR') for _ in range(int(sys.argv[2]))))"
)


class TestConcurrentTills(unittest.TestCase):
    def setUp(self):
        self._d, self.tmp = tmpdir()
        self.addCleanup(self._d.cleanup)

    def test_parallel_processes_get_unique_gapless_numbers(self):
        f = str(self.tmp / "series.json")
        procs = [
            subprocess.Popen([sys.executable, "-c", WORKER, f, "15"], cwd=ROOT,
                             stdout=subprocess.PIPE, text=True)
            for _ in range(4)
        ]
        issued = []
        for p in procs:
            out, _ = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0)
            issued += out.split()
        self.assertEqual(len(issued), 60)
        self.assertEqual(len(set(issued)), 60, "duplicate invoice numbers were issued")
        self.assertEqual(sorted(issued), [f"ELU/HSR/FY26/{i:05d}" for i in range(1, 61)])
        recorded = [r["invoice_no"] for r in InvoiceSeriesManager(f).data["HSR"]["invoices"]]
        self.assertEqual(len(recorded), 60)

    def test_lock_file_is_released(self):
        f = self.tmp / "series.json"
        InvoiceSeriesManager(f).next_invoice_number("HSR")
        self.assertFalse(Path(str(f) + ".lock").exists())

    def test_stale_lock_from_a_crashed_process_is_taken_over(self):
        import os, time
        f = self.tmp / "till.json"
        lock = Path(str(f) + ".lock")
        lock.write_text("")
        old = time.time() - 60
        os.utime(lock, (old, old))
        t = TillSessionManager(f)
        t.open_session("HSR", 1, "S108", Money(1000), "T1")
        self.assertIsNotNone(t.get_session("T1"))


if __name__ == "__main__":
    unittest.main()
