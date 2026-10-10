
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
    result=[]
    for p in sorted((root/'deployment_results').glob('frame_*.jpg')):
        img=cv2.imread(str(p));inp,scale,pad,_=d._to_model_input(img,640)
        start=time.monotonic();out=r.inference(inputs=[inp]);ms=(time.monotonic()-start)*1000
        d._validate_output_contract(out,meta)
        det=d._decode_outputs(out,5,.5,640,img.shape,scale,pad,box_format='xywh')
        result.append(dict(frame=p.name,inference_ms=ms,detections=[dict(name=meta['names'][v['class_id']],score=v['score']) for v in det]))
    (root/'deployment_results/npu_positive_frames.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
finally:r.release()
