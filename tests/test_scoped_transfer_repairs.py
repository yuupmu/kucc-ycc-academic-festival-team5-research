import unittest

from backend.allocation_repair import apply_edits
from experiments.scoped_transfer import bound_edits, evidence_choices


class ScopedTransferRepairs(unittest.TestCase):
    def setUp(self):
        self.history = [
            dict(request_id='early',answer={'text':'Keep pending entries.\nArchive settled entries.'}),
            dict(request_id='later',answer={'text':'Notify staff.'}),
        ]
        self.code = 'def route(active):\n\tif active:\n\t\tlabels = []\n\t\treturn labels\n\treturn None\n'

    def apply(self, target, replacement, evidence='early/H2'):
        choices = evidence_choices(self.history)
        edits = bound_edits({'edits':[dict(evidence=evidence,before=target,after=replacement)]},choices)
        return apply_edits(self.code,edits,self.history,['early','later'])

    def test_assignment_split_keeps_nested_tabs_and_adjacent_returns(self):
        for target in ('labels = []','\t\tlabels = []'):
            for replacement in ('open_items = []\nlabels = [open_items]', 'open_items = []\n\t\tlabels = [open_items]'):
                with self.subTest(target=target,replacement=replacement):
                    code = self.apply(target,replacement)
                    self.assertEqual(code,self.code.replace('labels = []','open_items = []\n\t\tlabels = [open_items]'))

    def test_multiple_statements_cannot_replace_unrelated_control_flow(self):
        with self.assertRaises(ValueError):
            self.apply('labels = []','labels = []\nreturn None')

    def test_passage_is_always_bound_to_its_origin_even_when_rounds_share_line_numbers(self):
        choices=evidence_choices(self.history)
        proposal={'edits':[dict(evidence='early/H2',before='labels = []',after='labels = [1]')]}
        edit, = bound_edits(proposal,choices)
        self.assertEqual((edit['request_id'],edit['quote']),('early','Archive settled entries.'))
        with self.assertRaises(ValueError):
            apply_edits(self.code,[edit],self.history,['later'])
