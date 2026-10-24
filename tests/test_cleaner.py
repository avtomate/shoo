import dataclasses
import subprocess
import sys
import unittest

from shoo.procs import read_proc
from shoo.cleaner import clean, still_same
from shoo.rules import Finding


def spawn(code="import time; time.sleep(60)"):
    child = subprocess.Popen([sys.executable, "-c", code])
    return child, read_proc(child.pid)


def finding(proc):
    return Finding(proc, "test", ())


class RealProcesses(unittest.TestCase):
    def test_polite_process_is_terminated(self):
        child, proc = spawn()
        try:
            self.assertEqual(clean([finding(proc)], grace=3), {child.pid: "terminated"})
            child.wait(timeout=5)  # collect it so it isn't left as a zombie
        finally:
            child.kill()

    def test_stubborn_process_is_killed_after_grace(self):
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        child, proc = spawn(code)
        try:
            # give the child a moment to install its handler
            while True:
                if read_proc(child.pid).cmdline.endswith(code):
                    break
            import time; time.sleep(0.5)
            self.assertEqual(clean([finding(proc)], grace=0.5), {child.pid: "killed"})
            child.wait(timeout=5)
        finally:
            child.kill()

    def test_refuses_to_signal_a_recycled_pid(self):
        child, proc = spawn()
        try:
            stale = dataclasses.replace(proc, starttime=proc.starttime + 1)
            self.assertFalse(still_same(stale))
            self.assertEqual(clean([finding(stale)], grace=0.2), {child.pid: "gone"})
            self.assertIsNone(child.poll())  # still running: we never signalled it
        finally:
            child.kill()
            child.wait()


if __name__ == "__main__":
    unittest.main()
