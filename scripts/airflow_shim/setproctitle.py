"""Bản rỗng thay `setproctitle`: bản thật làm tiến trình fork của Airflow SIGSEGV trên macOS (D-024)."""


def setproctitle(title: str) -> None:
    pass


def getproctitle() -> str:
    return ""
