#!/usr/bin/env python3
"""在用户自己的终端下载并公开发布现有1.0.416，不调用Actions，不构建或安装。"""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import warnings

REPOSITORY = 'xunova1121/weiyang-release'
API = f'https://api.github.com/repos/{REPOSITORY}'
SOURCE = 'xunova1121/-'
SOURCE_API = f'https://api.github.com/repos/{SOURCE}'
VERSION = '1.0.416'
SOURCE_COMMIT = '0663254bfd2d1f1338bfee918ddf3f869b81b84c'
EXPECTED = {
    'Jarvis-1.0.416-android.apk': (18580417, '1be88b210538d62bfd49622e068aef1cdaef2492a4388b25fc2fd6d90c5c796f'),
    'Jarvis-1.0.416-win-x64.zip': (177674015, 'f3ea1b0208a30e7b49f18b098c07f9d8744100d86dff60fd1bd2643d7bc50a71'),
    'Jarvis-Setup-1.0.416.exe': (140843466, '5b34d8056c26f7ccc3328f4d6b091b27e342b28258a64983a26f3211f30ac586'),
    'Jarvis-Setup-1.0.416.exe.blockmap': (148127, '969cd1b437a272c02867ae1e9942090f51637f5c5e3cd14ce70dce00a8c1596d'),
    'jarvis-server-1.0.416.tar.gz': (28146852, 'f808f812dd69195699196246bb428d84d5b903cabab4b082a8166a6312a0e2b7'),
    'jarvis-server-latest.json': (136, 'e77e4587a18b9ac3a48f7f80c0d85631cf0b8afae5aeda72fad90140aff00b5c'),
    'latest.yml': (347, '958a9d05b1533f3021638105ea19c80dda6d1db9c500ba4c507eb4777fbf0e64'),
}


class StopPublish(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def require(value, message):
    if not value:
        raise StopPublish(message)


def digest(path, algorithm='sha256'):
    hasher = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher


def request_json(token, url, method='GET', body=None, file=None):
    parsed = urllib.parse.urlparse(url)
    require(parsed.scheme == 'https' and parsed.hostname in ('api.github.com', 'uploads.github.com')
            and not parsed.port and not parsed.username and not parsed.password,
            '拒绝向非官方地址发送发布凭据')
    target_path = parsed.path.startswith(f'/repos/{REPOSITORY}/releases')
    source_read = method == 'GET' and parsed.hostname == 'api.github.com' and parsed.path.startswith(f'/repos/{SOURCE}/releases')
    require(target_path or source_read, '请求路径不属于指定发布仓库或只读原包接口')
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
               'User-Agent': 'weiyang-direct-release', 'X-GitHub-Api-Version': '2022-11-28'}
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    if data is not None:
        headers['Content-Type'] = 'application/json'
    stream = None
    if file is not None:
        headers['Content-Type'] = 'application/octet-stream'
        headers['Content-Length'] = str(file.stat().st_size)
        stream = file.open('rb')
        data = stream
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect).open(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # 只输出固定诊断码，绝不打印请求头、令牌、原始响应或重定向地址。
        labels = {401: '发布授权未通过', 403: '权限或访问限制', 404: '资源不可访问',
                  422: '发布或附件冲突', 429: '接口限流'}
        reason = labels.get(error.code, 'GitHub请求失败')
        raise StopPublish(f'{parsed.hostname} HTTP {error.code}：{reason}；停止发布，保留已有文件') from None
    except urllib.error.URLError:
        raise StopPublish(f'{parsed.hostname} 连接未完成；停止发布，保留已有文件') from None
    finally:
        if stream:
            stream.close()


def validate_local(directory):
    manifest = json.loads((directory / 'manual-release-files.json').read_text())
    version = manifest['version']
    require(version == VERSION, '本工具只用于发布现有1.0.416')
    names = {f'Jarvis-{version}-android.apk', f'Jarvis-{version}-win-x64.zip',
             f'Jarvis-Setup-{version}.exe', f'Jarvis-Setup-{version}.exe.blockmap',
             f'jarvis-server-{version}.tar.gz', 'jarvis-server-latest.json', 'latest.yml'}
    assets = manifest['assets']
    require(len(assets) == 7 and {a['name'] for a in assets} == names, '必须提供指定7份安装文件')
    require(manifest['sourceCommit'] == SOURCE_COMMIT, '构建来源不符合已确认版本')
    for asset in assets:
        require((asset['bytes'], asset['sha256']) == EXPECTED[asset['name']], '文件清单与已确认原包不一致')
        file = directory / asset['name']
        require(not file.is_symlink() and file.is_file(), f'文件缺失：{asset["name"]}')
        require(file.stat().st_size == asset['bytes'] and digest(file).hexdigest() == asset['sha256'],
                f'文件大小或摘要不一致：{asset["name"]}')
    server = json.loads((directory / 'jarvis-server-latest.json').read_text())
    require(server['version'] == version and server['file'] == f'jarvis-server-{version}.tar.gz'
            and server['sha256'] == next(a['sha256'] for a in assets if a['name'] == server['file']),
            '服务器更新清单不一致')
    import base64
    windows = (directory / 'latest.yml').read_text()
    hashes = re.findall(r'sha512:\s*([^\s]+)', windows)
    expected = base64.b64encode(digest(directory / f'Jarvis-Setup-{version}.exe', 'sha512').digest()).decode()
    require(f'version: {version}\n' in windows and f'Jarvis-Setup-{version}.exe' in windows
            and hashes and all(item == expected for item in hashes), 'Windows更新清单不一致')
    return manifest


def download_asset(token, asset, directory):
    size, expected_hash = EXPECTED[asset['name']]
    require(asset['state'] == 'uploaded' and asset['size'] == size and asset.get('digest') == 'sha256:' + expected_hash,
            '源发布附件与已确认原包不一致')
    endpoint = SOURCE_API + f'/releases/assets/{int(asset["id"])}'
    req = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + token,
                                 'Accept': 'application/octet-stream', 'User-Agent': 'weiyang-direct-release'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60):
            raise StopPublish('原包接口未返回预期下载地址')
    except urllib.error.HTTPError as error:
        require(error.code == 302, f'读取原包失败：HTTP {error.code}；请核对令牌对源码仓库的访问权限')
        location = error.headers.get('Location', '')
    url = urllib.parse.urlparse(location)
    require(url.scheme == 'https' and url.hostname == 'release-assets.githubusercontent.com'
            and not url.port and not url.username and not url.password, '拒绝非GitHub官方下载地址')
    # 临时地址仅在本机内存里供正常下载使用，不写入仓库、日志、工作流或第三方服务。
    # CDN下载不携带API令牌，禁用自动重定向，避免授权头被转发。
    request = urllib.request.Request(location, headers={'User-Agent': 'weiyang-direct-release'})
    path = directory / asset['name']
    hasher, total = hashlib.sha256(), 0
    with urllib.request.build_opener(NoRedirect).open(request, timeout=180) as response, path.open('xb') as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            require(total <= size, '原包超过声明大小，已停止下载')
            hasher.update(chunk)
            output.write(chunk)
    require(total == size and hasher.hexdigest() == expected_hash, '下载原包摘要不一致，未发布')
    print('已下载并核对：' + asset['name'], flush=True)


def prepare_local(token):
    source = request_json(token, SOURCE_API + '/releases/tags/desktop-v' + VERSION)
    require(not source['draft'] and not source['prerelease'] and source.get('published_at')
            and source['target_commitish'] == SOURCE_COMMIT, '源版本不是已确认正式发布的1.0.416')
    require(len(source['assets']) == 7 and {a['name'] for a in source['assets']} == set(EXPECTED), '源发布附件不完整')
    directory = Path(tempfile.mkdtemp(prefix='weiyang-release-1.0.416-', dir=Path.cwd()))
    print('安装包保存目录：' + str(directory), flush=True)
    print('开始下载约349MB现有安装包；不会编译、运行测试或更新本机未央。', flush=True)
    for asset in source['assets']:
        download_asset(token, asset, directory)
    manifest = {'version': VERSION, 'sourceCommit': SOURCE_COMMIT, 'testsRerun': False,
                'assets': [{'name': name, 'bytes': details[0], 'sha256': details[1]} for name, details in EXPECTED.items()]}
    (directory / 'manual-release-files.json').write_text(json.dumps(manifest, ensure_ascii=False))
    (directory / 'manual-release-notes.md').write_text(source.get('body') or '')
    return directory


def matches(actual, expected):
    return actual and actual.get('state') == 'uploaded' and actual['size'] == expected['bytes'] \
        and actual.get('digest') == 'sha256:' + expected['sha256']


def publish(directory, token):
    manifest = validate_local(directory)
    version = manifest['version']
    tag = 'desktop-v' + version
    notes = (directory / 'manual-release-notes.md').read_text()
    notes = re.sub(r'^下载状态：.*\n\n?', '', notes, flags=re.M)
    print(f'{version}：三端7份本地文件及更新清单核对一致；未构建、未运行测试', flush=True)
    latest = request_json(token, API + '/releases/latest')
    require(re.fullmatch(r'desktop-v1\.0\.\d+', latest['tag_name'])
            and int(latest['tag_name'].split('.')[-1]) <= int(version.split('.')[-1]), '不能回退公开最新版本')
    releases = request_json(token, API + '/releases?per_page=100')
    target = next((release for release in releases if release['tag_name'] == tag), None)
    if target is None:
        target = request_json(token, API + '/releases', 'POST',
                              {'tag_name': tag, 'name': '未央 ' + version, 'body': notes, 'draft': True})
    require(all(a['name'] in {item['name'] for item in manifest['assets']} for a in target['assets']),
            '目标发布有未知附件，停止覆盖')
    upload = target['upload_url'].split('{', 1)[0]
    require(upload == f'https://uploads.github.com/repos/{REPOSITORY}/releases/{target["id"]}/assets',
            'GitHub返回的上传入口不符合预期')
    # 小文件先传，鉴权失败立即停止，避免先传几百MB；已完成的相同原包可继续复用。
    for asset in sorted(manifest['assets'], key=lambda item: item['bytes']):
        existing = next((a for a in target['assets'] if a['name'] == asset['name']), None)
        if existing:
            require(matches(existing, asset), f'目标已有不同文件，停止覆盖：{asset["name"]}')
            continue
        require(target['draft'], '正式发布缺少附件，停止修改')
        url = upload + '?' + urllib.parse.urlencode({'name': asset['name']})
        uploaded = request_json(token, url, 'POST', file=directory / asset['name'])
        require(matches(uploaded, asset), f'上传回执摘要不符：{asset["name"]}')
        print(f'已上传：{asset["name"]}', flush=True)
    target_url = API + f'/releases/{target["id"]}'
    target = request_json(token, target_url)
    require(len(target['assets']) == 7 and all(matches(next((a for a in target['assets'] if a['name'] == item['name']), None), item)
                                                for item in manifest['assets']), '公开附件尚未齐全，保留草稿')
    request_json(token, target_url, 'PATCH', {'draft': False, 'prerelease': False,
                                           'make_latest': 'true', 'name': '未央 ' + version, 'body': notes})
    latest = request_json(token, API + '/releases/latest')
    require(latest['tag_name'] == tag and not latest['draft'], '尚未确认公开最新版本')
    receipt = {'tag': tag, 'url': latest['html_url'], 'assets': [a['name'] for a in latest['assets']],
               'published': True, 'actionsUsed': False, 'testsRerun': False}
    (directory / 'direct-publish-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print('公开发布完成：' + latest['html_url'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, help='已有完整原包目录；省略则从已发布版本下载')
    args = parser.parse_args()
    try:
        # 只在用户自己的真实终端隐藏输入；凭据不进shell历史、环境变量、文件或聊天。
        require(sys.stdin.isatty(), '请在自己的交互终端执行脚本，不能通过管道输入令牌')
        warnings.simplefilter('error', getpass.GetPassWarning)
        credential = getpass.getpass('粘贴GitHub发布令牌后回车（输入不显示）：').strip()
        require(credential, '未输入令牌，未请求')
        directory = args.directory.resolve() if args.directory else prepare_local(credential)
        publish(directory, credential)
        print('三端原包已公开发布。设备仍需分别更新；令牌可以在GitHub中撤销。')
    except StopPublish as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('用户已停止；未确认公开发布完成', file=sys.stderr)
        sys.exit(130)
    except getpass.GetPassWarning:
        print('当前终端无法隐藏输入，已停止；请使用支持密码隐藏输入的终端。', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError):
        print('网络、本地文件或发布元数据异常；未确认发布完成。不要回传令牌。', file=sys.stderr)
        sys.exit(1)
