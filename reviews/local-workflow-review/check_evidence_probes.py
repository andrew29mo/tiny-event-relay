"""Audit-only tampered-copy probes. These are not service benchmarks or VM fault injection."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.check_local import check_local
from tools.platform_io import save,sha
from tools.benchmark import summarize,aggregate,render


def main():
    source=Path('reviews/local-validation-reviewed')
    check_local(source)
    cases=('missing-test','timeout-zero-exit','missing-driver','nonzero-container-exit','oom',
           'leftover-container','vm-still-running','network-enabled','different-arrival-schedule','changed-overview')
    outcomes=[]
    for case in cases:
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'evidence'
            shutil.copytree(source,target)
            r=json.loads((target/'combined.json').read_text())
            def change_log(name,text):
                p=target/(name+'.txt'); p.write_text(text)
                r['operations'][name]['log_sha256']=sha(p)
            if case=='missing-test':
                p=target/'linux/tests/tests.json'; d=json.loads(p.read_text());d['successes'].pop();save(p,d)
            elif case=='timeout-zero-exit':
                r['operations']['linux-driver'].update(status='timeout',exit_code=0)
            elif case=='missing-driver':
                del r['operations']['linux-driver']
            elif case in ('nonzero-container-exit','oom'):
                k,v=('ExitCode',7) if case=='nonzero-container-exit' else ('OOMKilled',True)
                r['container_exit'][k]=v
                d=json.loads((target/'container-exit.txt').read_text());d[0]['State'][k]=v
                change_log('container-exit',json.dumps(d))
            elif case=='leftover-container':
                change_log('cleanup-remaining','owned-container\n')
            elif case=='vm-still-running':
                change_log('final-vm-state',json.dumps({'name':'relay','status':'Running'})+'\n')
            elif case=='network-enabled':
                d=json.loads((target/'linux-runtime.json').read_text());d['container']['NetworkMode']='bridge'
                save(target/'linux-runtime.json',d);r['linux_runtime_sha256']=sha(target/'linux-runtime.json')
                d=json.loads((target/'container-info.txt').read_text());d[0]['HostConfig']['NetworkMode']='bridge'
                change_log('container-info',json.dumps(d))
            elif case=='different-arrival-schedule':
                p=target/'linux/benchmark/report.json';d=json.loads(p.read_text());d['parameters']['rate']=16
                for t in d['trials']:
                    t['rate_per_s']=16
                    for i,row in enumerate(t['records']):row['scheduled_s']=i/16
                    t['summary']=summarize(t)
                d['aggregate']=aggregate(d);save(p,d)
                (p.parent/'report.html').write_text(render(d))
            elif case=='changed-overview':
                with (target/'report.html').open('a') as f:f.write('changed')
            save(target/'combined.json',r)
            try:
                check_local(target)
            except ValueError as error:
                outcomes.append({'case':case,'rejected':True,'reason':str(error)})
            else:
                raise AssertionError('tampered evidence passed: '+case)
    result={'snapshot_sha256':json.loads((source/'combined.json').read_text())['snapshot_sha256'],
            'passed':True,'scope':'tampered evidence copies, not VM failures','cases':outcomes}
    save(Path(__file__).with_name('checker-probes.json'),result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
