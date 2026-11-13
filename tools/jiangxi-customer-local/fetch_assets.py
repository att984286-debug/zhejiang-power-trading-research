"""Build-time only: download exact locked dependencies; never reads business files."""
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent
LOCK = json.loads((ROOT / 'dependencies.lock.json').read_text())
def fetch(item):
    relative, info = item
    path = ROOT / relative
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == info['sha256']:
        return relative + ' verified'
    request = urllib.request.Request(info['url'], headers={'User-Agent': 'jiangxi-customer-local/1.0'})
    data = urllib.request.urlopen(request, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != info['sha256']:
        raise ValueError('Dependency checksum mismatch: ' + relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative + ' downloaded and verified'
if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(fetch, LOCK.items()):
            print(result)
