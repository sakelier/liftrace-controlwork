/* Manifest catalog and native streamed downloads; no large browser Blob. */
'use strict';
const mappingState = {page: 0, more: false, runs: [], jobs: [], busy: false, source: '', online: false, generation: 0, sourceId: null};
const mappingLabels = {starting: '启动中', waiting: '等待话题', recording: '录制中', finalizing: '收尾中',
  complete: '已封闭', partial: '不完整', failed: '失败', not_applicable: '未运行 FreeDOM（不适用）',
  downloading: '取回到 PC', exporting: '导出点云', packaging: '打包中', ready: '可下载', interrupted: '已中断'};
function mappingButton(text, action, disabled) {
  const node = logNode('button', text); node.className = 'btn'; node.disabled = !!disabled; node.onclick = action; return node;
}
function mappingRender() {
  const state = mappingState, busyTask = state.jobs.some(j => ['downloading','exporting','packaging'].includes(j.state));
  logById('mapping-refresh').disabled = state.busy || !state.online;
  logById('mapping-prev').disabled = state.busy || !state.online || !state.page;
  logById('mapping-next').disabled = state.busy || !state.online || !state.more;
  logById('mapping-page').textContent = '第 ' + (state.page + 1) + ' 页';
  const runs = logById('mapping-runs'); runs.replaceChildren();
  for (const run of state.runs) {
    const block = logNode('div'); block.className = 'log-job'; const manifest = run.manifest;
    block.append(logNode('p', run.run + ' · ' + (mappingLabels[manifest.status] || manifest.status) + ' · ' + logSize(manifest.total_bytes || 0)));
    if (manifest.reason) block.append(logNode('p', '记录说明：' + manifest.reason));
    block.append(mappingButton('准备整轮下载（含 PCD 导出）', () => mappingPrepare(run.run),
      state.busy || busyTask || !state.online || !state.sourceId || run.active || !run.files.length));
    const details = logNode('details'); details.append(logNode('summary', '已封闭文件与建图信息'));
    for (const file of run.files) {
      const row = logNode('p', file.name + ' · ' + logSize(file.size) + ' ');
      row.append(mappingButton('准备此文件', () => mappingPrepare(run.run, file.name), state.busy || busyTask || !state.online || !state.sourceId)); details.append(row);
    }
    details.append(logNode('pre', JSON.stringify(manifest, null, 2))); block.append(details); runs.append(block);
  }
  if (!state.runs.length) runs.append(logNode('p', state.online ? '本页没有建图记录。板端需配套升级，历史轻量 bag 不会被当作完整建图记录。' : '连接后可查询板端记录。'));
  const jobs = logById('mapping-jobs'); jobs.replaceChildren();
  for (const job of state.jobs.slice().reverse()) {
    const block = logNode('div'); block.className = 'log-job';
    block.append(logNode('p', job.run + ' · ' + job.host + ' ' + (job.board_root || '') + ' · ' + (mappingLabels[job.state] || job.state)));
    block.append(logNode('p', logSize(job.transferred || 0) + ' / ' + logSize(job.total || 0)));
    if (job.error) block.append(logNode('p', job.error));
    for (const warning of job.warnings || []) block.append(logNode('p', warning));
    if (job.state === 'ready') for (const name of job.artifacts) {
      const link = logNode('a', '下载 ' + name); link.className = 'btn'; link.download = name;
      link.href = '/api/mapping-recordings/file?id=' + encodeURIComponent(job.id) + '&name=' + encodeURIComponent(name); block.append(link);
    }
    jobs.append(block);
  }
  if (!state.jobs.length) jobs.append(logNode('p', '暂无本机建图下载任务。'));
}
async function mappingRefresh() {
  if (mappingState.busy) return;
  mappingState.busy = true;
  try {
    const snapshot = await logAPI('/api/snapshot');
    const connection = snapshot.connection || {};
    const source = JSON.stringify([connection.host, connection.board_root]);
    if (source !== mappingState.source) {
      mappingState.generation++; mappingState.page = 0; mappingState.runs = []; mappingState.more = false; mappingState.sourceId = null; mappingState.source = source;
    }
    mappingState.online = connection.state === 'ok'; mappingRender();
    const generation = mappingState.generation;
    mappingState.jobs = (await logAPI('/api/mapping-recordings/jobs')).jobs;
    if (mappingState.online) {
      const result = await logAPI('/api/mapping-recordings/catalog?page=' + mappingState.page);
      if (generation === mappingState.generation) { mappingState.runs = result.runs; mappingState.more = result.has_more; mappingState.sourceId = result.source_id; }
    } else { mappingState.runs = []; mappingState.more = false; mappingState.sourceId = null; }
    logById('mapping-message').textContent = mappingState.online ? '最后查询 ' + new Date().toLocaleTimeString() : '请先连接板端；已准备的本机文件仍可下载。';
  } catch (error) {
    mappingState.runs = []; mappingState.more = false; mappingState.sourceId = null; logById('mapping-message').textContent = '建图记录查询失败：' + error.message;
  } finally { mappingState.busy = false; mappingRender(); }
}
async function mappingPrepare(run, file) {
  if (mappingState.busy || !mappingState.online) return;
  mappingState.busy = true; mappingRender();
  try {
    await logAPI('/api/mapping-recordings/prepare', {run, file, source_id: mappingState.sourceId});
    mappingState.jobs = (await logAPI('/api/mapping-recordings/jobs')).jobs;
    logById('mapping-message').textContent = '任务已提交；正在取回 PC 缓存并验证文件。';
  } catch (error) { logById('mapping-message').textContent = error.message; }
  finally { mappingState.busy = false; mappingRender(); }
}
window.addEventListener('DOMContentLoaded', () => {
  logById('mapping-refresh').onclick = mappingRefresh;
  logById('mapping-prev').onclick = () => { if (mappingState.page) { mappingState.page--; mappingRefresh(); } };
  logById('mapping-next').onclick = () => { if (mappingState.more) { mappingState.page++; mappingRefresh(); } };
  mappingRefresh(); setInterval(() => { if (!document.hidden) mappingRefresh(); }, 5000);
});
