"""wait_until(cond, seconds): what the tests wait on (a run, a thread, a child process), in a Qt event loop that a
10 ms timer checks cond() from, not in sleeps between processEvents() calls (R-C8: up to 180 s of 20 ms sleeps)."""


def wait_until(cond, seconds):
    """Run the event loop until cond() holds or `seconds` pass; cond()'s value then."""
    from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer
    if cond():
        return True
    loop, clock, timer = QEventLoop(), QElapsedTimer(), QTimer()
    clock.start()

    def check():
        if cond() or clock.elapsed() > seconds * 1000:
            loop.quit()
    timer.setInterval(10)
    timer.timeout.connect(check)
    timer.start()
    loop.exec()
    timer.stop()
    return bool(cond())
