from unittest import TestCase
from unittest.mock import patch

from experiments import transfer100_data as data, transfer100_report as report, transfer100_study as study


class Transfer100(TestCase):
    def test_each_public_task_has_twenty_distinct_manually_expected_inputs(self):
        total=0
        for task,config in data.TASKS.items():
            self.assertEqual(len(config['cases']),20)
            self.assertEqual(len({repr(c[2]) for c in config['cases']}),20)
            for _,_,args,expected,required in config['cases']:
                self.assertEqual(data.reference(task,args),expected)
                self.assertIs(type(data.reference(task,args)),type(expected))
                self.assertTrue(set(required)<=config['cards'].keys())
            total+=len(config['cases'])
        self.assertEqual(total,100)
        self.assertEqual(len(study.ARMS),len(set(study.ARMS)))

    def test_one_exceeded_dimension_alone_is_sufficient_evidence(self):
        item=dict(task='print',args=[7,5],required=['width','height'])
        self.assertTrue(report.needs(item,{'width'})[0])
        self.assertTrue(report.needs(item,{'height'})[0])
        self.assertFalse(report.needs(item,set())[0])
        item=dict(task='print',args=[6,4],required=['width','height','equal'])
        self.assertFalse(report.needs(item,{'width','height'})[0])

    def test_unanswered_and_lucky_correct_are_distinguished_from_known_rule_failures(self):
        rows=[dict(id='synthetic',task='title',category='synthetic',skill='empty',args=[''],expected='untitled',required=['empty'])]
        rec=dict(files={},sha256='fake',receipts=[],calls=[],status='open_limit')
        def raw(value,error=None):
            return [dict(actual=dict(value=value,exception=error,lines=[]),error=None)]
        with patch.object(report,'execute',return_value=raw('untitled')):
            _,cases=report.measure('title','synthetic',1,rec,rows,{})
            self.assertEqual(cases[0]['stage'],'correct_unsupported')
        with patch.object(report,'execute',return_value=raw(None,'NotImplementedError')):
            _,cases=report.measure('title','synthetic',1,rec,rows,{})
            self.assertEqual(cases[0]['stage'],'missing_defer')
        rec['receipts']=[dict(text=data.TASKS['title']['cards']['empty'],questions=[dict(question='빈 제목은?')])]
        with patch.object(report,'execute',return_value=raw('')):
            _,cases=report.measure('title','synthetic',1,rec,rows,{})
            self.assertEqual(cases[0]['stage'],'known_wrong')
