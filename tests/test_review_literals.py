import unittest

from backend import review_literals


def layout(*statements):
    sources = dict(P1='Classify the queue state.')
    sources.update({f'H{i}': text for i, text in enumerate(statements, 1)})
    receipts = [dict(text='\n'.join(statements), questions=[])]
    return review_literals.layout(['state','flags'], sources, receipts)


class ReviewLiteralRules(unittest.TestCase):
    def test_quoted_korean_strings_preserve_case_and_unknown_values(self):
        (cells, _, _), decisions = layout("state가 'Raw'이면 'Keep'을 반환합니다.")
        key = "state == 'Raw'"
        self.assertEqual(decisions, {key:dict(result="'Keep'",sources=['H1'])})
        condition = cells[key]['condition']
        self.assertTrue(eval(condition, {}, dict(state='Raw')))
        self.assertFalse(eval(condition, {}, dict(state='raw')))

    def test_primitive_equality_does_not_capture_a_different_type(self):
        (cells, _, _), decisions = layout('If state is 1, return 9.', 'If state is True, return 4.')
        for arg, result in [(True,'4'),(1,'9'),(1.0,None)]:
            matching = [decisions[k]['result'] for k,c in cells.items() if eval(c['condition'], {}, dict(state=arg))]
            self.assertEqual(matching, [] if result is None else [result])

    def test_conflicting_and_qualified_clauses_do_not_authorize_a_write(self):
        base = "If state equals 'ready', return 'show'."
        for other in ["If state equals 'ready', return 'hide'.",
                      "If state equals 'ready' and a reviewer has approved it, return 'show'."]:
            self.assertEqual(layout(base, other)[1], {})
        self.assertIsNone(layout(base, 'If flags equals 1, return 9.'))
        self.assertIsNone(review_literals.locate("state == 'ready' except for pending jobs", {"state == 'ready'"}))

    def test_questions_cannot_supply_a_missing_output(self):
        sources = dict(P1='Choose a state.', H1='That decision is still open.')
        result = review_literals.layout(['state'],sources,[dict(text=sources['H1'],questions=[dict(
            question="If state equals 'ready', return 'show'.")])])
        self.assertIsNone(result)

    def test_retraction_and_explicit_replacement_affect_their_own_scope(self):
        one="If state is 'archive', return 'cold'."
        two="If state is 'ready', return 'hot'."
        self.assertEqual(layout(one, 'I retract my previous answer.')[1], {})
        rules=layout(one, two, "Correction: If state is 'archive', return 'warm'.")[1]
        self.assertEqual(rules["state == 'archive'"], dict(result="'warm'", sources=['H3']))
        self.assertEqual(rules["state == 'ready'"], dict(result="'hot'", sources=['H2']))

