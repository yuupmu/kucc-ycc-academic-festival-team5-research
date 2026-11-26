import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import project_review as core, project_syntax
from experiments import project_review as runner
from experiments.local_transport import request_body
from experiments.monitor_cycles import locked_output, read, save


class ProjectReviewTests(unittest.TestCase):
    def test_disjoint_ranges_are_atomic_and_preserve_unedited_files_and_newlines(self):
        files={'a.js':'one\r\ntwo\r\nthree','doc.txt':'','copy.txt':' untouched \n'}
        evidence={'A1.1':'Use the alternative spelling.'}
        def change(name,first,last,text):
            return dict(file=name,first=first,last=last,text=text,sources=['A1.1'])
        edits=[change('a.js',4,3,'four'),change('doc.txt',1,0,'note'),change('a.js',1,1,'first')]
        self.assertEqual(core.apply_edits(files,edits,evidence),
                         {'a.js':'first\r\ntwo\r\nthree\r\nfour','doc.txt':'note','copy.txt':' untouched \n'})
        for invalid in (change('a.js',1,2,'ambiguous'),change('a.js',7,7,'outside'),
                        {**edits[1],'sources':['unseen']},change('other.txt',1,0,'other')):
            with self.assertRaises(ValueError):
                core.apply_edits(files,[*edits,invalid],evidence)
            self.assertEqual(files['a.js'],'one\r\ntwo\r\nthree')

    def test_only_public_manifest_keys_and_natural_answers_are_accepted(self):
        public=dict(brief='Use documented rules.',files={'src/a.ts':'','readme.txt':''})
        core.validate_project(public)
        for invalid in ({**public,'expected':True},{**public,'files':{'../private':''}},
                        {**public,'files':{'src':'a','src/a.ts':'b'}},{**public,'files':{}}):
            with self.assertRaises(ValueError):
                core.validate_project(invalid)
        self.assertEqual(core.natural_reply('합산 점수가 같으면 두 항목을 모두 표시합니다.'),'합산 점수가 같으면 두 항목을 모두 표시합니다.')
        for transcript in ('점수: 31/40','score: 25/40','{"results": []}','assert f(1) == 7'):
            with self.assertRaises(ValueError):
                core.natural_reply(transcript)

    def test_syntax_guard_restores_only_existing_whitespace_and_preserves_the_transaction(self):
        files={'src/sample.py':'def greet(s):\n    return s.upper()\n','guide.txt':'before\n'}
        refs={'P1':'Display in uppercase.'}
        edit=dict(file='src/sample.py',first=2,last=2,sources=['P1'],text='return s.upper()')
        note=dict(file='guide.txt',first=1,last=1,sources=['P1'],text='after')
        result,effective,receipt,error=project_syntax.transaction(files,[edit,note],refs,core.apply_edits)
        self.assertIsNone(error)
        self.assertEqual(receipt['restored_indent'],['src/sample.py'])
        self.assertEqual(result,{'src/sample.py':files['src/sample.py'],'guide.txt':'after\n'})
        self.assertEqual(effective[0]['text'],'    return s.upper()')
        result,effective,receipt,error=project_syntax.transaction(files,[{**edit,'text':'return ('},note],refs,core.apply_edits)
        self.assertTrue(error)
        self.assertEqual((result,effective),(files,[]))
        self.assertEqual(receipt['rejected'],['src/sample.py'])
        self.assertEqual(project_syntax.check('values.json','{"key": '),'invalid')
        self.assertEqual(project_syntax.check('guide.md','not a program'),'unavailable')
        self.assertEqual(project_syntax.check('script.py','raise RuntimeError()'),'valid')

    def test_quoting_a_declaration_does_not_open_a_human_question(self):
        texts={'P1':'A label can be blank.','P2':'Who should decide?','A1.1':'Keep the first one.','P3':'소유자를 알려 주세요.'}
        qs=[dict(question=text,proposed_by=['review-1']) for text in
            ('A label can be blank.','Who should decide?','Keep the first one?','When two policies conflict, which takes priority?','소유자를 알려 주세요.')]
        actual,quoted=core.original_statements(qs,texts)
        self.assertEqual(actual,qs[1:])
        self.assertEqual(quoted,[{**qs[0],'source':'P1'}])

    def test_precedence_findings_route_policy_only_and_block_ungrounded_completion(self):
        author={'questions':[],'complete':True}
        locs=[dict(file='rules.js',line=1),dict(file='rules.js',line=2)]
        base=dict(locations=locs,sources=['P1'])
        bug=dict(**base,kind=core.FIX,message='The first return shadows the documented exception.')
        ask=dict(**base,kind=core.ASK,message='Which rule takes precedence?')
        files={'rules.js':'checkPrimary();\ncheckOverride();'}
        reviews=[{'ready':True,'findings':[bug,ask]},{'ready':False,'findings':[ask]},{'ready':True,'findings':[]}]
        questions,ready=core.review_decision(author,files,reviews,None)
        self.assertFalse(ready)
        self.assertEqual(questions,[dict(question=ask['message'],proposed_by=['review-1','review-2'])])
        clear=[{'ready':True,'findings':[]}]*3
        self.assertTrue(core.review_decision(author,files,clear,None)[1])
        self.assertFalse(core.review_decision(author,files,clear,'invalid edit')[1])

    def test_same_protocol_for_custom_task_with_separate_models_and_branch_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'run'
            public=dict(brief='Select the requested case style for the output.',files={'main.js':'return value;\n','extra.txt':'fixed\n'})
            (Path(temp)/'private-cases.json').write_text('invisible-grader')
            with locked_output(out):
                design,state=runner.setup(out,public,31,'author.gguf',['a.gguf','b.gguf','c.gguf'])
                def fake(path,role,system,user,seed,limit,port,fmt,model):
                    packet=json.loads(user.split('\n',1)[0])
                    transcript=json.dumps([packet,fmt],ensure_ascii=False)
                    self.assertNotIn('invisible-grader',transcript)
                    expected='author.gguf' if not role.startswith('multi-review-') else ['a.gguf','b.gguf','c.gguf'][int(role[-1])-1]
                    self.assertEqual(model,expected)
                    if role.startswith('multi-'):
                        self.assertNotIn('Upper case',transcript)
                        self.assertNotIn('같은 버전의 직전 자체 검토',packet)
                    else:
                        self.assertNotIn('Lower case',transcript)
                    answers=packet['담당자 답변 원문']
                    if role.endswith('main'):
                        self.assertNotIn('같은 버전의 직전 자체 검토',packet)
                        doc=dict(plan='Keep untouched assets.',questions=[],complete=bool(answers))
                        if answers:
                            method='toUpperCase' if 'Upper case' in answers[0] else 'toLowerCase'
                            doc['edits']=[dict(file='main.js',first=1,last=1,sources=['A1.1'],text=f'return value.{method}();')]
                    else:
                        finding=dict(kind=core.ASK,locations=[],sources=[],message='Which case should the output use?')
                        doc=dict(findings=[] if answers else [finding],ready=bool(answers))
                    messages=[dict(role='system',content=system),dict(role='user',content=user)]
                    record=dict(role=role,model=model,text=json.dumps(doc),request=request_body(model,messages,seed,limit,'off',fmt))
                    if path.exists():
                        self.assertEqual(read(path),record)
                    else:
                        save(path,record)
                    return record
                with patch.object(runner,'recorded',side_effect=fake):
                    runner.advance(out,design,state,{})
                    self.assertEqual({a['status'] for a in state['arms'].values()},{'awaiting_human'})
                    self.assertFalse(list(out.glob('round-*/*/submission.json')))
                    runner.answer(out,state,'self',1,'Upper case.')
                    runner.answer(out,state,'self',1,'Upper case.')
                    with self.assertRaises(ValueError):
                        runner.answer(out,state,'self',1,'New answer.')
                    runner.answer(out,state,'multi',1,'Lower case.')
                    runner.advance(out,design,state,{})
                self.assertEqual(runner.audit(out),15)
                self.assertEqual(runner.setup(out)[0],design)
                for arm,method in [('self','toUpperCase'),('multi','toLowerCase')]:
                    final=read(out/'round-002'/arm/'submission.json')
                    self.assertEqual(final['files'],{'main.js':f'return value.{method}();\n','extra.txt':'fixed\n'})
                    self.assertEqual((out/'submissions'/arm/'main.js').read_text(),final['files']['main.js'])
                with self.assertRaises(ValueError):
                    runner.setup(out,{**public,'brief':'changed'})
                tampered=out/'round-002'/'calls'/'multi-main.json'
                call=read(tampered)
                call['request']['tools']=['invisible-grader']
                save(tampered,call)
                with self.assertRaises(ValueError):
                    runner.audit(out)

    def test_general_entrypoint_excludes_evaluators_and_historical_protocols(self):
        script=('import sys; from experiments import project_review; '
                'print(" ".join(n for n in sys.modules if n.startswith(("backend.","experiments."))))')
        modules=subprocess.check_output([sys.executable,'-B','-c',script],text=True)
        for word in ('thresholds','operator','benchmark','isolated','question_guide','transfer_study','monitor_cycles'):
            self.assertNotIn(word,modules)
        from experiments import monitor_cycles
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'public.json'
            save(f,dict(brief='Sort text.',files={'a.txt':''}))
            out=Path(temp)/'new'
            with patch('sys.argv',['run',str(out),'--project',str(f)]),patch.object(runner,'run') as invoked:
                monitor_cycles.main()
                self.assertEqual(invoked.call_args.args[:2],(out,read(f)))
