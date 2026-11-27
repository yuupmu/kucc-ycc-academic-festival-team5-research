import sys,time,shutil,json
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]))
from experiments import scoped_transfer as base, scoped_transfer_confirm as confirm
from experiments.project_review import freeze,publish
from experiments.local_transport import local_server,read
from hashlib import sha256

tasks=['title','suffix','mask','upload','print']
arms=['solo','self','abc','abc-confirmed']
freeze(root/'protocol.json',dict(tasks=tasks,arms=arms,model=base.MODEL,seed=263,cycles=3,questions_per_arm_cycle=3,
    responders='Codex chooses only requested facts from the registered operator cards',
    invalid_confirmation='retain sealed ABC, record failed calls',grading='after all 20 submissions sealed'))
print_dir=root/'print'
if not print_dir.exists():
    print_dir.mkdir()
    shutil.copytree(Path('var/transfer-print-fixed-evidence-v1/calls'),print_dir/'calls')
with local_server(18831,base.MODEL):
    while not all((root/t/'sealed-confirmation.json').exists() for t in tasks):
        for t in tasks:
            d=root/t
            if (d/'sealed-confirmation.json').exists():continue
            waiting=[f for f in d.glob('*-questions.json') if read(f) and not f.with_name(f.name.replace('questions','reply')).exists()]
            if waiting:continue
            if not (d/'sealed.json').exists():
                print('Running',t,flush=True);base.run(t,d,18831)
            if (d/'sealed.json').exists():
                calls=read(d/'abc.json')['calls'].copy()
                real_call=confirm.call_model
                def tracked(*args,**kwargs):
                    key, result=real_call(*args,**kwargs)
                    calls.append(key)
                    return key,result
                confirm.call_model=tracked
                try:
                    confirm.run(d,18831)
                except (ValueError,StopIteration) as exc:
                    if not (isinstance(exc,(json.JSONDecodeError,StopIteration)) or
                            str(exc).startswith(('Invalid model response ', 'No owner evidence'))):
                        raise
                    reason=type(exc).__name__+' '+str(exc)
                    code=(d/'submissions/abc/solution.py').read_text()
                    publish(d,'abc-confirmed',{'solution.py':code})
                    freeze(d/'abc-confirmed.json',dict(calls=calls,confirmed=False,probes=[],diagnostics=[reason]))
                    hashes=read(d/'sealed.json')
                    freeze(d/'sealed-confirmation.json',{**hashes,'abc-confirmed':hashes['abc']})
                    print('Retained unconfirmed ABC',t,reason,flush=True)
                finally:
                    confirm.call_model=real_call
        time.sleep(1)
sealed={t:read(root/t/'sealed-confirmation.json') for t in tasks}
assert all(set(v)==set(arms) for v in sealed.values())
freeze(root/'sealed-all.json',sealed)
print('All submissions sealed',flush=True)
