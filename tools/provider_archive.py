"""Decrypt authenticated provider archives for private ICARUS research intake.

Reads the same provider credentials from environment. Never accepts keys in argv.
"""
import argparse
import base64
import json
import os
import zlib
from pathlib import Path
from tools.provider_exhaustive_collection import PROVIDERS

def decrypt(payload,provider,run_id,job,env):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    encoded=env.get('ICARUS_DATA_ARCHIVE_KEY','').strip()
    if encoded:key=base64.b64decode(encoded,validate=True)
    else:
        source=next((env.get(k,'').strip() for k in PROVIDERS[provider]['keys'] if env.get(k,'').strip()),'')
        if not source:raise ValueError('provider archive credential missing')
        key=HKDF(algorithm=hashes.SHA256(),length=32,salt=b'icarus-provider-archive-v1',info=provider.encode()).derive(source.encode())
    raw=AESGCM(key).decrypt(payload[:12],payload[12:],f'{run_id}:{provider}:{job}'.encode())
    data=zlib.decompress(raw)
    return json.loads(data)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--provider',choices=sorted(PROVIDERS),required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=decrypt(args.archive.read_bytes(),args.provider,args.run_id,args.archive.stem,os.environ)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Restrict POSIX access at creation, before any plaintext is written. The
    # exclusive open also preserves existing files and rejects output symlinks.
    # Windows access still depends on the destination directory's ACL.
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,sort_keys=True)
    print('Private payload restored; do not commit licensed data.')

if __name__=='__main__':main()
