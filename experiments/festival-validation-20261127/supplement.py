"""Replay each affected pre-reply agenda under the frozen independent-scope fallback."""
import sys
from pathlib import Path
from run import OUT, PILOT, MODEL, PORT, cases, prepare, receipt, read, local_server, locked_output

def main():
    dest=OUT/'supplement'/'pilot'
    with local_server(PORT+1,MODEL):
        import run
        run.PORT=PORT+1
        if sys.argv[1]=='prepare':
            prepare(dest,907,PILOT/'shared/handoff.json')
            prepare(OUT/'supplement'/'control',907,OUT/'control-input.json')
        else:
            assert read(dest/'delivery.json')['qualified']
            for side in ('display','hide'):
                receipt(dest,907,1,(PILOT/(side+'.txt')).read_text().strip(),dest/side)

if __name__=='__main__':
    with locked_output(OUT):
        main()
