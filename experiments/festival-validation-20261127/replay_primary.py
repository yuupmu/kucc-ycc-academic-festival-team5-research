"""Reproduce the preregistered primary preparation with its archived implementation."""
import run
import decision_ledger_v1
from experiments import ledger_pipeline

if __name__=='__main__':
    ledger_pipeline.ledger=decision_ledger_v1
    run.ledger=decision_ledger_v1
    with run.locked_output(run.OUT):
        run.main()
