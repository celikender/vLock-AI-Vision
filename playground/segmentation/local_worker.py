"""Loopback-only SAM 3.1 worker. Run in the isolated Linux CUDA environment."""
import os
import time
import tempfile
import threading
from pathlib import Path
from flask import Flask, request, jsonify
from PIL import Image
from masks import prepare, render, SegmentationError

app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=6*1024*1024
lock=threading.Lock()
predictor=None


def checkpoint():
    from huggingface_hub import try_to_load_from_cache
    configured=os.getenv('SAM_CHECKPOINT','')
    if configured and Path(configured).is_file():
        return configured
    path=try_to_load_from_cache('facebook/sam3.1','sam3.1_multiplex.pt')
    return path if isinstance(path,str) and Path(path).is_file() else None


@app.before_request
def local_only():
    if request.host not in ('127.0.0.1:5052','localhost:5052') or request.headers.get('Origin'):
        return jsonify(error='Use the PC application backend.'),403


@app.get('/health')
def health():
    import torch
    return jsonify(ready=bool(checkpoint()) and torch.cuda.is_available(),
                   weights=bool(checkpoint()),cuda=torch.cuda.is_available(),loaded=predictor is not None)


@app.post('/segment')
def segment():
    global predictor
    if not lock.acquire(blocking=False):
        return jsonify(error='Local SAM is busy.'),409
    session_id=None
    try:
        import torch
        began=time.monotonic()
        image=prepare(request.get_data(),request.args.get('prompt',''))
        if not torch.cuda.is_available():
            raise SegmentationError('CUDA GPU unavailable in the local runtime.',503)
        path=checkpoint()
        if not path:
            raise SegmentationError('SAM 3.1 weights missing. Complete Hugging Face access and run the download command.',503)
        torch.cuda.reset_peak_memory_stats()
        if predictor is None:
            from sam3.model_builder import build_sam3_predictor
            predictor=build_sam3_predictor(version='sam3.1',checkpoint_path=path,compile=False,warm_up=False,
                use_fa3=False,use_rope_real=False,max_num_objects=8,multiplex_count=8,async_loading_frames=False)
        with tempfile.TemporaryDirectory(prefix='vision-frame-') as directory:
            image.save(Path(directory)/'00000.jpg','JPEG',quality=92)
            with torch.inference_mode(), torch.autocast('cuda',dtype=torch.bfloat16):
                session_id=predictor.handle_request({'type':'start_session','resource_path':directory,
                    'offload_video_to_cpu':True,'offload_state_to_cpu':True})['session_id']
                try:
                    response=predictor.handle_request({'type':'add_prompt','session_id':session_id,
                        'frame_index':0,'text':request.args['prompt']})
                    arrays=response['outputs']['out_binary_masks']
                    masks=[]
                    for array in arrays:
                        if hasattr(array,'detach'):
                            array=array.detach().cpu().numpy()
                        mask=Image.fromarray((array.squeeze().astype('uint8')*255),'L')
                        masks.append(mask)
                    result={'backend':'local','model':'sam-3.1','count':len(masks),
                        'annotated_image':render(image,masks),'elapsed_seconds':round(time.monotonic()-began,2),
                        'peak_vram_mb':round(torch.cuda.max_memory_allocated()/1024**2),
                        'width':image.width,'height':image.height}
                finally:
                    predictor.handle_request({'type':'close_session','session_id':session_id})
                    session_id=None
        return jsonify(result)
    except SegmentationError as error:
        return jsonify(error=str(error)),error.status
    except Exception as error:
        import torch
        if isinstance(error,torch.cuda.OutOfMemoryError):
            predictor=None
            torch.cuda.empty_cache()
            return jsonify(error='Local GPU ran out of memory. Close GPU apps or switch to Cloud API.'),503
        return jsonify(error='Local SAM failed. Check the worker terminal for runtime compatibility.'),502
    finally:
        lock.release()


if __name__=='__main__':
    app.run(host='127.0.0.1',port=5052,threaded=True,debug=False)