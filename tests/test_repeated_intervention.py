from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from experiments import repeated_intervention as loop
from experiments.local_transport import read


class RepeatedOwnerWindows(TestCase):
    def test_each_watcher_sees_only_the_current_code_and_its_own_conditions_owner_replies(self):
        seen=[]
        project={'brief':'Pick a color.','files':{'label.txt':'old'}}
        def ask(member,system,packet,schema,seed,limit):
            seen.append((member,packet))
            return member,dict(needed=True,quote='color',possible_rule_1='Private A',
                               possible_rule_2='Private B',distinguishing_situation='Private situation',
                               owner_question='Which color should be used?')
        result=loop.questions_for(project,{'label.txt':'revised'},'multi',8,ask,[{'text':'Use blue indoors.'}])
        self.assertEqual([member for member,_ in seen],['A','B','C'])
        for _,packet in seen:
            self.assertEqual(packet,{'draft_implementation':{'label.txt':'revised'},'public_request':'Pick a color.',
                                     'prior_owner_replies':['Use blue indoors.']})
        self.assertEqual(result['questions'],[{'question':'Which color should be used?','proposed_by':['A','B','C']}])

    def test_three_replies_resume_in_order_and_the_writer_only_receives_verbatim_owner_text(self):
        project={'brief':'Write a display label.','files':{'label.txt':'draft'}}
        design={'project':project,'seed':17}
        replies=['Use a plain label.','Use the short name.','Preserve its case.']
        def inquiry(p,files,role,seed,ask,history):
            n=len(history)+1
            return dict(questions=[{'question':f'Public decision {n}?','proposed_by':['A']}],
                        reviews=[{'analysis':'PRIVATE HYPOTHESIS'}],calls=[f'question-{n}'],invalid=False)
        def revision(p,files,text,seed,role,ask):
            n=len(text.splitlines())
            self.assertEqual(text,'\n'.join(replies[:n]))
            self.assertEqual(files,project['files'] if n==1 else {'label.txt':replies[n-2]})
            files={'label.txt':replies[n-1]}
            return dict(files=files,sha256=loop.base.core.digest(files),status='open_limit',writer={},
                        reviews=[{'response':'still open'}],calls=[f'writer-{n}'])
        with TemporaryDirectory() as temp, patch.object(loop,'questions_for',side_effect=inquiry), patch.object(loop.region_cycle,'revise',side_effect=revision):
            out=Path(temp)
            def advance(audit=False):
                return loop.advance(out,design,'multi',1,project['files'],[],3,0,initial_calls=['draft'],audit=audit)
            for n,text in enumerate(replies,1):
                self.assertEqual(advance()['waiting'],n)
                self.assertFalse((out/'final.json').exists())
                folder=loop.directory(out,n)
                intake=read(folder/'intake.json')
                loop.accept(folder,intake,text)
                loop.accept(folder,intake,text)
                with self.assertRaises(ValueError):
                    loop.accept(folder,intake,'A different answer.')
            self.assertEqual(advance()['cycle'],3)
            self.assertEqual(advance(audit=True),read(out/'final.json'))
            self.assertFalse(loop.directory(out,4).exists())
            self.assertEqual((out/'submissions/candidate/label.txt').read_text(),replies[-1])
            self.assertEqual(read(loop.directory(out,2)/'snapshot.json')['received_cycles'],[1,2])

    def test_an_empty_window_does_not_accept_an_owner_reply(self):
        with TemporaryDirectory() as temp:
            intake=loop.intake_for(2,'self',{'note.txt':'ready'},[],dict(questions=[],calls=[]))
            with self.assertRaises(ValueError):
                loop.accept(Path(temp),intake,'Use orange.')
            self.assertIsNone(loop.received(Path(temp),intake))
