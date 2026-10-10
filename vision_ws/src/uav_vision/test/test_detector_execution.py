import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from uav_vision.detector_execution import (
    LatestImageWorker, native_fp16_shape, prepare_native_fp16,
)


class ExecutionTest(unittest.TestCase):
    def attr(self, **updates):
        values = dict(type=1, fmt=1, n_dims=4, dims=[1,640,640,3],
                      size=2457600, w_stride=640, h_stride=0,
                      stride_with_stride=2457600)
        values.update(updates)
        return SimpleNamespace(**values)

    def runtime(self, attr):
        return SimpleNamespace(rknn_runtime=SimpleNamespace(get_tensor_attr=lambda _:attr))

    def test_native_contract_and_fallback(self):
        self.assertEqual(native_fp16_shape(self.runtime(self.attr())), (1,640,640,3))
        for update in [dict(type=0),dict(fmt=0),dict(w_stride=656),dict(h_stride=656),
                       dict(stride_with_stride=2500000),dict(size=4915200)]:
            self.assertIsNone(native_fp16_shape(self.runtime(self.attr(**update))))
        self.assertIsNone(native_fp16_shape(object()))

    def test_native_conversion_preserves_all_normalized_byte_values(self):
        x=np.arange(256,dtype=np.uint8).reshape(1,16,16,1)
        x=np.repeat(x,3,axis=3).astype(np.float32);x/=255.0
        actual=prepare_native_fp16(x,x.shape)
        np.testing.assert_array_equal(actual.view(np.uint16),x.astype(np.float16).view(np.uint16))
        self.assertTrue(actual.flags.c_contiguous)
        self.assertIsNone(prepare_native_fp16(x,None))
        self.assertIsNone(prepare_native_fp16(x.astype(np.uint8),x.shape))

    def test_pending_images_are_replaced_and_epochs_preserved(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event();seen=[];errors=[]
        def consume(image, epoch):
            seen.append((image,epoch))
            if image=='first': entered.set();release.wait(3)
            else: finished.set()
        worker=LatestImageWorker(consume,errors.append)
        try:
            worker.submit('first',0);self.assertTrue(entered.wait(3))
            worker.submit('old',1);worker.submit('newest',2);release.set()
            self.assertTrue(finished.wait(3))
            self.assertEqual(seen,[('first',0),('newest',2)]);self.assertEqual(errors,[])
        finally:release.set();worker.close();worker._thread.join(3)
        self.assertFalse(worker._thread.is_alive())

    def test_shutdown_discards_pending_image(self):
        entered=threading.Event();release=threading.Event();seen=[]
        def consume(image, epoch):seen.append(image);entered.set();release.wait(3)
        worker=LatestImageWorker(consume,lambda e:None)
        worker.submit('first',0);self.assertTrue(entered.wait(3))
        worker.submit('pending',0);worker.close();worker.submit('after_close',0)
        release.set();worker._thread.join(3)
        self.assertEqual(seen,['first']);self.assertFalse(worker._thread.is_alive())

    def test_worker_error_is_reported_and_stops(self):
        failed=threading.Event();errors=[]
        def consume(image, epoch):raise ValueError('bad output')
        def report(exc):errors.append(exc);failed.set()
        worker=LatestImageWorker(consume,report);worker.submit('bad',0)
        self.assertTrue(failed.wait(3));worker._thread.join(3)
        self.assertIsInstance(errors[0],ValueError);self.assertFalse(worker._thread.is_alive())

    def test_detector_rejects_queued_image_from_previous_stage(self):
        root=Path('/home/orangepi/liftrace_board_trials_20260928')
        spec=importlib.util.spec_from_file_location('detector_under_test',
            str(root/'vision_ws/src/uav_vision/scripts/target_detector_rknn.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        detector=module.TargetDetectorRKNN.__new__(module.TargetDetectorRKNN)
        detector._stage_gate=SimpleNamespace(begin=lambda:2,current=lambda epoch:epoch==2)
        # No bridge/runtime is initialized: touching either would fail this test.
        detector._on_image(object(),1)


if __name__=='__main__': unittest.main()
