"""Bounded, ephemeral calculation process; no persistent inputs or result cache."""
from datetime import datetime, timezone
import multiprocessing
import queue
import threading
import time
import uuid

from decision_core.contracts import RunStatus, ResultMetadata, StorageOutput
from decision_core.storage_calculation import (StorageCalculation, ActionAdvice, calculate_storage,
                                               validated_request)

WALL_TIME_SECONDS = 20
_GATE = threading.BoundedSemaphore(2)


def _failure(request, run_id, at, status, message, code):
    metadata = ResultMetadata("storage", request.input_sha256, status, run_id, at)
    return StorageCalculation(StorageOutput(metadata), (), (),
                              ActionAdvice(False, "暂不能给出动作建议", None, (message,), (code,)))


def _worker(connection, request, run_id, at):
    try:
        from .highs_adapter import highs_backend
        connection.send(calculate_storage(request, highs_backend, run_id=run_id, computed_at_utc=at))
    except Exception:
        connection.send(_failure(request, run_id, at, RunStatus.SOLVER_ERROR,
                                 "本次计算未完成；没有返回零收益或旧研究结果，请检查条件后重试。", "WORKER_FAILED"))
    finally:
        connection.close()


def _isolated(request, run_id, at, *, worker=_worker, wall_time=WALL_TIME_SECONDS):
    """Internal test seam; callers never choose process targets or solver options."""
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(send, request, run_id, at), daemon=True)
    inbox = queue.Queue(maxsize=1)
    reader = None
    started = time.monotonic()
    def receive_complete_message():
        try:
            inbox.put((True,receive.recv()))
        except Exception:
            inbox.put((False,None))
    try:
        process.start()
        send.close()
        # A readable pipe can contain only a frame header, not a complete message.
        # Deadline guards the full receive/unpickle, not merely poll readiness.
        reader = threading.Thread(target=receive_complete_message, daemon=True)
        reader.start()
        try:
            valid,result = inbox.get(timeout=max(0,wall_time-(time.monotonic()-started)))
        except queue.Empty:
            return _failure(request, run_id, at, RunStatus.TIME_LIMIT,
                            "本次计算超过20秒预算，已停止计算；没有动作建议，也不是零收益。", "WALL_TIME_LIMIT")
        if not valid or not isinstance(result, StorageCalculation) or result.output.metadata.input_sha256 != request.input_sha256:
            return _failure(request, run_id, at, RunStatus.SOLVER_ERROR,
                            "本次结果与输入不一致，不能作为建议。", "WORKER_RESULT_MISMATCH")
        return result
    except Exception:
        return _failure(request, run_id, at, RunStatus.SOLVER_ERROR,
                        "计算进程未返回有效结果，请稍后重试。", "PROCESS_FAILED")
    finally:
        send.close()
        if process.pid is not None:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.5)
            process.close()
        if reader is not None:
            reader.join(timeout=0.1)
        receive.close()


def run_storage(request):
    """Public Python entry: same normalized request for quick and advanced modes."""
    request = validated_request(request)
    run_id, at = str(uuid.uuid4()), datetime.now(timezone.utc)
    if not _GATE.acquire(blocking=False):
        return _failure(request, run_id, at, RunStatus.BUSY,
                        "当前同时测算的人较多，请稍后点击重试；研究回放不受影响。", "COMPUTE_BUSY")
    try:
        return _isolated(request, run_id, at)
    finally:
        _GATE.release()
