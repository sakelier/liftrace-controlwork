/* Optional PC mirror controls. Flight commands remain in app.js. */
(function () {
  'use strict';
  var job = null, busy = false;
  function byId(id) { return document.getElementById(id); }
  function size(n) { return (Number(n || 0) / 1048576).toFixed(1) + ' MiB'; }
  function active() { return job && ['waiting', 'syncing', 'finishing', 'retrying', 'pausing'].indexOf(job.state) >= 0; }
  function render() {
    var status = byId('flight-sync-status');
    if (!status) return;
    if (!job) {
      status.textContent = '默认关闭。勾选后随下一次 flight 启动；确认本轮日志目录后持续同步。';
      byId('flight-sync-directory').textContent = '';
    } else {
      var files = Object.keys(job.files || {}).map(function (name) { return job.files[name]; });
      var received = files.reduce(function (n, f) { return n + f.received; }, 0);
      var total = files.reduce(function (n, f) { return n + f.size; }, 0);
      var complete = files.filter(function (f) { return f.complete; }).length;
      var labels = {waiting: '等待日志目录', syncing: '飞行日志同步中', finishing: '封闭后校验与补齐',
        retrying: '连接重试中', pausing: '正在暂停', paused: '已暂停', complete: '同步完成'};
      status.textContent = (labels[job.state] || job.state) + ' · 已写入 PC ' + size(received) +
        ' / 当前源文件 ' + size(total) + ' · 已校验 ' + complete + '/' + files.length + ' 个文件 · ' + job.detail;
      byId('flight-sync-directory').textContent = 'PC 保存目录：' + job.local_directory;
    }
    byId('flight-sync-pause').disabled = busy || !active();
    byId('flight-sync-resume').disabled = busy || !job || job.state !== 'paused';
    byId('flight-sync-replay').hidden = !job;
  }
  async function request(path, body) {
    var response = await fetch('/api/flight-sync/' + path, body === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    var data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || '同步状态查询失败');
    job = data.job; render();
  }
  async function refresh() {
    if (busy) return;
    try { await request('status'); }
    catch (error) { byId('flight-sync-status').textContent = error.message; }
  }
  async function action(path) {
    busy = true; render();
    try { await request(path, {id: job && job.id}); }
    catch (error) { byId('flight-sync-status').textContent = error.message; }
    finally { busy = false; }
  }
  window.FlightLogSync = {
    options: function () {
      var enabled = byId('flight-sync-enabled');
      return {sync_logs: !!(enabled && enabled.checked), sync_rate_kib: Number(byId('flight-sync-rate').value)};
    }
  };
  function init() {
    if (!byId('flight-sync-status')) return;
    byId('flight-sync-pause').onclick = function () { action('pause'); };
    byId('flight-sync-resume').onclick = function () { action('resume'); };
    refresh(); window.setInterval(refresh, 3000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
