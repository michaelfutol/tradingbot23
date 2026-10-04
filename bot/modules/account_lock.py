"""One portfolio writer per data directory, across GUI/CLI/API processes."""

import os


class AccountLock:
    def __init__(self, data_dir):
        self.path = data_dir / ".paper-owner.lock"
        self.file = None

    def __enter__(self):
        self.file = self.path.open("a+b")
        if self.file.seek(0, os.SEEK_END) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError("This paper account is already running. Use the LUM bridge to control its owner.") from None
        return self

    def __exit__(self, *_args):
        if self.file is not None:
            self.file.close()
            self.file = None
