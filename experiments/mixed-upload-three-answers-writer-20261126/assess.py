"""Apply the unchanged, predeclared evaluator to this trial directory."""
import runpy
from trial import FIRST

if __name__ == '__main__':
    runpy.run_path(str(FIRST/'assess.py'), run_name='__main__')
