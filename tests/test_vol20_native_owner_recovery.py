"""Synthetic local accounts only. No real Owner credential or provider call."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import select

from twos_runtime import desktop_owner_recovery as recovery
from twos_runtime.db import initialize_database, make_engine, make_session_factory
from twos_runtime.maintenance import MaintenanceError, open_lock
from twos_runtime.models import AuditEvent, User
from twos_runtime.security import authenticate, create_owner, AuthenticationError, user_for_token

OLD = "synthetic original password"
NEW = "synthetic replacement password"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path):
    data = tmp_path.resolve() / "data"; data.mkdir(mode=0o700)
    db = data / "twos.sqlite3"
    engine = make_engine("sqlite:///" + str(db)); initialize_database(engine)
    with make_session_factory(engine)() as session:
        owner = create_owner(session, "fixture-owner", OLD)
        _, token, _ = authenticate(session, owner.username, OLD, 3600)
        session.commit()
    engine.dispose(); db.chmod(0o600)
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE recovery_business_fixture(id integer primary key, body text)")
        c.execute("INSERT INTO recovery_business_fixture VALUES(1,'preserve delivered history')")
    identity = "install_" + "a"*32
    (data / "installation.json").write_text(json.dumps(dict(installation_id=identity, data_root=str(data), database_path=str(db))))
    return data, token


def rows(db):
    with sqlite3.connect(db) as c:
        return {name: c.execute('SELECT * FROM "'+name+'"').fetchall() for (name,) in
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'").fetchall()}


def exchange(data, mutate=lambda r:r, *, cancel=False):
    read, write = os.pipe(); events=[]
    def emit(kind, **fields):
        events.append(dict(event=kind, **fields))
        if kind == "recovery_preview":
            if cancel:
                os.close(write); return
            request = {k:fields[k] for k in ("nonce", "installation_id", "owner_id")}
            request.update(confirmation="RESET_EXISTING_OWNER_PASSWORD", password=NEW, password_confirmation=NEW)
            os.write(write, json.dumps(mutate(request)).encode()+b"\n")
    try:
        recovery.recover(data, read, emit, seconds=.15)
        return events
    finally:
        os.close(read)
        if not cancel: os.close(write)


def test_reset_preserves_every_business_table_id_and_history_revokes_sessions_and_reloads(installation):
    data, token = installation; db=data/'twos.sqlite3'; before=rows(db)
    events=exchange(data)
    assert [e['event'] for e in events] == ['recovery_preview','recovery_complete']
    after=rows(db)
    for name in before.keys()-{'users','session_tokens','audit_events'}:
        assert after[name] == before[name], name
    engine=make_engine('sqlite:///'+str(db))
    with make_session_factory(engine)() as session:
        owner=session.scalar(select(User)); assert owner.id==1 and owner.username=='fixture-owner'
        assert user_for_token(session, token) is None
        with pytest.raises(AuthenticationError): authenticate(session, 'fixture-owner', OLD, 3600)
        assert authenticate(session, 'fixture-owner', NEW, 3600)[0].id == 1
        assert len(session.scalars(select(AuditEvent).where(AuditEvent.action=='owner_recovered')).all()) == 1
        session.rollback()
    engine.dispose()
    backups=list((data/'owner-credential-recovery').glob('*/before.sqlite3'))
    assert len(backups)==1 and rows(backups[0])==before
    assert backups[0].stat().st_mode & 0o077 == 0
    corpus=json.dumps(events)
    assert NEW not in corpus and OLD not in corpus and token not in corpus
    with pytest.raises(MaintenanceError, match='Local account recovery'): exchange(data)
    assert rows(db)==after


@pytest.mark.parametrize('change,code', [
    ({'nonce':'wrong'},'RECOVERY_CONFIRMATION_INVALID'),
    ({'installation_id':'install_'+'b'*32},'RECOVERY_CONFIRMATION_INVALID'),
    ({'owner_id':2},'RECOVERY_CONFIRMATION_INVALID'),
    ({'owner_id':True},'RECOVERY_CONFIRMATION_INVALID'),
    ({'confirmation':False},'RECOVERY_CONFIRMATION_INVALID'),
    ({'password':'short','password_confirmation':'short'},'RECOVERY_PASSWORD_INVALID'),
    ({'password_confirmation':'different'},'RECOVERY_PASSWORD_INVALID'),
    ({'password':'x'*201,'password_confirmation':'x'*201},'RECOVERY_PASSWORD_INVALID'),
    ({'password':None},'RECOVERY_PASSWORD_INVALID'),
    ({'arbitrary_database':'/tmp/foreign'},'RECOVERY_REQUEST_INVALID'),
])
def test_invalid_confirmation_input_and_cross_installation_leave_database_unchanged(installation,change,code):
    data,_=installation; before=rows(data/'twos.sqlite3')
    with pytest.raises(MaintenanceError) as error: exchange(data,lambda r:dict(r,**change))
    assert error.value.code==code
    assert rows(data/'twos.sqlite3')==before
    assert not (data/'owner-credential-recovery').exists()


def test_cancel_and_partial_input_timeout_are_bounded_and_nonmutating(installation):
    data,_=installation; before=rows(data/'twos.sqlite3')
    with pytest.raises(MaintenanceError) as e: exchange(data,cancel=True)
    assert e.value.code=='RECOVERY_CANCELLED'
    read,write=os.pipe()
    try:
        os.write(write,b'{"password":')
        with pytest.raises(MaintenanceError) as e: recovery.read_request(read,.01)
        assert e.value.code=='RECOVERY_TIMEOUT'
    finally: os.close(read);os.close(write)
    assert rows(data/'twos.sqlite3')==before


@pytest.mark.parametrize('frame',[b'[]\n', b'{broken}\n', b'\xff\n', b'x'*8193+b'\n'])
def test_invalid_frames_are_rejected(frame,tmp_path):
    # A regular descriptor avoids the test producer blocking on pipe capacity
    # before the reader starts; partial-pipe timeout is tested independently.
    path=tmp_path/'input';path.write_bytes(frame)
    with path.open('rb') as stream:
        with pytest.raises(MaintenanceError) as e: recovery.read_request(stream.fileno(),.1)
        assert e.value.code=='RECOVERY_REQUEST_INVALID'


@pytest.mark.parametrize('boundary',['snapshot','receipt','transaction'])
def test_storage_and_transaction_failures_preserve_account_and_all_records(installation,monkeypatch,boundary):
    data,_=installation; before=rows(data/'twos.sqlite3')
    def broken(*a,**kw):raise OSError('synthetic disk failure; must not cross native pipe')
    if boundary=='snapshot':monkeypatch.setattr(recovery,'snapshot',broken)
    elif boundary=='receipt':monkeypatch.setattr(recovery,'atomic_json',broken)
    else:
        original=recovery.recover_owner_credentials
        def halfway(*a,**kw):original(*a,**kw);broken()
        monkeypatch.setattr(recovery,'recover_owner_credentials',halfway)
    with pytest.raises(OSError):exchange(data)
    assert rows(data/'twos.sqlite3')==before
    # Failure releases both leases; retry is explicit and can reach preview.
    fd=open_lock(data/'twos.sqlite3',exclusive=True);os.close(fd)


def test_other_runtime_lease_blocks_recovery_without_stealing_lock(installation):
    data,_=installation; before=rows(data/'twos.sqlite3');fd=open_lock(data/'twos.sqlite3')
    try:
        with pytest.raises(MaintenanceError) as e:exchange(data)
        assert e.value.code=='INSTALLATION_BUSY'
        os.fstat(fd)
    finally:os.close(fd)
    assert rows(data/'twos.sqlite3')==before


@pytest.mark.parametrize('sql,code', [
    ("UPDATE users SET is_active=0",'RECOVERY_OWNER_UNAVAILABLE'),
    ("UPDATE users SET username=' fixture-owner '",'RECOVERY_OWNER_UNAVAILABLE'),
    ("INSERT INTO r2_work_executions(id,work_id,revision,phase,idempotency_key,plan_hash,state,input_json,evidence_json,output,error_code,started_at) VALUES('fixture','fixture',1,'execute','fixture','fixture','RUNNING','{}','{}','','','2026-10-08')",'ACTIVE_OPERATION'),
])
def test_recovery_does_not_activate_or_rename_accounts_or_interrupt_work(installation,sql,code):
    data,_=installation;db=data/'twos.sqlite3'
    with sqlite3.connect(db) as connection:connection.execute(sql)
    before=rows(db)
    with pytest.raises(MaintenanceError) as e:exchange(data)
    assert e.value.code==code and rows(db)==before


@pytest.mark.parametrize('unsafe',['root_symlink','db_hardlink','shared_directory','journal_symlink','wrong_identity','missing_db'])
def test_storage_boundaries_fail_closed(installation,tmp_path,unsafe):
    data,_=installation; db=data/'twos.sqlite3'
    if unsafe=='root_symlink':
        link=tmp_path/'linked';link.symlink_to(data);data=link
    elif unsafe=='db_hardlink':os.link(db,tmp_path/'other.sqlite3')
    elif unsafe=='shared_directory':data.chmod(0o755)
    elif unsafe=='journal_symlink':(data/'twos.sqlite3-journal').symlink_to(tmp_path/'absent')
    elif unsafe=='wrong_identity':
        p=data/'installation.json';d=json.loads(p.read_text());d['database_path']='/tmp/wrong.sqlite3';p.write_text(json.dumps(d))
    else:db.rename(data/'preserved.sqlite3')
    with pytest.raises(MaintenanceError):exchange(data)
    assert not (data/'owner-credential-recovery').exists()


def test_native_contract_has_system_user_presence_personal_confirmation_and_closed_dispatch():
    native=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text()
    assert 'evaluatePolicy(.deviceOwnerAuthentication' in native
    assert 'NSSecureTextField' in native and 'Reset this account password' in native
    assert 'RESET_EXISTING_OWNER_PASSWORD' in native
    assert 'process.standardError = FileHandle.nullDevice' in native
    assert 'recover-owner' not in (ROOT/'twos_runtime/app.py').read_text()
    assert '--twos-owner-recovery' in (ROOT/'packaging/macos/service_entry.py').read_text()
    catalog=json.loads((ROOT/'static_cockpit/project_first/catalog.json').read_text())
    assert 'error.INVALID_CREDENTIALS' in catalog
    translations=json.loads((ROOT/'static_cockpit/project_first/native_i18n.json').read_text())
    for key in ['Recover local account…','Reset this account password','Confirm new local password']:
        assert all(translations[key][locale] for locale in ['en-US','zh-CN'])


@pytest.mark.skipif(sys.platform != 'darwin', reason='AppKit layout/lifecycle requires macOS')
def test_real_appkit_password_geometry_and_nonblocking_terminal_dismissal(tmp_path):
    """Compile the exact production presenter; no credentials or auth bypass.

    The prior NSStackView collapsed secure fields to their empty intrinsic width.
    The old synchronous runModal also prevented queued worker timeout handling.
    A hidden parent keeps this component test separate from personal GUI testing.
    """
    native=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text()
    presenter=native[:native.index('// The only child runtime')]
    source=tmp_path/'main.swift'
    source.write_text(presenter+'''
let app = NSApplication.shared
let host = NSWindow(contentRect: NSRect(x:0,y:0,width:720,height:620),
    styleMask:[.titled],backing:.buffered,defer:false)
let prompt = RecoveryPrompt()
var responseCount = 0
DispatchQueue.main.async {
    prompt.show(on:host,title:"Synthetic layout test",detail:"No credential input.",
        action:"Review",cancel:"Cancel",passwordLabels:["New password","Confirm password"]) { _,_ in responseCount += 1 }
    // Reaching this line proves presentation did not enter a blocking runModal.
    DispatchQueue.main.asyncAfter(deadline:.now()+0.05) {
        let sheet = prompt.alert!
        sheet.window.layoutIfNeeded()
        let fields = prompt.fields
        precondition(fields.count == 2)
        for field in fields {
            precondition(field.frame.width >= 400 && field.frame.height >= 26)
            precondition(!field.isHidden && field.isEnabled && field.isEditable && field.isSelectable)
            precondition(field.stringValue.isEmpty)
            precondition(field.superview!.bounds.contains(field.frame))
        }
        precondition(fields[0].nextKeyView === fields[1])
        precondition(!fields[0].frame.intersects(fields[1].frame))
        prompt.dismiss() // Same product method used on worker failure/timeout.
        precondition(prompt.alert == nil && prompt.fields.isEmpty)
        prompt.dismiss() // Idempotent cancellation, no late submit callback.
        DispatchQueue.main.asyncAfter(deadline:.now()+0.05) {
            precondition(responseCount == 0)
            print("APPKIT_LAYOUT_AND_TERMINAL_DISMISSAL_PASS")
            exit(0)
        }
    }
}
app.run()
''')
    binary=tmp_path/'recovery-layout'
    compile_result=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(tmp_path/'module-cache'),'-framework','AppKit','-framework','LocalAuthentication',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert compile_result.returncode == 0, compile_result.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'APPKIT_LAYOUT_AND_TERMINAL_DISMISSAL_PASS' in result.stdout


def test_native_terminal_handling_drains_output_and_invalidates_open_prompt():
    native=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text()
    form=native.split('func showRecoveryForm(',1)[1]
    assert '.runModal()' not in form
    assert 'beginSheetModal' in native
    assert 'guard recoveryExited && recoveryEOF else { return }' in native
    finish=native.split('func finishRecoveryMessage',1)[1].split('func launchRecovery',1)[0]
    assert 'recoveryPrompt.dismiss()' in finish
    assert form.count('guard self.recoveryActive, !self.recoveryReported, self.recoveryProcess?.isRunning == true') == 2
