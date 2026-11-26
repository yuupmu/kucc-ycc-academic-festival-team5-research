"""Content-addressed local inference. Identical requests share the exact original response."""
from experiments import festival_protocol as base
from experiments.local_transport import compact, read, recorded, request_body
from experiments.project_review import freeze


class Calls:
    def __init__(self, out, design, port=0, prior=(), audit=False):
        self.out = out
        self.design = design
        self.port = port
        self.prior = tuple(prior)
        self.audit = audit

    def reuse(self, path, role, system, user, seed, limit, port, fmt, model):
        if not path.exists():
            for directory in self.prior:
                existing = directory / path.name
                if existing.is_file():
                    freeze(path, read(existing))
                    break
        return recorded(path, role, system, user, seed, limit, port, fmt, model)

    def __call__(self, role, system, packet, schema, seed, limit):
        return base.call_model(self.out, self.design, role, system, packet, schema, seed, limit,
                               self.port, self.audit, self.reuse)

    def text(self, role, system, packet, seed, limit):
        model = self.design['model']
        user = compact(packet)
        messages = [{'role':'system','content':system},{'role':'user','content':user}]
        request = request_body(model,messages,seed,limit,'off',None)
        key = base.core.digest([role,request])
        path = self.out/'calls'/(key+'.json')
        if self.audit:
            raw = read(path)
        else:
            path.parent.mkdir(exist_ok=True)
            raw = self.reuse(path,role,system,user,seed,limit,self.port,None,model)
        if (raw['role'],raw['model'],raw['request'])!=(role,model,request):
            raise ValueError('자연 코드 작성 요청이 원문과 다릅니다.')
        u = raw['usage']
        if any(type(u.get(k)) is not int or u[k]<0 for k in ('prompt_tokens','completion_tokens','total_tokens')) or u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:
            raise ValueError('자연 코드 작성 호출의 실제 토큰 계측이 다릅니다.')
        return key, raw['text'] if raw['finish_reason']=='stop' else None
