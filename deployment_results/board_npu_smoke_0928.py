
import sys,pathlib,json,time
import cv2,numpy as np
root=pathlib.Path('/home/orangepi/liftrace_board_trials_20260928')
sys.path.insert(0,str(root/'vision_ws/src/uav_vision/scripts'))
import target_detector_rknn as d
r=d.RKNNLite()
try:
    assert r.load_rknn(str(root/'runtime_models/flight_5cls_20260928_fp16.rknn'))==0
    assert r.init_runtime()==0
    meta=d._load_metadata(str(root/'runtime_models/flight_5cls_20260928_metadata.yaml'))
    img=cv2.imread(str(root/'deployment_results/smoke_frame.jpg'))
    assert img is not None
    inp,scale,pad,_=d._to_model_input(img,640)
    ms=[]
    for i in range(4):
        start=time.monotonic();out=r.inference(inputs=[inp]);ms.append((time.monotonic()-start)*1000)
        d._validate_output_contract(out,meta)
        assert all(np.isfinite(v).all() for v in out)
    det=d._decode_outputs(out,5,.5,640,img.shape,scale,pad,box_format='xywh')
    result=dict(status='PASS',kind='offline_frame_no_ROS_nodes',shapes=[list(v.shape) for v in out],names=meta['names'],inference_ms=ms,detections=[dict(name=meta['names'][v['class_id']],score=v['score']) for v in det])
    (root/'deployment_results/npu_smoke.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
finally:r.release()
