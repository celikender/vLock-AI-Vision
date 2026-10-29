"""Explicit local-camera video prompt smoke test; stores private results only on request."""
import argparse
import http.client
import json
import time
from pathlib import Path


def api(method,path,payload=None,port=5053):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
    try:
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'} if payload is not None else {}
        connection.request(method,path,body=json.dumps(payload) if payload is not None else None,headers=headers)
        response=connection.getresponse()
        result=json.loads(response.read(64*1024*1024))
        if response.status!=200:
            raise RuntimeError(result.get('error',str(response.status)))
        return result
    finally:
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address',required=True)
    parser.add_argument('--output',type=Path,help='Optional private JSON output under playground/outputs.')
    args=parser.parse_args()
    if args.output:
        allowed=Path(__file__).resolve().parents[1]/'outputs'
        if not args.output.resolve().is_relative_to(allowed):
            parser.error('--output must be inside ignored playground/outputs')
    if api('GET','/api/status')['busy']:
        raise RuntimeError('Stop the existing experiment before running this smoke test.')
    rows=[]
    began=time.monotonic()
    try:
        started=api('POST','/api/start',{'address':args.address,'prompt':'person','rule':'video_tracking'})
        print(json.dumps({'input':{'prompt':'person','run_id':started['run_id']}}),flush=True)
        cursor=0
        # Two person windows verify cold/warm reuse, followed by an active prompt change.
        for prompt,required in (('person',8),('forklift',4)):
            if prompt=='forklift':
                changed=api('POST','/api/prompt',{'prompt':prompt})
                assert changed['running'] and changed['run_id']==started['run_id']
                print(json.dumps({'input':{'prompt':prompt,'prompt_revision':changed['prompt_revision']}}),flush=True)
            collected=0
            deadline=time.monotonic()+360
            seen=set()
            while collected<required:
                if time.monotonic()>deadline:
                    raise TimeoutError(f'Timed out waiting for {prompt} frames: '+api('GET','/api/status')['reason'])
                result=api('GET',f'/api/video/results?after={cursor}')
                for row in result['frames']:
                    cursor=max(cursor,row['output_id'])
                    if row['prompt']!=prompt:
                        continue
                    identity=(row['session_id'],row['frame_index'])
                    assert identity not in seen
                    seen.add(identity)
                    rows.append(row);collected+=1
                    print(json.dumps({'output':{k:row[k] for k in ('prompt','prompt_revision','session_id','frame_index',
                        'frame_sequence','count','elapsed_seconds','model_loads','peak_vram_mb','stale')},
                        'objects':[{k:v for k,v in obj.items() if k!='mask'} | {
                            'mask_size':obj['mask']['size'],'mask_runs':len(obj['mask']['counts']),
                            'mask_foreground_pixels':sum(obj['mask']['counts'][1::2])} for obj in row['objects']]}),flush=True)
                time.sleep(0.2)
        health=api('GET','/health',port=5052)
        assert len({row['model_loads'] for row in rows})==1
        for session in {row['session_id'] for row in rows}:
            assert {row['frame_index'] for row in rows if row['session_id']==session}=={0,1,2,3}
        print(json.dumps({'verified':{'frames':len(rows),'prompts':['person','forklift'],
            'model_loads':health['model_loads'],'seconds':round(time.monotonic()-began,2)}}),flush=True)
    finally:
        api('POST','/api/stop',{})
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps({'frames':rows},indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
