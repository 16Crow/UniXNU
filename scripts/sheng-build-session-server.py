"""临时构建会话：认证执行、加密传输，不使用 GitHub 产物或缓存。"""
import hashlib
import hmac
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(os.environ['GITHUB_WORKSPACE']).resolve()
STAGE = Path(os.environ['RUNNER_TEMP']) / 'sheng-private-session'
STAGE.mkdir(mode=0o700, exist_ok=True)
PASSWORD = os.urandom(32)
RUN = os.environ['GITHUB_RUN_ID']
TOKEN = hmac.new(PASSWORD, ('sheng-session:' + RUN).encode(), hashlib.sha256).hexdigest()
JOBS = {}
LOCK = threading.Lock()
MAGIC = b'SHNGGCM1'


def seal(data):
    # 每次传输独立盐和 nonce，密文认证同时保护完整性。
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    key = hashlib.pbkdf2_hmac('sha256', PASSWORD, salt, 200000, 32)
    return header + AESGCM(key).encrypt(nonce, data, header)


def unseal(data):
    # 先认证密文再使用输入，不把密钥或明文写进工作流输出。
    if data[:8] != MAGIC or len(data) < 52:
        raise ValueError('Invalid encrypted envelope')
    header, salt, nonce = data[:36], data[8:24], data[24:36]
    key = hashlib.pbkdf2_hmac('sha256', PASSWORD, salt, 200000, 32)
    return AESGCM(key).decrypt(nonce, data[36:], header)


def local_path(value):
    # 网络接口只允许工作区和此次 runner 临时目录内的路径。
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not any(path == root or root in path.parents for root in [ROOT, STAGE]):
        raise ValueError('Path outside build session')
    return path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        # HTTP 路径和请求内容均不写入 GitHub 日志。
        pass

    def reply(self, value, status=200, binary=False):
        # 所有响应先加密，再交给临时 HTTPS 隧道。
        raw = value if binary else json.dumps(value).encode()
        body = seal(raw)
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        # 认证失败不暴露会话信息；所有命令均来自持有本地密钥的客户端。
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            self.send_error(403)
            return
        try:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if self.command == 'GET' and parsed.path == '/info':
                return self.reply(dict(run=RUN, root=str(ROOT), stage=str(STAGE), jobs=list(JOBS)))
            if self.command == 'GET' and parsed.path == '/job':
                job = JOBS[query['id'][0]]
                position = int(query.get('offset', ['0'])[0])
                data = job['log'].read_bytes()[position:position + 128000]
                return self.reply(dict(id=job['id'], returncode=job['process'].poll(),
                                       output=data.decode(errors='replace'), next_offset=position + len(data)))
            if self.command == 'GET' and parsed.path == '/file':
                return self.reply(local_path(query['path'][0]).read_bytes(), binary=True)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100 * 1024**2:
                raise ValueError('Unexpected input length')
            raw = unseal(self.rfile.read(length))
            if parsed.path == '/file':
                path = local_path(query['path'][0])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                return self.reply(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
            document = json.loads(raw)
            if parsed.path == '/run':
                with LOCK:
                    if any(job['process'].poll() is None for job in JOBS.values()):
                        raise RuntimeError('Previous build command is still running')
                    identifier = str(len(JOBS) + 1)
                    log = STAGE / ('job-' + identifier + '.log')
                    with log.open('wb') as stream:
                        process = subprocess.Popen(['bash', '-euo', 'pipefail', '-c', document['command']],
                                                   cwd=local_path(document.get('cwd', '.')),
                                                   stdout=stream, stderr=subprocess.STDOUT, env=dict(os.environ))
                    JOBS[identifier] = dict(id=identifier, process=process, log=log)
                return self.reply(dict(id=identifier))
            if parsed.path == '/stop':
                if any(job['process'].poll() is None for job in JOBS.values()):
                    raise RuntimeError('A command is still running')
                (STAGE / 'stop').touch()
                return self.reply(dict(stopping=True))
            self.send_error(404)
        except Exception as error:
            self.reply(dict(error=str(error)), status=500)


def main():
    # 构建产物只留在临时 runner；下载确认后结束会话。
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tunnel_log = STAGE / 'tunnel.log'
    with tunnel_log.open('wb') as log:
        tunnel = subprocess.Popen(['cloudflared', 'tunnel', '--url', 'http://127.0.0.1:8765',
                                   '--no-autoupdate'], stdout=log, stderr=subprocess.STDOUT)
    import re
    for _ in range(90):
        matches = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', tunnel_log.read_text(errors='replace'))
        if matches:
            url = matches[-1]
            break
        if tunnel.poll() is not None:
            raise RuntimeError('Transfer tunnel exited')
        time.sleep(1)
    else:
        raise RuntimeError('Transfer tunnel not ready')
    # 只发布用本机公钥加密的临时会话密钥；私钥始终留在用户电脑。
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    public = serialization.load_der_public_key(base64.b64decode(os.environ['SHENG_SESSION_PUBLIC_KEY']))
    encrypted = public.encrypt(PASSWORD, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                     algorithm=hashes.SHA256(), label=None))
    metadata = json.dumps(dict(run=RUN, url=url, encrypted_key=base64.b64encode(encrypted).decode())).encode()
    payload = STAGE / 'public-session-metadata.json'
    payload.write_text(json.dumps(dict(message='ci: publish encrypted session connection metadata',
                                       branch=os.environ['GITHUB_REF_NAME'],
                                       content=base64.b64encode(metadata).decode())))
    subprocess.run(['gh', 'api', '--method', 'PUT',
                    'repos/' + os.environ['GITHUB_REPOSITORY'] + '/contents/sessions/sheng-build-' + RUN + '.json',
                    '--input', str(payload)], check=True, stdout=subprocess.DEVNULL)
    print('Authenticated build session ready; no artifacts or caches are uploaded.', flush=True)
    deadline = time.monotonic() + 5 * 3600
    while time.monotonic() < deadline and not (STAGE / 'stop').exists():
        if tunnel.poll() is not None:
            raise RuntimeError('Transfer tunnel disconnected')
        time.sleep(3)
    server.shutdown()
    tunnel.terminate()
    # 保持入口占用，供本机确认下载后取消这一专用会话，防止旧工作流接着执行旧构建。
    time.sleep(120)
    raise RuntimeError('Private session ended; legacy build steps must not run')


if __name__ == '__main__':
    main()
