"""Narrow, non-privileged candidate builder for a reviewed catalog-only iteration.

The controller supplies the build steps. Candidate-provided build scripts are
never executed. Only the approved bilingual resource may replace packaged bytes.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import unittest
import runpy
import tempfile

from .iteration_studio import ALLOWED,CATALOG,REGRESSION,check_changes,git
from .project_first import fail,encoded,digest,now


def bundle_path():
    if not getattr(sys,'frozen',False):fail('PACKAGED_BUILDER_REQUIRED')
    app=Path(sys.executable).resolve().parents[3]
    if app.suffix!='.app' or not (app/'Contents/Info.plist').is_file():fail('PACKAGED_BUILDER_REQUIRED')
    return app


def run_regression(root,app,*,expect_pass=True):
    executable=app/'Contents/Resources/engine/twos-service'
    # Sandbox only the untrusted candidate regression. No network or writes,
    # and no access to private user roots except this candidate and shipped code.
    # macOS must stat each selected path's ancestors before launching the frozen
    # binary. Allow metadata only, never parent directory contents/user files.
    ancestors=sorted({str(p) for target in (root,app) for p in target.parents})
    traversal=' (allow file-read-metadata '+''.join('(literal '+json.dumps(p)+')' for p in ancestors)+')'
    profile='(version 1) (allow default) (deny network*) (deny file-write*) (deny file-read* (subpath "/Users"))'+traversal+' (allow file-read* (subpath '+json.dumps(str(root))+') (subpath '+json.dumps(str(app))+')) (deny process-exec) (allow process-exec (literal '+json.dumps(str(executable))+'))'
    try:
        r=subprocess.run(['/usr/bin/sandbox-exec','-p',profile,str(executable),'--twos-iteration-check',str(root)],
            cwd=root,capture_output=True,timeout=35,env={'PATH':'/usr/bin:/bin','HOME':str(root),'PYTHONDONTWRITEBYTECODE':'1'})
    except (OSError,subprocess.TimeoutExpired):fail('ITERATION_TEST_FAILED')
    # No arbitrary candidate stdout is exposed as diagnostics.
    try: receipt=json.loads(r.stdout)
    except ValueError:fail('ITERATION_TEST_FAILED')
    if receipt.get('tests_run',0)<1:fail('ITERATION_TEST_FAILED')
    if expect_pass:
        if r.returncode!=0 or not receipt.get('passed'):fail('ITERATION_TEST_FAILED')
    elif r.returncode!=1 or receipt.get('passed') or receipt.get('errors')!=0 or receipt.get('failures',0)<1:
        fail('ITERATION_REGRESSION_INSENSITIVE')
    return receipt


def validate_generated_regression(root,baseline,app):
    """Run the unchanged model test against immutable before and one-sided mutants.

    Each fixture has only public candidate source inputs and the exact model test;
    it receives the same read-only/no-network/no-subprocess sandbox as the candidate.
    A test that compares the file to itself cannot pass this gate.
    """
    before=json.loads(git(root,'show',baseline+':'+CATALOG))
    after=json.loads((root/CATALOG).read_bytes())
    test=(root/REGRESSION).read_bytes()
    variants={'unchanged_target':before}
    for locale in ('en-US','zh-CN'):
        value=json.loads(json.dumps(after))
        value['noSourcesDesc'][locale]=before['noSourcesDesc'][locale]
        variants['unchanged_'+locale]=value
    receipts={}
    with tempfile.TemporaryDirectory(prefix='.twos-regression-controls-',dir=root.parent) as directory:
        for name,value in variants.items():
            variant=Path(directory)/name
            for relative,content in ((CATALOG,json.dumps(value,ensure_ascii=False).encode()),(REGRESSION,test)):
                path=variant/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            receipts[name]=run_regression(variant,app,expect_pass=False)
    return {'status':'PASSED','baseline':baseline,'test_sha256':hashlib.sha256(test).hexdigest(),
            'negative_controls':receipts,'candidate_test_unchanged':True}


def check_main(argv):
    """Only invoked in the controller-enforced sandbox, fixed candidate test path."""
    root=Path(argv[0]).resolve(strict=True)
    path=root/REGRESSION
    if not path.is_file() or path.is_symlink():return 2
    namespace=runpy.run_path(str(path),run_name='twos_candidate_regression')
    suite=unittest.TestSuite()
    for value in namespace.values():
        if isinstance(value,type) and issubclass(value,unittest.TestCase) and value is not unittest.TestCase:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
    result=unittest.TestResult();suite.run(result)
    print(json.dumps({'tests_run':result.testsRun,'passed':result.wasSuccessful() and result.testsRun>0,
        'failures':len(result.failures),'errors':len(result.errors),'sandbox':'read-only-no-network'}))
    return 0 if result.wasSuccessful() and result.testsRun else 1


def candidate_preview(root,baseline,review):
    checks=check_changes(root,baseline)
    if review.get('deterministic_checks',{}).get('files')!=checks['files']:fail('CANDIDATE_INPUT_CHANGED')
    if review.get('independent_review',{}).get('verdict')!='PASS':fail('INDEPENDENT_REVIEW_REQUIRED')
    app=bundle_path()
    receipt=run_regression(root,app)
    return {'files':checks['files'],'baseline':baseline,'checks':checks,'regression':receipt,
            'running_app':str(app),'method':'RESOURCE_ONLY_REPRODUCIBLE_CHILD','self_iteration_test_artifact':True,
            'requires_separate_local_commit':True,'requires_separate_install_confirmation':True}


def commit_candidate(root,preview,*,name,email):
    if not name.strip() or len(name)>100 or not email.strip() or '@' not in email or any(c in name+email for c in '\n\r\0'):
        fail('COMMIT_IDENTITY_INVALID')
    if preview['files']!={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ALLOWED}:fail('CANDIDATE_INPUT_CHANGED')
    if git(root,'rev-parse','HEAD').strip()!=preview['baseline']:fail('CANDIDATE_INPUT_CHANGED')
    app=bundle_path()
    provenance=json.loads((app/'Contents/Resources/source-provenance.json').read_text())
    # The child is valid only when all original runtime inputs match the running
    # controller. Do not package unrelated/unreviewed candidate changes.
    for path,h in provenance['input_hashes'].items():
        if path==CATALOG:continue
        candidate=root/path
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest()!=h:fail('BUILD_BASELINE_MISMATCH')
    # Explicit identity applies only to this one authorized local commit.
    git(root,'add','--',*ALLOWED)
    git(root,'-c','user.name='+name,'-c','user.email='+email,'commit','--no-gpg-sign','-m','Improve bilingual empty-project guidance')
    commit=git(root,'rev-parse','HEAD').strip()
    if git(root,'status','--porcelain').strip():fail('CANDIDATE_SOURCE_DIRTY')
    return commit


def build(root,preview,*,commit,build_directory):
    if git(root,'rev-parse','HEAD').strip()!=commit or git(root,'status','--porcelain').strip():fail('CANDIDATE_SOURCE_DIRTY')
    if preview['files']!={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ALLOWED}:fail('CANDIDATE_INPUT_CHANGED')
    app=bundle_path()
    provenance=json.loads((app/'Contents/Resources/source-provenance.json').read_text())
    build_directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    volume=build_directory/'volume';volume.mkdir()
    candidate=volume/app.name
    shutil.copytree(app,candidate,symlinks=True)
    dest=candidate/'Contents/Resources/engine/_internal'/CATALOG
    if not dest.is_file():fail('BUNDLED_CATALOG_MISSING')
    dest.write_bytes((root/CATALOG).read_bytes())
    inputs=dict(provenance['input_hashes']);inputs[CATALOG]=hashlib.sha256(dest.read_bytes()).hexdigest()
    source_hash=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    child_build=provenance['build_version']+'.1'
    provenance.update(source_commit=commit,source_input_sha256=source_hash,input_hashes=inputs,
        build_version=child_build,self_iteration_test_artifact=True,base_build=provenance['build_version'],
        candidate_build_method='RESOURCE_ONLY_REPRODUCIBLE_CHILD',public_ga=False)
    resources=candidate/'Contents/Resources'
    (resources/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    info_path=candidate/'Contents/Info.plist';info=plistlib.loads(info_path.read_bytes())
    info.update(CFBundleVersion=child_build,TWOSSourceCommit=commit,TWOSSourceInputSHA256=source_hash)
    info_path.write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(candidate)],check=True,capture_output=True,timeout=90)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(candidate)],check=True,capture_output=True,timeout=60)
    (volume/'Applications').symlink_to('/Applications',target_is_directory=True)
    dmg=build_directory/('TWOS-self-iteration-'+child_build+'-'+commit[:12]+'.dmg')
    subprocess.run(['/usr/bin/hdiutil','create','-volname','TWOS Self Iteration','-srcfolder',str(volume),'-format','UDZO',str(dmg)],check=True,capture_output=True,timeout=180)
    receipt={'artifact':str(dmg),'sha256':hashlib.sha256(dmg.read_bytes()).hexdigest(),'size':dmg.stat().st_size,
        'source_commit':commit,'source_input_sha256':source_hash,'build':child_build,'status':'CANDIDATE_READY',
        'installed':False,'owner_accepted':False,'self_iteration_test_artifact':True,'created_at':now(),
        'install_method':'OWNER_GUI_DMG','automatic_in_app_update':False,'regression':preview['regression']}
    (build_directory/'INSTALLER_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (build_directory/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    manifest={str(p.relative_to(candidate)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in candidate.rglob('*') if p.is_file() and not p.is_symlink()}
    (build_directory/'APP_MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    (build_directory/'SHA256SUMS').write_text(receipt['sha256']+'  '+dmg.name+'\n')
    return receipt


def execute_build(service,eid):
    from .project_first_models import WorkItem,WorkExecution,ProjectSpace
    from .project_first import activity
    with service.factory() as session:
        row=session.get(WorkExecution,eid);inputs=json.loads(row.input_json)
    receipt=build(Path(inputs['root']),inputs['preview'],commit=inputs['commit'],build_directory=Path(inputs['destination']))
    with service.factory() as session:
        row=session.get(WorkExecution,eid);work=session.get(WorkItem,row.work_id)
        row.evidence_json=encoded(receipt);row.output=encoded(receipt);row.state='COMPLETED';row.finished_at=now()
        work.state='CANDIDATE_READY'
        activity(session,work.project_id,'CANDIDATE_READY',receipt,'build_tool',work.id)
        session.commit()
