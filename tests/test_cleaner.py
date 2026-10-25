import dataclasses
import subprocess
import sys
import unittest
from unittest import mock

from shoo import cleaner
from shoo.cleaner import clean, still_same
from shoo.procs import read_proc
from shoo.rules import Finding


def spawn(code="import time; time.sleep(60)"):
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
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
            child.wait()
            child.stdout.close()

    def test_stubborn_process_is_killed_after_grace(self):
        code = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)")
        child, proc = spawn(code)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")  # SIGTERM is now ignored
            self.assertEqual(clean([finding(proc)], grace=0.5), {child.pid: "killed"})
            child.wait(timeout=5)
        finally:
            child.kill()
            child.wait()
            child.stdout.close()

    def test_ctrl_c_during_the_grace_period_does_not_escalate(self):
        code = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)")
        child, proc = spawn(code)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with mock.patch("shoo.cleaner.time.sleep", side_effect=KeyboardInterrupt):
                self.assertEqual(clean([finding(proc)], grace=5), {child.pid: "interrupted"})
            self.assertIsNone(child.poll())  # SIGTERM was ignored and no SIGKILL followed
        finally:
            child.kill()
            child.wait()
            child.stdout.close()

    def test_ctrl_c_while_sending_sigterms_still_reports_every_process(self):
        first, proc1 = spawn()
        second, proc2 = spawn()
        real_send, calls = cleaner._send, []

        def interrupt_on_second(proc, sig):
            calls.append(proc.pid)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real_send(proc, sig)

        try:
            with mock.patch.object(cleaner, "_send", interrupt_on_second):
                results = clean([finding(proc1), finding(proc2)], grace=5)
            self.assertEqual(results[second.pid], "not signalled")
            self.assertIn(results[first.pid], {"interrupted", "terminated"})
            self.assertIsNone(second.poll())  # never signalled
        finally:
            for child in (first, second):
                child.kill()
                child.wait()
                child.stdout.close()

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
            child.stdout.close()


if __name__ == "__main__":
    unittest.main()
