#!/usr/bin/env python3
"""Fetch only SHA-pinned Adreno source and firmware; never execute firmware."""
import base64
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
pins = json.loads((ROOT / 'scripts/data/adreno-inputs.json').read_text())
TOKEN = os.environ.get('GITHUB_TOKEN', '')
HEADERS = {'User-Agent': 'sheng-offline-adreno-audit'}


def get(url, attempts=4):
    """读取一个固定 URL；共享出口的匿名额度会被耗尽，所以重试并带上凭据。"""
    headers = dict(HEADERS)
    # 凭据只发给 GitHub API，不发给第三方主机。
    if TOKEN and url.startswith('https://api.github.com/'):
        headers['Authorization'] = 'Bearer ' + TOKEN
    last = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last = error
            # 403 可能是共享出口的匿名额度耗尽，带凭据重试。
            if error.code in (403, 429) and TOKEN and 'Authorization' not in headers:
                headers['Authorization'] = 'Bearer ' + TOKEN
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as error:
            # 连接被对端重置、超时都是可重试的瞬时故障。
            last = error
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f'cannot read {url}: {last}')


def fetch(item):
    # 获取固定版本输入，并校验原始内容身份。
    # urls 里每一项是 (地址, 解码方式)：解码方式随实际取到内容的那个地址而定。
    path, urls, expected, blob = item
    if path.exists():
        data = path.read_bytes()
    else:
        # 依次尝试各个地址：共享出口会耗尽 GitHub API 的匿名额度，
        # raw 端点不消耗该额度，所以它是可靠的兜底。
        data = None
        encoding = None
        failures = []
        for url, kind in urls:
            try:
                data = get(url)
                encoding = kind
                break
            except SystemExit as error:
                failures.append(str(error))
        if data is None:
            raise SystemExit('; '.join(failures))
        if blob:
            data = base64.b64decode(json.loads(data)['content'])
        elif encoding == 'base64':
            data = base64.b64decode(data, validate=False)
    if hashlib.sha256(data).hexdigest() != expected['sha256'] or (expected.get('bytes') and len(data) != expected['bytes']):
        raise ValueError('Pinned input hash/size differs: ' + path.name)
    if blob and hashlib.sha1(('blob ' + str(len(data)) + '\0').encode() + data).hexdigest() != blob:
        raise ValueError('Pinned Git blob identity differs: ' + path.name)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return len(data)


if __name__ == '__main__':
    jobs = []
    linux = pins['linux']
    for name, expected in linux['files'].items():
        url = linux['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') + '/' + linux['commit'] + '/' + name
        jobs.append((ROOT / '.cache/adreno-source' / name, [(url, 'plain')], expected, None))
    mesa = pins['mesa']
    for name, expected in mesa['files'].items():
        # gitiles 镜像返回 base64，GitLab 官方 raw 端点返回原文；
        # 两者内容相同，任一可用即可，解码方式随实际取到的那个地址而定。
        gitiles = mesa['mirror'] + '/+/' + mesa['commit'] + '/' + name + '?format=TEXT'
        official = mesa['repository'] + '/-/raw/' + mesa['commit'] + '/' + name
        jobs.append((ROOT / '.cache/adreno-source/mesa' / name,
                     [(gitiles, 'base64'), (official, 'plain')], expected, None))
    firmware = pins['firmware']
    for name, expected in firmware['files'].items():
        blob = expected['git_blob_sha1']
        api = firmware['repository'].replace('https://github.com/', 'https://api.github.com/repos/') + '/git/blobs/' + blob
        # raw 端点按路径取同一个提交的内容，不消耗 API 额度，是限流时的兜底。
        raw = (firmware['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') +
               '/' + firmware['tree_sha'] + '/' + name)
        jobs.append((ROOT / '.cache/firmware/sheng-gpu' / name, [(api, 'plain'), (raw, 'plain')], expected, blob))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        sizes = list(executor.map(fetch, jobs))
    print(f'PASS: {len(sizes)} exact source/firmware inputs, {sum(sizes)} bytes; no GPU execution/authenticity claim')
