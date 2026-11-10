// 公开仓库仅存同步代码与安装包，不包含应用私有源码，不运行构建或测试。
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync, createWriteStream } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const repository = 'xunova1121/weiyang-release';
const requireState = (value, message) => { if (!value) throw new Error(message); };
function gh(args) {
  try {
    return execFileSync('gh', args, { encoding: 'utf8', timeout: 180_000, maxBuffer: 4 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (error) {
    const code = String(error.stderr || '').match(/HTTP\s+(\d{3})/u)?.[1];
    throw new Error(`GitHub发布操作失败${code ? `：HTTP ${code}` : ''}，保留当前发布状态`);
  }
}
const api = (path) => JSON.parse(gh(['api', `repos/${repository}/${path}`]));
const same = (left, right) => left?.state === 'uploaded' && left.size === right.bytes && left.digest === `sha256:${right.sha256}`;

async function download(asset, file) {
  const url = new URL(asset.url);
  requireState(url.protocol === 'https:' && url.hostname === 'release-assets.githubusercontent.com' && !url.port && !url.username && !url.password, '只允许GitHub官方安装包地址');
  // 临时文件地址不打印到普通日志，也不写入代码仓库；下载不携带任何API凭据。
  console.log(`::add-mask::${asset.url}`);
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(180_000) });
  requireState(response.ok && response.body, `原包下载失败：${asset.name}，HTTP ${response.status}`);
  const hash = createHash('sha256');
  let bytes = 0;
  const meter = new Transform({
    transform(chunk, encoding, done) {
      bytes += chunk.length;
      if (bytes > asset.bytes) return done(new Error('原包超过声明大小'));
      hash.update(chunk);
      done(null, chunk);
    },
  });
  await pipeline(Readable.fromWeb(response.body), meter, createWriteStream(file, { flags: 'wx' }));
  requireState(bytes === asset.bytes && hash.digest('hex') === asset.sha256, `原包大小或摘要不一致：${asset.name}`);
}

async function main() {
  requireState(process.env.GITHUB_REPOSITORY === repository, '仅能在公开安装包仓库执行');
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  const transfer = JSON.parse(event.inputs.transfer);
  requireState(/^1\.0\.\d{1,6}$/u.test(transfer.version), '版本格式不正确');
  requireState(transfer.sourceRepo === 'xunova1121/-' && /^[a-f0-9]{40}$/u.test(transfer.sourceCommit), '原包来源元数据不正确');
  const version = transfer.version;
  const tag = `desktop-v${version}`;
  const names = [
    `Jarvis-${version}-android.apk`, `Jarvis-${version}-win-x64.zip`,
    `Jarvis-Setup-${version}.exe`, `Jarvis-Setup-${version}.exe.blockmap`,
    `jarvis-server-${version}.tar.gz`, 'jarvis-server-latest.json', 'latest.yml',
  ];
  requireState(Array.isArray(transfer.assets) && transfer.assets.length === 7 && new Set(transfer.assets.map((a) => a.name)).size === 7, '必须提供7份不同的原包');
  for (const asset of transfer.assets) {
    requireState(names.includes(asset.name) && Number.isSafeInteger(asset.bytes) && asset.bytes > 0 && asset.bytes < 250 * 1024 * 1024 && /^[a-f0-9]{64}$/u.test(asset.sha256), '安装包清单不正确');
  }
  requireState(typeof transfer.notes === 'string' && transfer.notes.length < 16_000, '发布说明不正确');
  const latest = api('releases/latest');
  requireState(/^desktop-v1\.0\.\d+$/u.test(latest.tag_name) && Number(latest.tag_name.split('.').at(-1)) <= Number(version.split('.').at(-1)), '不能回退公开最新版本');
  const directory = mkdtempSync(join(tmpdir(), 'weiyang-package-sync-'));
  try {
    for (const asset of transfer.assets) await download(asset, join(directory, asset.name));
    const server = JSON.parse(readFileSync(join(directory, 'jarvis-server-latest.json'), 'utf8'));
    requireState(server.version === version && server.file === `jarvis-server-${version}.tar.gz` && server.sha256 === transfer.assets.find((a) => a.name === server.file)?.sha256, '服务器更新清单不一致');
    const windows = readFileSync(join(directory, 'latest.yml'), 'utf8');
    const exeHash = createHash('sha512').update(readFileSync(join(directory, `Jarvis-Setup-${version}.exe`))).digest('base64');
    const hashes = [...windows.matchAll(/sha512:\s*([^\s]+)/gu)];
    requireState(windows.includes(`version: ${version}`) && windows.includes(`Jarvis-Setup-${version}.exe`) && hashes.length > 0 && hashes.every((match) => match[1] === exeHash), 'Windows更新清单不一致');
    const notes = join(directory, 'notes.md');
    writeFileSync(notes, transfer.notes);
    let target = api('releases?per_page=100').find((release) => release.tag_name === tag);
    if (!target) {
      gh(['release', 'create', tag, '--repo', repository, '--draft', '--title', `未央 ${version}`, '--notes-file', notes]);
      target = api('releases?per_page=100').find((release) => release.tag_name === tag);
    }
    requireState(target && target.assets.every((asset) => names.includes(asset.name)), '目标草稿不存在或有未知附件');
    for (const asset of transfer.assets) {
      const existing = target.assets.find((item) => item.name === asset.name);
      if (existing) {
        requireState(same(existing, asset), `目标存在不同文件，停止覆盖：${asset.name}`);
        continue;
      }
      requireState(target.draft, '不能向缺件的正式版本补写文件');
      gh(['release', 'upload', tag, join(directory, asset.name), '--repo', repository]);
      console.log(`已同步：${asset.name}`);
    }
    target = api(`releases/${target.id}`);
    requireState(target.assets.length === 7 && transfer.assets.every((asset) => same(target.assets.find((item) => item.name === asset.name), asset)), '目标文件未全部核对通过，保持草稿');
    gh(['release', 'edit', tag, '--repo', repository, '--draft=false', '--prerelease=false', '--latest', '--title', `未央 ${version}`, '--notes-file', notes]);
    const published = api('releases/latest');
    requireState(published.tag_name === tag && !published.draft, '尚未确认公开最新版本');
    console.log(`发布成功：${published.html_url}`);
    console.log('只搬运现有包，没有运行测试或重新构建。');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}
main().catch((error) => {
  // 网络异常不打印完整URL/调用栈，防止临时文件签名进入日志。
  console.error(error instanceof TypeError ? '清单或网络请求失败，未完成发布' : error.message);
  process.exitCode = 1;
});
