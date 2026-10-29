"""Check existing SAM 3.1 tensors against Transformers without allocating model GPU weights."""
import argparse
import hashlib
import importlib.util
import json
from urllib.request import urlopen
from pathlib import Path

CONVERTER_REVISION='144ecf007b8b4f2910da104c84a79801db6985a6'


def compare_tensors(expected, actual):
    missing=sorted(set(expected)-set(actual))
    unexpected=sorted(set(actual)-set(expected))
    mismatched=[{'key':key,'checkpoint':list(actual[key].shape),'expected':list(expected[key].shape)}
                for key in sorted(set(expected)&set(actual)) if actual[key].shape!=expected[key].shape]
    return dict(compatible=not(missing or unexpected or mismatched),missing=missing,
                unexpected=unexpected,shape_mismatches=mismatched)


def load_converter(version, local_only):
    try:
        from transformers.models.sam3_video import convert_sam3_video_to_hf
        return convert_sam3_video_to_hf
    except ImportError:
        # Wheels omit conversion utilities. Pin the official converter separately
        # to its source commit and record that provenance; no checkpoint download.
        directory=Path(__file__).resolve().parents[2]/'outputs'
        provenance=directory/'sam_video_converter_source.json'
        if provenance.is_file():
            info=json.loads(provenance.read_text())
        elif local_only:
            raise RuntimeError('Pinned conversion source is not cached. Run once without --local-only.')
        else:
            info={'revision':CONVERTER_REVISION,'model_package_version':version}
        source=directory/f'sam_video_converter_{info["revision"]}.py'
        if not source.is_file():
            if local_only:
                raise RuntimeError('Pinned conversion source is not cached. Run once without --local-only.')
            url=f'https://raw.githubusercontent.com/huggingface/transformers/{info["revision"]}/src/transformers/models/sam3_video/convert_sam3_video_to_hf.py'
            with urlopen(url,timeout=30) as response:
                content=response.read(200_001)
            if len(content)>200_000:
                raise RuntimeError('Unexpected conversion source size.')
            source.write_bytes(content)
            info['sha256']=hashlib.sha256(content).hexdigest()
            info['url']=url
            provenance.write_text(json.dumps(info,indent=2))
        if hashlib.sha256(source.read_bytes()).hexdigest()!=info['sha256']:
            raise RuntimeError('Cached converter hash does not match its provenance.')
        spec=importlib.util.spec_from_file_location('sam_video_converter',source)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def convert_official(state, converter, torch):
    """The conversion steps shipped with the pinned Transformers SAM3 converter.

    Apply on meta tensors for shape auditing first. Never drop weights to hide a
    mismatch or run inference with missing/randomly initialized parameters.
    """
    mapping=converter.convert_old_keys_to_new_keys(list(state))
    converted={mapping.get(key,key):value for key,value in state.items()}
    key='detector_model.vision_encoder.backbone.embeddings.position_embeddings'
    if key in converted:
        converted[key]=converted[key][:,1:,:]
    source='tracker_model.prompt_encoder.shared_embedding.positional_embedding'
    if source in converted:
        converted['tracker_model.shared_image_embedding.positional_embedding']=converted[source]
    point_keys=[f'tracker_model.prompt_encoder.point_embed.{i}.weight' for i in range(4)]
    if all(key in converted for key in point_keys):
        converted['tracker_model.prompt_encoder.point_embed.weight']=torch.cat(
            [converted.pop(key) for key in point_keys],dim=0)
    converted=converter.split_qkv(converted)
    projection='detector_model.text_encoder.text_projection.weight'
    if projection in converted:
        converted[projection]=converted[projection].T
    return converted


def normalize_roots(state):
    """Adapt container names only; leave every tensor value and shape intact."""
    normalized={}
    for key,value in state.items():
        if key.startswith('detector.'):
            key='sam3_model.'+key[len('detector.'):]
        elif key.startswith('tracker.model.'):
            key='sam2_predictor.model.'+key[len('tracker.model.'):]
        if key in normalized:
            raise ValueError('Checkpoint root normalization caused a key collision.')
        normalized[key]=value
    return normalized


def audit(output, local_only=False):
    import torch
    import transformers
    from huggingface_hub import try_to_load_from_cache, hf_hub_download
    from transformers import Sam3VideoConfig,Sam3VideoModel,Sam3VideoProcessor
    converter=load_converter(transformers.__version__,local_only)
    transformers.utils.logging.set_verbosity_error()
    checkpoint=try_to_load_from_cache('facebook/sam3.1','sam3.1_multiplex.pt')
    if not isinstance(checkpoint,str) or not Path(checkpoint).is_file():
        raise RuntimeError('Existing SAM 3.1 checkpoint was not found in the local cache.')
    config_path=hf_hub_download('facebook/sam3.1','config.json',local_files_only=local_only)
    config=Sam3VideoConfig.from_pretrained(str(Path(config_path).parent),local_files_only=True)
    print('Building expected model tensors on meta device; GPU weights are not allocated.',flush=True)
    with torch.device('meta'):
        model=Sam3VideoModel(config)
    expected=model.state_dict()
    state=torch.load(checkpoint,map_location='meta',weights_only=True,mmap=True)
    if 'model' in state:
        state=state['model']
    converted=convert_official(state,converter,torch)
    official_comparison=compare_tensors(expected,converted)
    normalized=convert_official(normalize_roots(state),converter,torch)
    comparison=compare_tensors(expected,normalized)
    report={'transformers_version':transformers.__version__,'torch_version':torch.__version__,
        'checkpoint_file':Path(checkpoint).name,'checkpoint_bytes':Path(checkpoint).stat().st_size,
        'config_revision':Path(config_path).parent.name,
        'config_sha256':hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        'converter_sha256':hashlib.sha256(Path(converter.__file__).read_bytes()).hexdigest(),
        'original_tensors':len(state),'converted_tensors':len(converted),'expected_tensors':len(expected),
        'raw_format_comparison':compare_tensors(expected,state),'official_conversion_comparison':official_comparison,
        'converted_comparison':comparison,
        'architecture':{'streaming_model':type(model).__name__,
            'streaming_tracker':type(model.tracker_model).__name__,
            'streaming_tracker_config':config.tracker_config.model_type,
            'checkpoint_variant':'SAM 3.1 multiplex',
            'checkpoint_shapes':{k:list(v.shape) for k,v in state.items() if any(s in k for s in (
                'maskmem_tpos_enc','no_obj_embed_spatial','output_valid_embed','output_invalid_embed'))}},
        'gpu':torch.cuda.get_device_name() if torch.cuda.is_available() else None}
    try:
        model.load_state_dict(normalized,strict=True,assign=True)
        report['strict_load']='passed'
    except RuntimeError as error:
        report['strict_load']='failed'
        report['strict_load_error']=str(error)
    # Test the actual processor/session API independently of unusable model weights.
    processor=Sam3VideoProcessor.from_pretrained('facebook/sam3.1',local_files_only=local_only)
    session=processor.init_video_session(inference_device='cuda',processing_device='cpu',
        video_storage_device='cpu',dtype=torch.bfloat16,max_vision_features_cache_size=1)
    session=processor.add_text_prompt(inference_session=session,text='person')
    report['processor_api']={'init_without_video':True,'add_text_prompt':'person',
                             'session_class':type(session).__name__}
    session=processor.add_text_prompt(inference_session=session,text='forklift')
    report['processor_api']['second_prompt']='forklift'
    report['processor_api']['prompt_semantics']='additive; replacement should use a new session'
    report['processor_api']['prompts']=list(session.prompts.values()) if isinstance(session.prompts,dict) else list(session.prompts)
    report['inference_test']={'status':'not_run' if not comparison['compatible'] else 'eligible',
        'reason':'Strict checkpoint validation failed.' if not comparison['compatible'] else None,
        'camera_frames_processed':0,'fps':None,'tracking_continuity':None,
        'end_to_end_latency_ms':None,'inference_gpu_memory_mib':None,'gpu_utilization_percent':None}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'strict_load':report['strict_load'],
        'missing_tensors':len(comparison['missing']),'unexpected_tensors':len(comparison['unexpected']),
        'shape_mismatch_count':len(comparison['shape_mismatches']),
        'shape_mismatches':comparison['shape_mismatches'][:15],
        'missing_examples':comparison['missing'][:12],
        'unexpected_examples':comparison['unexpected'][:12],
        'processor_api':report['processor_api'],'report':str(output)},indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only',action='store_true')
    args=parser.parse_args()
    output=Path(__file__).resolve().parents[2]/'outputs'/'streaming_compatibility.json'
    report=audit(output,args.local_only)
    raise SystemExit(0 if report['converted_comparison']['compatible'] else 2)


if __name__=='__main__':
    main()
