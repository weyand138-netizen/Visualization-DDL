import { remainingSeconds } from './domain.js';
import { connectAppearance, widgetToken } from './widget.js';

const $ = selector => document.querySelector(selector);
const token = widgetToken('focus');
connectAppearance();
let timer, account, busy = false, polling = false;

async function request(payload) {
  const response = await fetch('/api/focus-timer', {
    method: payload ? 'POST' : 'GET',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(account ? { 'X-DDL-Account': account } : {}),
      ...(payload ? { 'Content-Type': 'application/json' } : {}) },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '计时器连接失败');
  account = value.account;
  if (!timer || value.timer.version >= timer.version) timer = value.timer;
  $('#error').hidden = true;
  render();
}

function render() {
  if (!timer) return;
  const seconds = remainingSeconds(timer);
  $('#task').textContent = timer.title;
  $('#task').hidden = !timer.title;
  $('#time').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('#dial').style.setProperty('--progress', `${Math.max(0, Math.min(1, seconds / timer.total)) * 360}deg`);
  $('#status').textContent = timer.completed ? '已完成' : timer.running ? '专注中' : seconds < timer.total ? '已暂停' : '未开始';
  $('#toggle').textContent = timer.running ? '暂停' : timer.completed ? '再来一次' : seconds < timer.total ? '继续' : '开始';
  $('#toggle').disabled = busy;
  $('#reset').disabled = busy;
}

function showError(error) { $('#error').textContent = error.message; $('#error').hidden = false; }

async function command(action) {
  if (!timer || busy) return;
  busy = true; render();
  try { await request({ action, expectedVersion: timer.version }); }
  catch (error) { showError(error); }
  finally { busy = false; render(); }
}

$('#toggle').addEventListener('click', () => command(timer.running ? 'pause' : timer.completed || timer.remaining === timer.total ? 'start' : 'resume'));
$('#reset').addEventListener('click', () => command('reset'));
async function poll() {
  if (polling || busy) return;
  polling = true;
  try { await request(); } catch (error) { showError(error); }
  finally { polling = false; }
}
setInterval(render, 250);
setInterval(poll, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
poll();
