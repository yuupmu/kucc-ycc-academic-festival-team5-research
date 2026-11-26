"""Use the exact predeclared endpoint and executable evaluator of the first receipt reader."""
import runpy
from trial import PREV

if __name__=='__main__':
    runpy.run_path(str(PREV/'assess.py'),run_name='__main__')
