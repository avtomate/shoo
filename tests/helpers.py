from sexton.procs import Proc

ME = 1000


def make_proc(pid, cmdline, *, ppid=1, uid=ME, state="S", tty_nr=0, age_s=7200.0,
              rss_kb=100_000, comm=None, cgroup="/user.slice/user-1000.slice/session-3.scope"):
    return Proc(
        pid=pid, ppid=ppid, uid=uid, state=state, session=pid, tty_nr=tty_nr,
        starttime=pid * 10, cpu_ticks=0, rss_kb=rss_kb,
        comm=comm or cmdline.split()[0].rsplit("/", 1)[-1][:15],
        cmdline=cmdline, cgroup=cgroup, age_s=age_s,
    )


def table(*procs):
    return {p.pid: p for p in procs}
