"""Small process-pool helper shared by the CPU-bound fan-out sites.

The codec's entropy coder and the ground decoder are pure-Python / GIL-bound, so per-band work is
dispatched to worker processes. A ``spawn`` context is used deliberately: forking from a
multi-threaded parent is deprecated (Python 3.12+) and deadlock-prone.
"""

from __future__ import annotations

from typing import Any, Callable


def run_in_process_pool(
    tasks: dict[Any, tuple[Callable[..., Any], tuple]], jobs: int
) -> dict[Any, Any]:
    """Run ``{key: (fn, args)}`` across a spawn-context process pool, returning ``{key: result}``.

    The callables must be importable at module scope so they survive pickling into the workers.
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as pool:
        futures = {key: pool.submit(fn, *args) for key, (fn, args) in tasks.items()}
        return {key: fut.result() for key, fut in futures.items()}
