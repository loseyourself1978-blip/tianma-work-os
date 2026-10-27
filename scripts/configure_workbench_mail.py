#!/usr/bin/env python3
"""Maintainer-only iCloud SMTP setup. Secrets stay in mode-0600 local files.

Does not send email, create an Apple credential, or modify the installed App.
"""
import argparse
import getpass
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--email',required=True)
    args=parser.parse_args()
    root=args.data_root.expanduser().resolve(strict=True)
    if '@' not in args.email or any(c in args.email for c in '\r\n'):parser.error('A valid sender address is required')
    directory=root/'mail'
    if directory.is_symlink():parser.error('Unsafe configuration directory')
    directory.mkdir(exist_ok=True,mode=0o700)
    config=directory/'config.json'; secret=directory/'smtp-password'
    if config.exists() or secret.exists():parser.error('Configuration already exists; retained unchanged')
    password=getpass.getpass('iCloud App-Specific Password (hidden; never your Apple Account password): ').strip()
    if not password:parser.error('No password supplied')
    for path,content in [(secret,password+'\n'),(config,json.dumps({'host':'smtp.mail.me.com','port':587,'username':args.email,'from':args.email,'password_file':str(secret)},indent=2)+'\n')]:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    print('Private mail configuration saved. Restart only the corresponding TWOS test environment before sending a verification email.')

if __name__=='__main__':main()
