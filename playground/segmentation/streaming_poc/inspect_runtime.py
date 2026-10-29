"""Read-only local checkpoint/environment audit for the isolated streaming experiment."""
import importlib.metadata
import json
from pathlib import Path


def main():
    import torch
    from huggingface_hub import try_to_load_from_cache
    report={'packages':{}}
    for name in ('torch','torchvision','transformers','huggingface_hub','sam3','accelerate','safetensors'):
        try:
            report['packages'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report['packages'][name]=None
    report['cuda']=torch.cuda.is_available()
    if report['cuda']:
        report['gpu']=torch.cuda.get_device_name()
        free,total=torch.cuda.mem_get_info()
        report['gpu_memory_mib']={'free':round(free/1024**2),'total':round(total/1024**2)}
    checkpoint=try_to_load_from_cache('facebook/sam3.1','sam3.1_multiplex.pt')
    report['checkpoint_present']=isinstance(checkpoint,str) and Path(checkpoint).is_file()
    if report['checkpoint_present']:
        state=torch.load(checkpoint,map_location='meta',weights_only=True,mmap=True)
        report['checkpoint_top_level']=list(state)[:12]
        if 'model' in state:
            state=state['model']
        report['checkpoint_tensor_count']=len(state)
        report['checkpoint_prefixes']=sorted({k.split('.')[0] for k in state})
        report['multiplex_keys']={k:list(v.shape) for k,v in state.items()
                                  if any(s in k for s in ('multiplex','obj_ptr','maskmem_tpos','occlusion'))}
        report['sample_keys']={k:list(v.shape) for k,v in list(state.items())[:12]}
    if report['packages']['transformers']:
        try:
            from transformers import Sam3VideoModel,Sam3VideoProcessor
            import inspect
            report['streaming_classes_import']=True
            report['session_signature']=str(inspect.signature(Sam3VideoProcessor.init_video_session))
            report['forward_signature']=str(inspect.signature(Sam3VideoModel.forward))
        except Exception as error:
            report['streaming_classes_import']=False
            report['streaming_import_error']=f'{type(error).__name__}: {error}'
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
