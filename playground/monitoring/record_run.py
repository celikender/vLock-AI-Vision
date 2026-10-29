"""Observe a real monitoring run and save per-frame evidence privately, without changing setup."""
import argparse
import http.client
import json
import time
from pathlib import Path


def get(path):
    connection=http.client.HTTPConnection('127.0.0.1',5051,timeout=10)
    try:
        connection.request('GET',path)
        response=connection.getresponse()
        data=json.loads(response.read(64*1024*1024))
        if response.status!=200:raise RuntimeError('Local monitoring endpoint unavailable.')
        return data
    finally:connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until',choices=['Warning','Normal'],default='Warning')
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--output',default='monitoring_demo.json')
    args=parser.parse_args()
    if Path(args.output).name!=args.output or not args.output.endswith('.json'):
        parser.error('Use a plain JSON filename for the ignored output directory.')
    began=time.monotonic();frames=[];cursor=0;final=None
    try:
        while time.monotonic()-began<args.timeout:
            try:
                data=get(f'/api/monitoring/results?after={cursor}')
                state=get('/api/monitoring/status')
            except (OSError,http.client.HTTPException):
                print('Waiting for the local monitoring endpoint; no state assumed.',flush=True)
                time.sleep(0.5)
                continue
            for row in data['frames']:
                cursor=max(cursor,row['output_id']);frames.append(row)
                print(json.dumps({'prompt':row['prompt'],'frame':row['frame_sequence'],'count':row['count'],
                    'overlaps':[d['overlap_ratio'] for d in row['zone_detections']],
                    'rule_state':row['rule_state'],'stale':row['stale'],'model_loads':row.get('model_loads')}),flush=True)
            final=state
            if final['state']==args.until:
                print(json.dumps({'verified_state':final['state'],'warning_active':final['warning_active'],
                    'frames_recorded':len(frames),'seconds':round(time.monotonic()-began,2)}),flush=True)
                return
            time.sleep(0.5)
        raise TimeoutError('Expected state was not reached: '+(final or {}).get('reason','No result.'))
    finally:
        if final:final={k:v for k,v in final.items() if k!='result'}
        output=Path(__file__).resolve().parents[1]/'outputs'/args.output
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({'source':'live Pi camera and local SAM','status':final,'frames':frames},indent=2),encoding='utf-8')


if __name__=='__main__':main()
