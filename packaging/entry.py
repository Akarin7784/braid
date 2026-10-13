import time

# 尽早记下时间点，供 --startup-time 计算冷启动耗时
_T0 = time.perf_counter()

from braid import startup  # noqa: E402

startup.T0 = _T0

from braid.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
