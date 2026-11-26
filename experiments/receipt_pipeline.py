"""Apply every owner sentence to the existing decision ticket; keep literal quantities and prose."""
import argparse
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from backend.answer_contracts import SHORT
from backend.project_review import digest
from backend.structured_output import array, obj
from experiments import decision_ledger as ledger
from experiments.festival_protocol import MODEL, call_model
from experiments.ledger_pipeline import open_ticket
from experiments.local_transport import local_server, locked_output, read
from experiments.partial_reply import choices
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING


NUMBER = re.compile(r'(?<![\d.])[-+]?\d+(?!\d|\.\d)')
QUANTIFIED = re.compile(r'[-+]?\d+\s*(?:[A-Za-z가-힣%°]+?)?\s*(?:입니다|이에요|예요|이다|입니다만)[.!。]?\s*$'
                        r'|(?:\bis\s+|^)[-+]?\d+(?:\s+[A-Za-z]+)?[.!]?\s*$',re.I)
UNANSWERED = re.compile(r'아직\s*(?:미정|결정하지|정하지)|미정(?:입니다|이에요|이다)?[.! ]*$|\b(?:undecided|not decided)\b',re.I)
COMPOUND = re.compile(r'[,，].+|(?:이고|이며|하고|지만|하며)\s+|\b(?:and|but|whereas)\b',re.I)
SELECT = ('담당자가 실제로 쓴 한 문장과, 이 회신을 받을 때 전달한 질문들입니다. 이 문장이 직접 답하는 항목 하나를 고르세요. '
          '질문과 무관하거나 여러 항목 중 어디에 답한 것인지 알 수 없으면 해당 없음입니다. 행동을 정한 문장이라면 '
          '그 상황에서 함수를 실행·허용·켜는 의미는 True, 거절·끄는 의미는 False입니다. 실제 발언의 부정 표현을 정확히 읽으세요. '
          '질문에 들어 있던 설명은 결정의 근거가 아닙니다. 다른 정책을 보충하지 마세요.')


def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?。！？])\s+|(?<=[다요죠][.!?])(?=\S)|[\n;；]+',text) if s.strip()]


def evidence_spans(line,ask,calls):
    if not COMPOUND.search(line) or len(line.split())<6:
        return [line]
    key,parts=ask('receipt-subclauses',ledger.FACTS,{'owner_reply':line},
                  obj({'facts':array(obj({'quote':STRING,'kind':choices(ledger.KINDS)}),0,12)}),440)
    calls.append(key)
    spans=sorted({(line.index(q),line.index(q)+len(q)) for f in (parts or {}).get('facts',[])
                  if (q:=ledger.source_quote(line,f['quote']))})
    if len(spans)<2 or any(a[1]>b[0] for a,b in zip(spans,spans[1:])):
        return [line]
    # Unquoted substantive material is retained and considered, including a final omitted clause.
    out=[]
    end=0
    for start,stop in [*spans,(len(line),len(line))]:
        gap=line[end:start].strip(' ,，.')
        if gap and gap.casefold() not in {'고','이고','그리고','and','but','이며','하며'}:
            out.append(gap)
        if stop>start:
            out.append(line[start:stop])
        end=stop
    return out


def receive(agenda,parent,reply,ask):
    if not reply.strip() or not parent['pending']:
        raise ValueError('No open ticket or answer')
    active={k:agenda['slots'][k] for k in parent['pending']}
    matched=defaultdict(list)
    calls,observed=[],[]
    for line in sentences(reply):
        for quote in evidence_spans(line,ask,calls):
            nums=list(dict.fromkeys(int(n) for n in NUMBER.findall(quote)))
            number_statement=bool(nums and (QUANTIFIED.search(quote) or NUMBER.fullmatch(quote.strip(' .'))))
            pool={k:s for k,s in active.items() if (s['kind']=='quantity' and nums) or
                  (s['kind']=='decision' and not number_statement)}
            record=dict(quote=quote,candidates=list(pool),status='open')
            observed.append(record)
            if not pool or UNANSWERED.search(quote) or (SHORT.fullmatch(quote) and len(active)>1):
                continue
            fmt={'item':choices([*pool,'해당 없음'])}
            has_action=any(s['kind']=='decision' for s in pool.values())
            if has_action or len(nums)>1:
                fmt['value']=choices([*(['True','False'] if has_action else []),
                                                    *map(str,nums),ledger.OPEN])
            key,binding=ask('receipt-item',SELECT,dict(owner_statement=quote,
                            sent_items={k:s['question'] for k,s in pool.items()},ticket_size=len(active)),obj(fmt),100)
            calls.append(key)
            record['binding']=binding
            if not binding or binding['item'] not in pool:
                continue
            item=binding['item']
            answer=binding.get('value')
            if pool[item]['kind']=='quantity':
                if len(nums)==1:
                    value=nums[0]
                elif answer in list(map(str,nums)):
                    value=int(answer)
                else:
                    continue
            elif answer in ('True','False'):
                value=answer=='True'
            else:
                continue
            record['status']='matched'
            matched[item].append(dict(value=value,quote=quote,turn=len(parent['history'])+1))
    confirmed=dict(parent['confirmed'])
    for k,rows in matched.items():
        if len({v['value'] for v in rows})==1:
            confirmed[k]=rows[0]
    code,edits=ledger.materialize(agenda,parent['code'],confirmed)
    history=dict(ticket=list(active),reply=reply,statements=observed,calls=calls,edits=edits)
    return dict(code=code,confirmed=confirmed,pending=[k for k in agenda['slots'] if k not in confirmed],
                history=[*parent['history'],history])


def checkpoint(folder,agenda,parent,reply,ask):
    folder.mkdir(parents=True,exist_ok=True)
    key=digest([digest(agenda),digest(parent),reply])
    path=folder/'solution.py'
    if (folder/'seal.json').exists():
        seal,state=read(folder/'seal.json'),read(folder/'state.json')
        if (seal['ticket']!=key or seal['state']!=digest(state) or path.read_bytes()!=state['code'].encode()
                or seal['code']!=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise ValueError('A different receipt or source is bound to this checkpoint')
        return state
    state=receive(agenda,parent,reply,ask)
    freeze(folder/'state.json',state)
    if path.exists() and path.read_bytes()!=state['code'].encode():
        raise ValueError('Existing source differs')
    if not path.exists():
        path.write_bytes(state['code'].encode())
    freeze(folder/'seal.json',dict(ticket=key,state=digest(state),code=hashlib.sha256(path.read_bytes()).hexdigest()))
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('out',type=Path)
    action=p.add_mutually_exclusive_group(required=True)
    action.add_argument('--handoff',type=Path)
    action.add_argument('--answer-file',type=Path)
    p.add_argument('--turn',type=int)
    p.add_argument('--port',type=int,default=18984)
    p.add_argument('--seed',type=int,default=273)
    args=p.parse_args()
    with locked_output(args.out):
        freeze(args.out/'config.json',dict(model=MODEL,seed=args.seed,reader='literal-sentences-v1'))
        with local_server(args.port,MODEL):
            def ask(role,prompt,packet,fmt,cap):
                return call_model(args.out,{'model':MODEL},role,prompt,packet,fmt,args.seed,cap,args.port)
            if args.handoff:
                handoff=read(args.handoff)
                if 'questions' not in handoff:
                    handoff['questions']=handoff['dialogue'][0]['questions']
                agenda=open_ticket(args.out,handoff,ask)
                print(*agenda['sent_questions'].values(),sep='\n')
                return
            if not args.turn or args.turn<1:
                p.error('Specify the ticket turn')
            ref=read(args.out/'agenda.json')
            agenda=ref['agenda']
            if ref['digest']!=digest(agenda):
                raise ValueError('Stored agenda differs')
            parent=ledger.start(agenda)
            for turn in range(1,args.turn+1):
                folder=args.out/f'turn-{turn}'
                reply=args.answer_file.read_text() if turn==args.turn else read(folder/'state.json')['history'][-1]['reply']
                parent=checkpoint(folder,agenda,parent,reply,ask)
            print(*ledger.questions(agenda,parent) or ['담당자 결정 항목이 모두 확정되었습니다.'],sep='\n')


if __name__=='__main__':
    main()
