"""Optional engineering invocation ledger shared across environments.

This cannot grant provider authority or replace the normal project approval and
environment budget. The default policy imposes an extra cap. Explicit matching
AUDIT_ONLY_EXISTING_QUOTA policy/ledger records preserve counts without a cap.
The model never receives a writable path to either policy or ledger.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from datetime import datetime, timezone


def safe_path(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('unsafe ledger path')
    return path


@contextmanager
def locked(path):
    path=safe_path(path)
    fd=os.open(path,os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd,'r+') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & 0o077:
            raise ValueError('ledger must be private and regular')
        fcntl.flock(stream,fcntl.LOCK_EX)
        value=json.load(stream)
        yield value
        stream.seek(0);json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
        stream.truncate();stream.flush();os.fsync(stream.fileno())


class InvocationGate:
    def __init__(self,settings,eid,phase,inputs):
        self.path=None;self.eid=eid
        root=settings.data_root
        if root is None:return
        policy_path=root/'engineering-invocation-policy.json'
        if not policy_path.exists() and not policy_path.is_symlink():return
        policy=json.loads(safe_path(policy_path).read_bytes())
        if policy['environment_data_root']!=str(root.resolve()):raise ValueError('environment binding')
        self.path=safe_path(policy['ledger_path'])
        with locked(self.path) as ledger:
            if ledger['experiment_id']!=policy['experiment_id'] or ledger['historical_cli_starts']<0:
                raise ValueError('experiment binding')
            entries=ledger['entries'];used=ledger['historical_cli_starts']+len(entries)
            mode=policy.get('mode','CAPPED')
            if mode not in ('CAPPED','AUDIT_ONLY_EXISTING_QUOTA') or ledger.get('mode','CAPPED')!=mode:
                raise ValueError('policy mode binding')
            if mode=='CAPPED' and used>=ledger['total_limit']:raise ValueError('experiment exhausted')
            if any(e['execution_id']==eid for e in entries):raise ValueError('execution already reserved')
            if ledger['allowed_environment_data_root']!=str(root.resolve()):raise ValueError('environment not allocated')
            if phase not in ('document','planner','executor','reviewer'):raise ValueError('phase not allocated')
            if mode=='CAPPED' and phase!=ledger['remaining_phase_order'][len(entries)]:raise ValueError('phase not allocated')
            entry={'execution_id':eid,'phase':phase,'global_ordinal':used+1,'state':'RESERVED',
                   'input_sha256':hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest(),
                   'reserved_at':datetime.now(timezone.utc).isoformat(),'cli_started':False}
            entries.append(entry)

    def update(self,state,**fields):
        if self.path is None:return
        with locked(self.path) as ledger:
            entry=next(e for e in ledger['entries'] if e['execution_id']==self.eid)
            entry.update(state=state,**fields)

    def started(self):
        self.update('STARTED',cli_started=True,started_at=datetime.now(timezone.utc).isoformat())

    def finished(self,success):
        self.update('FINISHED' if success else 'FAILED',finished_at=datetime.now(timezone.utc).isoformat())
