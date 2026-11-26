"""Run the frozen scorer with the three additive token counters from llama.cpp."""
import score


def token_usage(dest, calls):
    totals = dict(calls=len(calls), prompt_tokens=0, completion_tokens=0, total_tokens=0)
    for key in calls:
        raw = score.read(dest / 'calls' / (key + '.json'))['usage']
        for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            totals[name] += raw[name]
    if totals['prompt_tokens'] + totals['completion_tokens'] != totals['total_tokens']:
        raise ValueError('Raw token counts disagree')
    return totals


if __name__ == '__main__':
    # Keep the registered scoring source and every sealed candidate byte-identical.
    score.usage = token_usage
    score.main()
