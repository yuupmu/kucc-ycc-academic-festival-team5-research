"""Static syntax checks for declared project files. No submitted program or test is run."""
import json
import os
import shutil
import subprocess
from pathlib import PurePosixPath


def check(name,text):
    suffix=PurePosixPath(name).suffix.lower()
    if suffix in ('.py','.pyw'):
        try:
            compile(text,name,'exec',dont_inherit=True)
        except (SyntaxError,ValueError,OverflowError):
            return 'invalid'
        return 'valid'
    if suffix=='.json':
        try:
            json.loads(text)
        except (ValueError,RecursionError):
            return 'invalid'
        return 'valid'
    if suffix in ('.js','.mjs','.cjs'):
        node=shutil.which('node')
        if not node:
            return 'unavailable'
        modes={'.mjs':['module'],'.cjs':['commonjs'],'.js':['module','commonjs']}[suffix]
        for mode in modes:
            try:
                process=subprocess.run([node,'--input-type='+mode,'--check','-'],input=text,text=True,
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=6,
                                       env={'PATH':os.defpath})
            except (OSError,subprocess.TimeoutExpired):
                return 'unavailable'
            if process.returncode==0:
                return 'valid'
        return 'invalid'
    return 'unavailable'


def restore_identical_lines(source,edit):
    """Only restore indentation on lines whose non-indentation text was already identical."""
    original=source.splitlines()[edit['first']-1:edit['last']]
    replacement=edit['text'].splitlines(keepends=True)
    if len(original)!=len(replacement):
        return edit
    restored=[]
    for old,new in zip(original,replacement):
        line=new.rstrip('\r\n')
        if line.strip() and old.lstrip(' \t')==line.lstrip(' \t') and old!=line:
            new=old+new[len(line):]
        restored.append(new)
    return {**edit,'text':''.join(restored)}


def transaction(files,edits,evidence,apply):
    candidate=apply(files,edits,evidence)
    before={name:check(name,text) for name,text in files.items()}
    after={name:(before[name] if text==files[name] else check(name,text)) for name,text in candidate.items()}
    broken={name for name,status in after.items() if status=='invalid' and candidate[name]!=files[name]}
    adjusted=[restore_identical_lines(files[e['file']],e) if e['file'] in broken else e for e in edits]
    restored=[]
    if adjusted!=edits:
        alternative=apply(files,adjusted,evidence)
        for name in broken:
            if alternative[name]!=candidate[name] and check(name,alternative[name])=='valid':
                candidate[name]=alternative[name]
                after[name]='valid'
                restored.append(name)
    effective=[new if old['file'] in restored else old for old,new in zip(edits,adjusted)]
    rejected=[name for name in broken if after[name]=='invalid' and (before[name]=='valid' or not files[name].strip())]
    receipt=dict(before=before,proposed_invalid=sorted(broken),restored_indent=sorted(restored),rejected=sorted(rejected),
                 verified=before if rejected else after)
    if rejected:
        return files,[],receipt,'구문이 유효했던 파일을 깨뜨리는 편집을 보류함'
    return candidate,effective,receipt,None
