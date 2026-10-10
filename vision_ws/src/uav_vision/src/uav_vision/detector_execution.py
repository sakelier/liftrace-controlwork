"""Execution helpers for the RKNN detector; no mission or selection policy."""
import os
from pathlib import Path
import threading

import cv2
import numpy as np


def prefer_big_cpus():
    """Restrict this thread (and subsequently created threads) to allowed big CPUs."""
    allowed = os.sched_getaffinity(0)
    capacities = {}
    for cpu in allowed:
        path = Path('/sys/devices/system/cpu/cpu%d/cpu_capacity' % cpu)
        if not path.is_file():
            return None  # Do not guess CPU numbering on other boards.
        capacities[cpu] = int(path.read_text().strip())
    peak = max(capacities.values())
    big = {cpu for cpu, capacity in capacities.items() if capacity == peak}
    os.sched_setaffinity(0, big)
    return sorted(big)


def native_fp16_shape(runtime):
    """Accept only unpacked, unpadded NHWC FP16 input from the actual model."""
    try:
        attr = runtime.rknn_runtime.get_tensor_attr(0)
        shape = tuple(int(attr.dims[i]) for i in range(attr.n_dims))
        # RKNN tensor enums: FLOAT16=1, NHWC=1.
        if attr.type != 1 or attr.fmt != 1 or len(shape) != 4 or shape[0] != 1:
            return None
        if shape[3] != 3 or attr.size != int(np.prod(shape)) * 2:
            return None
        if attr.w_stride not in (0, shape[2]) or attr.h_stride not in (0, shape[1]):
            return None
        if attr.stride_with_stride not in (0, attr.size):
            return None
        if not hasattr(cv2, 'convertFp16'):
            return None
        return shape
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None


def prepare_native_fp16(tensor, shape):
    """Convert already normalized FP32 values without changing their scale/layout."""
    if shape is None or tensor.shape != shape or tensor.dtype != np.float32:
        return None
    # OpenCV uses SIMD and stores IEEE FP16 bits in a CV_16S array.
    return cv2.convertFp16(tensor[0]).view(np.float16)[None, ...]


class LatestImageWorker:
    """One inference owner and at most one pending image; replace older pending work."""
    def __init__(self, callback, on_error):
        self._callback = callback
        self._on_error = on_error
        self._condition = threading.Condition()
        self._pending = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='rknn_inference')
        self._thread.daemon = True
        self._thread.start()

    def submit(self, image, epoch):
        with self._condition:
            if not self._closed:
                self._pending = (image, epoch)
                self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                image, epoch = self._pending
                self._pending = None
            try:
                self._callback(image, epoch)
            except Exception as exc:
                self.close()
                self._on_error(exc)
                return
