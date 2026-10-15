"""Server-owned email proof, separate from model authorization.

SMTP credentials are administrator-local, private files, never product assets.
The only injectable sender lives on app.state for isolated tests, never HTTP.
"""
from datetime import timedelta
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import stat
import time

from fastapi import Depends, Request, Response
from pydantic import Field
from sqlalchemy import select, text, update
from .models import User, SessionToken, utc_now
from .security import hash_password, verify_password, hash_token
from .project_first import Strict, mutation, fail, identity, now
from .workbench_models import EmailIdentity, EmailChallenge, AuthThrottle


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        fail('EMAIL_INVALID', 422)
    return value


def private_bytes(path):
    path = Path(path).expanduser()
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('private configuration required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1 or st.st_size > 32000:
            raise ValueError('private configuration required')
        return stream.read()


class SMTPMail:
    def __init__(self, settings):
        self.path = settings.mail_config_path or (settings.data_root / 'mail/config.json' if settings.data_root else None)

    def config(self):
        if not self.path:
            raise ValueError('mail not configured')
        value = json.loads(private_bytes(self.path))
        for key in ('host', 'username', 'from', 'password_file'):
            if not isinstance(value.get(key), str) or not value[key] or any(c in value[key] for c in '\r\n'):
                raise ValueError('mail configuration invalid')
        if value.get('port', 587) not in (587, 465):
            raise ValueError('TLS mail required')
        normalize_email(value['from'])
        return value

    def available(self):
        try:
            c = self.config()
            return bool(private_bytes(c['password_file']).strip())
        except Exception:
            return False

    def send(self, email, purpose, code):
        c = self.config()
        password = private_bytes(c['password_file']).decode().strip()
        msg = EmailMessage()
        msg['From'] = c['from']; msg['To'] = email
        msg['Subject'] = 'TWOS ' + ('password reset' if purpose == 'reset' else 'email verification')
        msg.set_content(f'TWOS {purpose}\n\nYour verification code: {code}\n\nExpires in 10 minutes. Use only in the TWOS window that requested it.\nIf you did not request this, ignore this message.\n')
        port = c.get('port', 587)
        context = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(c['host'], port, timeout=20, context=context) if port == 465 else smtplib.SMTP(c['host'], port, timeout=20)
        with smtp:
            if port == 587:
                smtp.ehlo(); smtp.starttls(context=context); smtp.ehlo()
            smtp.login(c['username'], password)
            if smtp.send_message(msg):
                raise ValueError('mail refused')


def secret_key(settings):
    from sqlalchemy.engine import make_url
    root = settings.data_root or Path(make_url(settings.database_url).database).parent
    path = root / 'email-challenge-key'
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(secrets.token_bytes(32)); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            pass
    key = private_bytes(path)
    if len(key) != 32:
        fail('EMAIL_SERVICE_UNAVAILABLE', 503)
    return key


def serialize(session):
    if session.get_bind().dialect.name == 'sqlite':
        session.commit(); session.execute(text('BEGIN IMMEDIATE'))


def throttle(session, key, limit, seconds):
    current = int(time.time()); bucket = current // seconds
    row = session.get(AuthThrottle, key)
    if not row:
        row = AuthThrottle(key=key, window=bucket, count=0); session.add(row)
    if row.window != bucket:
        row.window = bucket; row.count = 0
    row.count += 1
    session.flush()
    if row.count > limit:
        session.commit(); fail('AUTH_RATE_LIMIT', 429)


def set_cookie(response, request, name, value, age):
    response.set_cookie(name, value, max_age=age, httponly=True, samesite='strict', secure=request.url.scheme == 'https', path='/')


def login_session(session, user, response, request, settings):
    raw = secrets.token_urlsafe(32)
    session.add(SessionToken(user_id=user.id, token_hash=hash_token(raw), created_at=utc_now(), expires_at=utc_now()+timedelta(seconds=settings.session_ttl_seconds)))
    set_cookie(response, request, settings.session_cookie_name, raw, settings.session_ttl_seconds)


class Begin(Strict):
    email: str = Field(max_length=254)
    purpose: str = Field(pattern='^(signup|reset|bind)$')
    password: str = Field(default='', max_length=200)
    confirmation: bool


class Verify(Strict):
    challenge_id: str = Field(max_length=64)
    purpose: str = Field(pattern='^(signup|reset|bind)$')
    code: str = Field(pattern=r'^\d{6}$')


class Reset(Strict):
    challenge_id: str = Field(max_length=64)
    password: str = Field(min_length=12, max_length=200)
    confirmation: str = Field(min_length=12, max_length=200)


class EmailLogin(Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class ChallengeID(Strict):
    challenge_id: str = Field(max_length=64)
    confirmation: bool = False


def install(app, settings, get_db, current_user):
    app.state.mail_sender = SMTPMail(settings)
    flow_cookie = settings.session_cookie_name + '_email_flow'
    reset_cookie = settings.session_cookie_name + '_reset'

    def proof(row, code):
        return hmac.new(secret_key(settings), (row.id+'\0'+row.email+'\0'+row.purpose+'\0'+code).encode(), hashlib.sha256).hexdigest()

    def flow_row(session, request, cid):
        row = session.get(EmailChallenge, cid)
        flow = request.cookies.get(flow_cookie, '')
        if not row or not flow or not hmac.compare_digest(row.flow_hash, hash_token(flow)):
            fail('EMAIL_CODE_INVALID', 400)
        return row

    def send(session, row):
        code = f'{secrets.randbelow(1000000):06d}'
        row.code_hash = proof(row, code)
        sent_hash = row.code_hash
        row.issued = int(time.time()); row.expires = row.issued + 600
        row.attempts = 0; row.state = 'SENDING'
        session.commit()  # a crash is never reported as sent
        try:
            # Nonexistent resets and existing signups produce the same public reply.
            exists = session.scalar(select(EmailIdentity).where(EmailIdentity.email == row.email))
            eligible = (row.purpose == 'reset' and exists) or (row.purpose in ('signup', 'bind') and not exists)
            if eligible:
                app.state.mail_sender.send(row.email, row.purpose, code)
        except Exception:
            session.execute(update(EmailChallenge).where(EmailChallenge.id == row.id,
                EmailChallenge.state == 'SENDING', EmailChallenge.code_hash == sent_hash).values(state='SEND_FAILED', code_hash=''))
            session.commit()
            fail('EMAIL_SEND_FAILED', 503)
        changed = session.execute(update(EmailChallenge).where(EmailChallenge.id == row.id,
            EmailChallenge.state == 'SENDING', EmailChallenge.code_hash == sent_hash).values(state='SENT'))
        session.commit()
        if changed.rowcount != 1:
            fail('EMAIL_CODE_REPLACED', 409)
        return {'challenge_id': row.id, 'state': 'CHECK_EMAIL', 'delivery': 'NOT_CONFIRMED', 'expires_in': 600}

    @app.get('/api/auth/email/status')
    def status(request: Request, session=Depends(get_db)):
        pending = None
        flow = request.cookies.get(flow_cookie)
        if flow:
            row = session.scalar(select(EmailChallenge).where(EmailChallenge.flow_hash == hash_token(flow),
                EmailChallenge.purpose.in_(['signup', 'reset']), EmailChallenge.state.in_(['SENT', 'RESET_AUTHORIZED']),
                EmailChallenge.expires >= int(time.time())))
            if row:
                pending = {'challenge_id': row.id, 'email': row.email, 'purpose': row.purpose, 'state': row.state}
        return {'configured': app.state.mail_sender.available(), 'gate': 'REAL_INBOX_PROOF_REQUIRED', 'account_sync': False, 'pending': pending}

    @app.post('/api/auth/email/begin')
    def begin(payload: Begin, request: Request, response: Response, session=Depends(get_db)):
        mutation(request)
        if not payload.confirmation: fail('CONFIRMATION_REQUIRED', 422)
        email = normalize_email(payload.email)
        if not app.state.mail_sender.available(): fail('EMAIL_SERVICE_UNAVAILABLE', 503)
        serialize(session)
        throttle(session, 'send-global', 30, 3600)
        throttle(session, 'send:'+hash_token(email), 5, 3600)
        throttle(session, 'cooldown:'+hash_token(email), 1, 30)
        account = session.scalar(select(EmailIdentity).where(EmailIdentity.email == email))
        user_id = account.user_id if account and payload.purpose == 'reset' else None
        ph = salt = ''
        if payload.purpose == 'signup':
            if len(payload.password) < 12: fail('PASSWORD_TOO_SHORT', 422)
            ph, salt = hash_password(payload.password)
        if payload.purpose == 'bind':
            user = current_user(request, session)
            if not verify_password(payload.password, user.password_hash, user.password_salt): fail('AUTH_INVALID', 401)
            if session.get(EmailIdentity, user.id): fail('EMAIL_ALREADY_BOUND', 409)
            user_id = user.id
        # Replacement invalidates every old challenge for this email/purpose.
        for old in session.scalars(select(EmailChallenge).where(EmailChallenge.email == email, EmailChallenge.purpose == payload.purpose)):
            if old.state in ('SENDING', 'SENT', 'VERIFIED', 'RESET_AUTHORIZED'): old.state = 'REPLACED'
        flow = secrets.token_urlsafe(32)
        row = EmailChallenge(id=identity('email'), flow_hash=hash_token(flow), email=email, purpose=payload.purpose,
            user_id=user_id, password_hash=ph, password_salt=salt, code_hash='', issued=0, expires=0)
        session.add(row); session.flush()
        result = send(session, row)
        set_cookie(response, request, flow_cookie, flow, 1800)
        return result

    @app.post('/api/auth/email/resend')
    def resend(payload: ChallengeID, request: Request, session=Depends(get_db)):
        mutation(request); serialize(session)
        row = flow_row(session, request, payload.challenge_id)
        if row.state not in ('SENT', 'SEND_FAILED', 'LOCKED'): fail('EMAIL_CODE_INVALID', 400)
        if int(time.time()) - row.issued < 30: fail('AUTH_RATE_LIMIT', 429)
        throttle(session, 'send-global', 30, 3600)
        throttle(session, 'send:'+hash_token(row.email), 5, 3600)
        return send(session, row)

    @app.post('/api/auth/email/verify')
    def verify(payload: Verify, request: Request, response: Response, session=Depends(get_db)):
        mutation(request); serialize(session)
        row = flow_row(session, request, payload.challenge_id)
        if row.state != 'SENT' or row.purpose != payload.purpose or row.expires < int(time.time()): fail('EMAIL_CODE_INVALID', 400)
        row.attempts += 1
        if row.attempts > 5 or not hmac.compare_digest(row.code_hash, proof(row, payload.code)):
            if row.attempts >= 5: row.state = 'LOCKED'
            session.commit(); fail('EMAIL_CODE_INVALID', 400)
        row.code_hash = ''
        existing = session.scalar(select(EmailIdentity).where(EmailIdentity.email == row.email))
        if row.purpose == 'reset':
            if not existing or existing.user_id != row.user_id: fail('EMAIL_CODE_INVALID', 400)
            raw = secrets.token_urlsafe(32); row.reset_hash = hash_token(raw)
            row.state = 'RESET_AUTHORIZED'; row.expires = int(time.time()) + 600
            set_cookie(response, request, reset_cookie, raw, 600)
            return {'state': 'RESET_AUTHORIZED'}
        if existing: fail('EMAIL_CODE_INVALID', 400)
        if row.purpose == 'bind':
            user = current_user(request, session)
            if row.user_id != user.id: fail('EMAIL_CODE_INVALID', 400)
            row.state = 'VERIFIED'
            return {'state': 'BIND_CONFIRMATION_REQUIRED'}
        user = User(username=identity('email_user'), password_hash=row.password_hash, password_salt=row.password_salt, is_active=True)
        session.add(user); session.flush()
        session.add(EmailIdentity(user_id=user.id, email=row.email, verified_at=now()))
        row.user_id = user.id; row.state = 'CONSUMED'; row.password_hash = ''; row.password_salt = ''
        login_session(session, user, response, request, settings)
        return {'state': 'VERIFIED', 'authenticated': True, 'projects_created': 0}

    @app.post('/api/auth/email/bind/confirm')
    def bind(payload: ChallengeID, request: Request, session=Depends(get_db), user=Depends(current_user)):
        mutation(request); serialize(session)
        row = flow_row(session, request, payload.challenge_id)
        if not payload.confirmation or row.purpose != 'bind' or row.state != 'VERIFIED' or row.user_id != user.id or row.expires < int(time.time()): fail('EMAIL_CODE_INVALID', 400)
        if session.get(EmailIdentity, user.id) or session.scalar(select(EmailIdentity).where(EmailIdentity.email == row.email)): fail('EMAIL_ALREADY_BOUND', 409)
        session.add(EmailIdentity(user_id=user.id, email=row.email, verified_at=now())); row.state = 'CONSUMED'
        return {'state': 'BOUND', 'data_moved': False}

    @app.post('/api/auth/email/reset')
    def reset(payload: Reset, request: Request, response: Response, session=Depends(get_db)):
        mutation(request); serialize(session)
        row = flow_row(session, request, payload.challenge_id)
        raw = request.cookies.get(reset_cookie, '')
        if row.purpose != 'reset' or row.state != 'RESET_AUTHORIZED' or row.expires < int(time.time()) or not raw or not hmac.compare_digest(row.reset_hash, hash_token(raw)):
            fail('RESET_AUTHORIZATION_INVALID', 400)
        if payload.password != payload.confirmation: fail('PASSWORD_MISMATCH', 422)
        user = session.get(User, row.user_id)
        user.password_hash, user.password_salt = hash_password(payload.password)
        for token in session.scalars(select(SessionToken).where(SessionToken.user_id == user.id)):
            token.revoked_at = utc_now()
        for challenge in session.scalars(select(EmailChallenge).where(EmailChallenge.user_id == user.id, EmailChallenge.purpose == 'reset')):
            challenge.state = 'CONSUMED'; challenge.reset_hash = ''
        response.delete_cookie(reset_cookie, path='/')
        response.delete_cookie(settings.session_cookie_name, path='/')
        return {'state': 'LOGIN_REQUIRED'}

    @app.post('/api/auth/email/login')
    def login(payload: EmailLogin, request: Request, response: Response, session=Depends(get_db)):
        mutation(request); serialize(session)
        email = normalize_email(payload.email)
        throttle(session, 'login-global', 100, 600)
        throttle(session, 'login:'+hash_token(email), 10, 600)
        account = session.scalar(select(EmailIdentity).where(EmailIdentity.email == email))
        user = session.get(User, account.user_id) if account else None
        if not user:
            hash_password('timing-normalization-password', salt='A'*32)
        valid = bool(user and user.is_active and verify_password(payload.password, user.password_hash, user.password_salt))
        if not valid:
            session.commit(); fail('AUTH_INVALID', 401)
        login_session(session, user, response, request, settings)
        return {'authenticated': True}
