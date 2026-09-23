"""Boot/cursor-scoped kernel guard for production validation; no GPU probes."""
import re
import threading
import time

GPU_ERROR = re.compile(r'(?:amdgpu|\bMES\b|\bring\b).*(?:\bfailed\b|\bfull\b|\breset\b|\btimeout\b|\btimed out\b|\bhang\b)', re.I)


class KernelGuard:
    def __init__(self, run, contain, evidence):
        self.run, self.contain, self.evidence = run, contain, evidence
        self.stop = threading.Event()
        self.blocked = threading.Event()
        self.cursor = None
        self.thread = None

    def sample(self):
        args = ['journalctl', '-k', '-b', '--no-pager', '--show-cursor', '-o', 'cat']
        args += ['--after-cursor', self.cursor] if self.cursor else ['-n', '0']
        result = self.run(args)
        lines = result.splitlines()
        cursors = [line.removeprefix('-- cursor: ') for line in lines if line.startswith('-- cursor: ')]
        if not cursors:
            raise RuntimeError('kernel cursor unavailable')
        self.cursor = cursors[-1]
        errors = [line for line in lines if GPU_ERROR.search(line)]
        if errors:
            self.evidence.write_text('\n'.join(errors) + '\n')
            raise RuntimeError('new GPU kernel fault')

    def check(self):
        if self.blocked.is_set():
            raise RuntimeError('GPU validation blocked; ingress paused')

    def __enter__(self):
        self.sample()
        self.evidence.with_suffix('.cursor').write_text(self.cursor + '\n')
        def watch():
            while not self.stop.wait(1):
                try:
                    self.sample()
                except Exception:
                    self.blocked.set()
                    self.contain()
                    return
        self.thread = threading.Thread(target=watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=30)
        self.check()
        try:
            self.sample()
        except Exception:
            self.blocked.set()
            self.contain()
            raise
        self.evidence.with_suffix('.verified').write_text(f'No new GPU errors through cursor {self.cursor}\n')
