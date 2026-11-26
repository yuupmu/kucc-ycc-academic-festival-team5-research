from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend import decision_regions as regions
from experiments import region_cycle
from experiments.local_transport import save


class DisjointDecisions(unittest.TestCase):
    def test_amounts_on_the_right_inputs_partition_an_unrelated_physical_domain(self):
        sources={'P1':'measure(parcel_bytes, span_cm) -> bool. Values from 0 upwards.',
                 'H1':'The parcel threshold is 2 KiB.','H2':'The span limit is 3 meters.'}
        params=['parcel_bytes','span_cm']
        notes={'P1':{'input':'none'},'H1':{'input':params[0]},'H2':{'input':params[1]}}
        cells,outputs,kind=regions.layout(params,sources,notes)
        self.assertEqual(kind,'numeric')
        self.assertEqual(len(cells),25)
        self.assertIn('parcel_bytes == 2048 and span_cm == 300',cells)
        self.assertFalse(any('span_cm == 2048' in c or 'parcel_bytes == 300' in c for c in cells))
        self.assertEqual(set(outputs),{'True','False','defer'})
        for size in (-1,0,1,2048,2049):
            for span in (-1,0,4,300,1000):
                env=dict(parcel_bytes=size,span_cm=span)
                self.assertEqual(sum(eval(c,{'__builtins__':{}},env) for c in cells),1)

    def test_only_explicit_priority_can_supply_precedence_and_unsupported_inputs_defer(self):
        sources={'P1':'Labels red, blue, green. Order and duplicates do not matter.',
                 'H1':'Priority order: green, blue, red.'}
        args=['colors']
        notes={k:{'input':'colors'} for k in sources}
        cells,opts,kind=regions.layout(args,sources,notes)
        rank=next(k for k in opts if k.startswith('first present by'))
        decisions={k:{'result':'defer','sources':[]} for k in cells}
        select='several distinct declared values, only declared values'
        decisions[select]={'result':rank,'sources':['P1']}
        patch,entries=regions.apply_choices('T1',(cells,opts,kind),decisions,sources)
        self.assertEqual(len(patch['lines']),1)
        self.assertTrue(next(r for r in entries if r['region']==select)['issue'])
        decisions[select]['sources']=['H1']
        patch,entries=regions.apply_choices('T1',(cells,opts,kind),decisions,sources)
        self.assertIn("('green', 'blue', 'red')",patch['lines'][1]['code'])
        self.assertEqual(patch['lines'][-1]['code'],'raise NotImplementedError')
        self.assertFalse(any(k.startswith('first present by') for k in regions.layout(args,{'P1':sources['P1']},notes)[1]))
        self.assertIsNone(regions.layout(args,{'P1':'Labels red, blue, green. Return the first input.'},notes))

    def test_ordinary_entry_pauses_for_actual_questions_and_refuses_unasked_answers(self):
        project={'brief':'Format a color.','files':{'color.py':'def color(x):\n    return x\n'}}
        with TemporaryDirectory() as temp, patch('experiments.region_cycle.local_server',side_effect=AssertionError('unexpected model call')):
            folder=Path(temp)
            save(folder/'project.json',dict(project=project,role='multi',seed=23))
            text=folder/'owner.txt'
            text.write_text('Use red.')
            with self.assertRaisesRegex(ValueError,'실제 질문'):
                region_cycle.project_run(folder,answer_file=text)
            save(folder/'questions.json',{'questions':[{'question':'Which color is required?'}]})
            self.assertEqual(region_cycle.project_run(folder),'Which color is required?')
