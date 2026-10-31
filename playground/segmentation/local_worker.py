"""Loopback-only SAM 3.1 worker. Run in the isolated Linux CUDA environment."""
import os
import time
import tempfile
import threading
import json
import logging
from io import BytesIO
from pathlib import Path
from flask import Flask, request, jsonify, Response
from PIL import Image
from masks import prepare, render, SegmentationError
from video_tracking import track_window, validate_prompt, WINDOW_FRAMES, MAX_JPEG_BYTES

app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=9*1024*1024
lock=threading.Lock()
predictor=None
model_loads=0
log=logging.getLogger('sam.video')
GROUNDING_BATCH_SIZE=1


def get_predictor():
    """Called under the same GPU lock by both existing photo and video routes."""
    global predictor, model_loads
    import torch
    if not torch.cuda.is_available():
        raise SegmentationError('CUDA GPU unavailable in the local runtime.',503)
    if predictor is None:
        path=checkpoint()
        if not path:
            raise SegmentationError('SAM 3.1 weights missing. Complete Hugging Face access and run the download command.',503)
        from sam3.model_builder import build_sam3_predictor
        model=build_sam3_predictor(version='sam3.1',checkpoint_path=path,compile=False,warm_up=False,
            use_fa3=False,use_rope_real=False,max_num_objects=8,multiplex_count=16,async_loading_frames=False)
        # Bound grounding activations on the 8 GB GPU. This is a frame batch
        # setting; the checkpoint's trained 16-slot multiplex architecture stays fixed.
        if not hasattr(model.model,'batched_grounding_batch_size'):
            raise RuntimeError('Installed SAM does not expose grounding batch sizing.')
        model.model.batched_grounding_batch_size=GROUNDING_BATCH_SIZE
        predictor=model
        model_loads+=1
        log.info('SAM predictor loaded; model_loads=%s grounding_batch_size=%s',model_loads,GROUNDING_BATCH_SIZE)
    return predictor


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
                   weights=bool(checkpoint()),cuda=torch.cuda.is_available(),loaded=predictor is not None,
                   model_loads=model_loads, video_window_frames=WINDOW_FRAMES)


@app.post('/segment')
def segment():
    global predictor
    if not lock.acquire(blocking=False):
        return jsonify(error='Local SAM is busy.'),409
    session_id=None
    try:
        import torch
        began=time.monotonic()
        if request.content_length and request.content_length>6*1024*1024:
            raise SegmentationError('Photo request is too large.',413)
        image=prepare(request.get_data(),request.args.get('prompt',''))
        get_predictor()
        torch.cuda.reset_peak_memory_stats()
        with tempfile.TemporaryDirectory(prefix='vision-frame-') as directory:
            image.save(Path(directory)/'00000.jpg','JPEG',quality=92)
            with torch.inference_mode(), torch.autocast('cuda',dtype=torch.bfloat16):
                session_id=predictor.handle_request({'type':'start_session','resource_path':directory,
                    'offload_video_to_cpu':True})['session_id']
                try:
                    response=predictor.handle_request({'type':'add_prompt','session_id':session_id,
                        'frame_index':0,'text':request.args['prompt']})
                    arrays=response['outputs']['out_binary_masks']
                    masks=[]
                    detections=[]
                    for array in arrays:
                        if hasattr(array,'detach'):
                            array=array.detach().cpu().numpy()
                        mask=Image.fromarray((array.squeeze().astype('uint8')*255),'L')
                        masks.append(mask)
                        import numpy as np
                        ys,xs=np.nonzero(np.asarray(mask))
                        if len(xs):
                            detections.append({'center':[float(xs.mean()/mask.width),float(ys.mean()/mask.height)],
                                'area':float(len(xs)/(mask.width*mask.height)),
                                'bbox':[float(xs.min()/mask.width),float(ys.min()/mask.height),
                                        float((xs.max()+1)/mask.width),float((ys.max()+1)/mask.height)]})
                    result={'backend':'local','model':'sam-3.1','count':len(masks),
                        'annotated_image':render(image,masks),'elapsed_seconds':round(time.monotonic()-began,2),
                        'peak_vram_mb':round(torch.cuda.max_memory_allocated()/1024**2),
                        'width':image.width,'height':image.height,'detections':detections}
                finally:
                    predictor.handle_request({'type':'close_session','session_id':session_id})
                    session_id=None
        return jsonify(result)
    except SegmentationError as error:
        return jsonify(error=str(error)),error.status
    except Exception as error:
        log.exception('SAM photo inference failed')
        import torch
        if isinstance(error,torch.cuda.OutOfMemoryError):
            predictor=None
            torch.cuda.empty_cache()
            return jsonify(error='Local GPU ran out of memory. Close GPU apps or switch to Cloud API.'),503
        return jsonify(error='Local SAM failed. Check the worker terminal for runtime compatibility.'),502
    finally:
        lock.release()


@app.post('/video/track')
def video_track():
    """Bounded original-JPEG camera window in; one NDJSON row per video frame out."""
    if not lock.acquire(blocking=False):
        return jsonify(error='Local SAM is busy.'),409
    released=False

    def release():
        nonlocal released
        if not released:
            released=True
            lock.release()

    try:
        prompt=validate_prompt(request.form.get('prompt'))
        revision=int(request.form.get('revision','0'))
        metadata=json.loads(request.form.get('frames','null'))
        uploads=request.files.getlist('frame')
        if not isinstance(metadata,list) or not 2<=len(metadata)<=WINDOW_FRAMES or len(uploads)!=len(metadata):
            raise SegmentationError(f'Send 2–{WINDOW_FRAMES} camera frames and matching metadata.',400)
        jpegs=[]
        sizes=[]
        sequences=set()
        for upload,meta in zip(uploads,metadata):
            jpeg=upload.read(MAX_JPEG_BYTES+1)
            if not 0<len(jpeg)<=MAX_JPEG_BYTES or not isinstance(meta,dict):
                raise SegmentationError('Invalid or oversized camera JPEG.',400)
            sequence=meta.get('sequence')
            if not isinstance(sequence,str) or not sequence.isdigit() or sequence in sequences:
                raise SegmentationError('Camera frame sequences must be unique numeric strings.',400)
            sequences.add(sequence)
            # Validate without re-encoding: the model decodes these original JPEG bytes.
            with Image.open(BytesIO(jpeg)) as image:
                if image.format!='JPEG' or image.width*image.height>2_000_000:
                    raise SegmentationError('Use camera JPEGs of at most 2 megapixels.',400)
                image.verify()
                sizes.append(list(image.size))
            meta['size']=sizes[-1]
            jpegs.append(jpeg)
        if any(size!=sizes[0] for size in sizes):
            raise SegmentationError('Camera dimensions changed within the video window.',400)
    except (ValueError,TypeError,OSError,SegmentationError) as error:
        release()
        return jsonify(error=str(error) if isinstance(error,SegmentationError) else 'Invalid camera window.'),getattr(error,'status',400)
    except Exception:
        release()
        raise

    def generate():
        began=time.monotonic()
        stream=None
        try:
            import torch
            model=get_predictor()
            torch.cuda.reset_peak_memory_stats()
            with tempfile.TemporaryDirectory(prefix='vision-video-') as directory:
                for index,jpeg in enumerate(jpegs):
                    (Path(directory)/f'{index:05d}.jpg').write_bytes(jpeg)
                with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                    stream=track_window(model,directory,prompt,revision,metadata)
                    try:
                        for result in stream:
                            result.update(backend='local',model='sam-3.1',model_loads=model_loads,
                                elapsed_seconds=round(time.monotonic()-began,2),
                                peak_vram_mb=round(torch.cuda.max_memory_allocated()/1024**2))
                            yield json.dumps(result,allow_nan=False)+'\n'
                    finally:
                        stream.close()
                        stream=None
        except GeneratorExit:
            raise
        except Exception as error:
            log.exception('SAM video inference failed')
            message=str(error) if isinstance(error,SegmentationError) else 'SAM video failed; see worker traceback.'
            yield json.dumps({'type':'error','error':message,'prompt':prompt,'prompt_revision':revision})+'\n'
        finally:
            release()

    response=Response(generate(),mimetype='application/x-ndjson',headers={'Cache-Control':'no-store'})
    response.call_on_close(release)
    return response


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    app.run(host='127.0.0.1',port=5052,threaded=True,debug=False)
