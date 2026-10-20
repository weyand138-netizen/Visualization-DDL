import { dateKey, calendarDays, parseIncome, incomeSummary, remainingSeconds, money, focusSummary, focusDay } from './domain.js';
import { readPending, acknowledgeFocus } from './focus-store.js';
import { accountStorage, accountEventKey } from './account-store.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const categoryNames = { work: '工作', personal: '生活', study: '学习' };
const statusNames = { planned: '待开始', active: '进行中', done: '已完成' };
const viewNames = { overview: '总览', agenda: '日程清单', income: '收入统计', focus: '专注时钟' };
// Inline paths keep icons independent of the operating system's emoji fonts.
const iconPaths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  list: '<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>',
  'trending-up': '<path d="m3 17 6-6 4 4 8-8M15 7h6v6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  settings: '<path d="m9.5 3-.7 2.1-1.7 1L5 5.7 2.5 10l1.5 1.7v2L2.5 15.4 5 19.7l2.1-.4 1.7 1 .7 1.7h5l.7-1.7 1.7-1 2.1.4 2.5-4.3-1.5-1.7v-2l1.5-1.7L19 5.7l-2.1.4-1.7-1-.7-2.1z"/><circle cx="12" cy="12.5" r="3"/>',
  theme: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/>',
  sparkles: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 3v4M18 5h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  'chevron-left': '<path d="m15 5-7 7 7 7"/>',
  'chevron-right': '<path d="m9 5 7 7-7 7"/>',
  'arrow-up-right': '<path d="M6 18 18 6M6 6h12v12"/>',
  reset: '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7"/>',
  play: '<path d="m8 4 12 8-12 8z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
};

function icon(name) {
  return `<svg class="icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${iconPaths[name]}</svg>`;
}

function mountIcons() {
  document.querySelectorAll('[data-icon]').forEach(element => { element.innerHTML = icon(element.dataset.icon); });
}

function renderTimerButton(button, running, label) {
  const name = running ? 'pause' : 'play';
  const next = `${name}:${label}`;
  // The timer ticks four times a second; keep its button DOM stable between states.
  if (button.dataset.timerState === next) return;
  button.dataset.timerState = next;
  button.innerHTML = `${icon(name)}<span>${label}</span>`;
}
let today = dateKey();
let selectedDay = today;
let [year, month] = today.split('-').map(Number);
month -= 1;
let view = 'overview';
let state = { events: [], settings: { theme: 'light', custom: { button: '#486950', background: '#f5f4ef', border: '#dedfd5' }, focusMinutes: 25, dailyFocusGoal: 120 }, focus: [], focusSessions: [] };
let loaded = false;
let toastTimeout;
let timer;
const browserStorage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value),
  removeItem: key => localStorage.removeItem(key), key: index => localStorage.key(index), get length() { return localStorage.length; } };
let accountId;
let focusStorage;
let focusOutbox = [];
let focusStats = focusSummary([], focusOutbox);
let syncingFocus = false;
let settingsSaving = false;
let audio;

function readLocal(key, fallback) {
  try { return JSON.parse(focusStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

function writeLocal(key, value) {
  try { focusStorage.setItem(key, JSON.stringify(value)); } catch { /* The app still works when browser storage is disabled. */ }
}

function notify(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('visible');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => $('#toast').classList.remove('visible'), 3500);
}

async function api(path, method = 'GET', body) {
  const response = await fetch(path, { method, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(accountId ? { 'X-DDL-Account': accountId } : {}) }, body: body ? JSON.stringify(body) : undefined });
  let data;
  try { data = await response.json(); } catch { throw new Error('服务返回异常，请刷新页面重试'); }
  if (response.status === 409 && data.accountMismatch) {
    loaded = false; timer = undefined;
    location.reload();
    throw new Error(data.error);
  }
  if (!response.ok) throw new Error(data.error || '操作失败，请稍后重试');
  return data;
}

async function load() {
  try {
    const next = await api('/api/state');
    const nextAccount = next.account?.id || 'admin';
    if (accountId !== nextAccount) {
      accountId = nextAccount;
      focusStorage = accountStorage(browserStorage, accountId);
      focusOutbox = readPending(focusStorage);
      state.focusSessions = []; timer = undefined;
    }
    const saved = readLocal('ddl-focus-timer', null);
    if (next.focusTimer?.version === 0 && saved && !saved.completed && (saved.running || saved.remaining < saved.total)) {
      try { next.focusTimer = (await api('/api/focus-timer', 'POST', { action: 'adopt', timer: saved })).timer; }
      catch (error) { notify(error.message); }
    }
    acceptState(next);
    loaded = true;
    $('#connection-error').hidden = true;
    applyTheme();
    if (!timer && accountId) restoreTimer();
    render();
    flushFocus();
  } catch (error) {
    $('#connection-error').hidden = false;
    notify(error.message);
    if (!timer && accountId) restoreTimer();
  }
}

function acceptState(next) {
  // Focus is append-only. Keep acknowledged records if an older in-flight GET
  // arrives after a newer response, then reconcile pending ids atomically.
  const records = [...new Map([...(state.focusSessions || []), ...(next.focusSessions || [])].map(record => [record.id, record])).values()];
  state = { ...next, focusSessions: records, settings: { dailyFocusGoal: 120, ...next.settings } };
  if (next.focusTimer && (!timer || next.focusTimer.version >= (timer.version ?? -1))) {
    timer = next.focusTimer; persistTimer();
  }
  $('[data-action="ai"]').hidden = !state.capabilities?.aiPlanning;
  focusOutbox = acknowledgeFocus(focusStorage, records, focusOutbox);
}

function renderFocusViews() {
  focusOutbox = readPending(focusStorage, focusOutbox);
  focusStats = focusSummary(state.focusSessions, focusOutbox);
  renderCalendar(); renderDay(); renderFocusStats();
}

function monthKey() { return `${year}-${String(month + 1).padStart(2, '0')}`; }
function dayEvents(day) { return state.events.filter(event => event.date === day).sort((a, b) => (a.time || '99:99').localeCompare(b.time || '99:99')); }
function isOverdue(event) { return event.status !== 'done' && event.date < today; }

function render() {
  $('#account-name').textContent = state.account?.displayName || '我的日常';
  $('#account-hint').textContent = accountId ? `独立工作台 · ${accountId}` : '正在连接工作台';
  $('#workspace-owner').textContent = accountId ? `我的空间 · ${accountId}` : '我的空间';
  focusOutbox = readPending(focusStorage, focusOutbox);
  focusStats = focusSummary(state.focusSessions, focusOutbox);
  const pending = dayEvents(today).filter(event => event.status !== 'done').length;
  const completed = dayEvents(today).filter(event => event.status === 'done').length;
  $('#today-pending').textContent = pending;
  $('#today-summary').textContent = `已完成 ${completed} 件`;
  $('#nav-count').textContent = state.events.filter(event => event.status !== 'done').length;
  renderCalendar();
  renderDay();
  renderIncome();
  renderAgenda();
  renderFocusStats();
  tick();
}

function renderCalendar() {
  $('#month-label').textContent = `${year} 年 ${month + 1} 月`;
  const count = state.events.filter(event => event.date.startsWith(monthKey())).length;
  $('#calendar-count').textContent = `${count} 项安排`;
  $('#calendar').innerHTML = calendarDays(year, month).map(day => {
    const events = dayEvents(day.key);
    const focus = focusDay(focusStats, day.key);
    return `<div class="calendar-cell ${day.current ? '' : 'outside'} ${day.key === selectedDay ? 'selected' : ''} ${focus.seconds ? 'has-focus' : ''}" data-day="${day.key}" style="--focus-strength:${focus.intensity}">
      <button class="day-number ${day.key === today ? 'today' : ''}" data-select-day="${day.key}" aria-label="${day.key}${events.length ? `，${events.length} 项日程` : ''}" ${day.key === selectedDay ? 'aria-pressed="true"' : 'aria-pressed="false"'}>${day.day}</button>${day.key === today ? '<span class="day-label">今天</span>' : ''}
      <button class="day-add" data-new-day="${day.key}" aria-label="在 ${day.key} 新建日程">${icon('plus')}</button>
      ${events.slice(0, 2).map(event => `<button class="event-pill ${event.category} ${event.status === 'done' ? 'done' : ''}" data-event="${event.id}" title="${escape(event.title)}${event.incomeCents ? ` · ${money(event.incomeCents)}` : ''}">${escape(event.title)}</button>`).join('')}
      ${events.length > 2 ? `<button class="more-events" data-select-day="${day.key}">+${events.length - 2} 项安排</button>` : ''}
    </div>`;
  }).join('');
}

function renderDay() {
  const events = dayEvents(selectedDay);
  const daily = focusDay(focusStats, selectedDay);
  $('#selected-title').innerHTML = `${selectedDay === today ? '今日日程' : `${Number(selectedDay.slice(5, 7))} 月 ${Number(selectedDay.slice(8))} 日`} <span class="count-badge">${events.length}</span>`;
  $('#selected-focus').textContent = daily.sessions ? `专注 ${daily.minutes} 分钟 · 完成 ${daily.sessions} 次 · +${daily.points} 积分` : '暂无专注记录';
  $('#day-events').innerHTML = events.length ? events.map(event => `<div class="day-event ${event.status === 'done' ? 'completed' : ''}">
    <button class="event-check ${event.status === 'done' ? 'checked' : ''}" data-complete="${event.id}" aria-label="${event.status === 'done' ? '重新打开' : '完成'}：${escape(event.title)}">${event.status === 'done' ? icon('check') : ''}</button>
    <button class="day-event-info" data-event="${event.id}"><strong>${escape(event.title)}</strong><small><i class="dot ${event.category}"></i>${event.time || '全天'} · ${categoryNames[event.category]}${event.incomeCents ? `<span class="mini-money">${money(event.incomeCents)}</span>` : ''}</small></button></div>`).join('') : `<div class="empty-day"><p>${loaded ? '暂无日程' : '正在读取日程…'}</p>${loaded ? `<button data-action="new-selected">${icon('plus')}<span>新建日程</span></button>` : ''}</div>`;
}

function emptyList(title, action = true) {
  return `<div class="list-empty"><h3>${title}</h3>${action ? `<button class="button primary" data-action="new">${icon('plus')}<span>新建日程</span></button>` : ''}</div>`;
}

function renderAgenda() {
  const query = $('#agenda-search').value.trim().toLowerCase();
  const filter = $('#agenda-filter').value;
  const events = state.events.filter(event => (`${event.title} ${event.notes}`).toLowerCase().includes(query) && (filter === 'all' || (filter === 'overdue' ? isOverdue(event) : event.status === filter))).sort((a, b) => a.date.localeCompare(b.date) || (a.time || '99').localeCompare(b.time || '99'));
  $('#agenda-list').innerHTML = events.length ? events.map(event => `<div class="agenda-row">
    <button class="event-check ${event.status === 'done' ? 'checked' : ''}" data-complete="${event.id}" aria-label="${event.status === 'done' ? '重新打开' : '完成'}：${escape(event.title)}">${event.status === 'done' ? icon('check') : ''}</button>
    <button class="row-info" data-event="${event.id}"><strong>${escape(event.title)}</strong><small><i class="dot ${event.category}"></i> ${categoryNames[event.category]} · ${event.date} · ${event.time || '全天'}</small></button>
    <div class="row-meta"><span class="status-tag ${isOverdue(event) ? 'overdue' : event.status}">${isOverdue(event) ? '已逾期' : statusNames[event.status]}</span><span>${event.incomeCents ? money(event.incomeCents) : '—'}</span><button class="icon-button" data-event="${event.id}" aria-label="查看 ${escape(event.title)}">${icon('arrow-up-right')}</button></div></div>`).join('') : emptyList(query || filter !== 'all' ? '无匹配日程' : '暂无日程', !query && filter === 'all');
}

function renderIncome() {
  const summary = incomeSummary(state.events, monthKey());
  $('#income-period').textContent = `${year} 年 ${month + 1} 月`;
  $('#income-paid').textContent = money(summary.paid);
  $('#income-pending').textContent = money(summary.pending);
  const period = $('#income-month').value || monthKey();
  const total = incomeSummary(state.events, period);
  $('#total-expected').textContent = money(total.expected);
  $('#total-paid').textContent = money(total.paid);
  $('#total-pending').textContent = money(total.pending);
  const events = state.events.filter(event => event.date.startsWith(period) && event.incomeCents > 0).sort((a, b) => b.date.localeCompare(a.date));
  $('#income-list').innerHTML = events.length ? events.map(event => `<div class="agenda-row"><button class="row-info" data-event="${event.id}"><strong>${escape(event.title)}</strong><small>${event.date} · ${categoryNames[event.category]}</small></button><div class="row-meta"><span>${money(event.incomeCents)}</span><span class="status-tag ${event.payment === 'paid' ? 'paid' : ''}">${event.payment === 'paid' ? '已到账' : '待到账'}</span><button class="icon-button" data-event="${event.id}" aria-label="查看收入详情">${icon('arrow-up-right')}</button></div></div>`).join('') : emptyList('暂无收入记录');
}

function setView(next) {
  if (!viewNames[next]) return;
  view = next;
  for (const name of Object.keys(viewNames)) $(`#${name}-view`).hidden = name !== view;
  $('#clock-banner').hidden = view !== 'overview';
  $('#page-name').textContent = viewNames[view];
  $('#page-title').textContent = viewNames[view];
  document.querySelectorAll('.nav-item[data-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  if (view === 'income') { $('#income-month').value = monthKey(); renderIncome(); }
  window.scrollTo({ top: 0, behavior: 'instant' });
}

function selectDay(key) {
  selectedDay = key;
  [year, month] = key.split('-').map(Number);
  month -= 1;
  renderCalendar(); renderDay(); renderIncome();
}

function changeMonth(delta) {
  const date = new Date(year, month + delta, 1, 12);
  if (date.getFullYear() < 1900 || date.getFullYear() > 2100) return;
  year = date.getFullYear(); month = date.getMonth();
  selectedDay = `${monthKey()}-01`;
  renderCalendar(); renderDay(); renderIncome();
}

function modal(title, kicker, body, actions, formId = '') {
  $('#modal-content').innerHTML = `${formId ? `<form id="${formId}">` : ''}<div class="modal-header"><div><div class="section-kicker">${kicker}</div><h2 id="modal-title">${title}</h2></div><button type="button" class="icon-button" data-action="close" aria-label="关闭">${icon('close')}</button></div>${body}<div class="modal-actions">${actions}</div>${formId ? '</form>' : ''}`;
  if (!$('#modal').open) $('#modal').showModal();
}

function openAI() {
  if (!loaded) { notify('请等待数据加载完成'); return; }
  modal('AI 整理日程', 'A LITTLE HELP WITH YOUR PLANS', `<div class="modal-body"><div class="form-grid">
    <label class="form-field full">描述你的安排<textarea name="text" maxlength="6000" rows="4" placeholder="例如：明天下午3点交设计初稿，收入1200元，暂未到账。也可以查询、修改已有日程。"></textarea></label>
    <label class="form-field full">安排截图（可选，最多3张）<input name="images" type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
    </div><p class="settings-caption">文字和图片将由已连接的 AstrBot 模型处理，整理后可先检查日期、金额和详细内容。</p><div id="ai-preview" aria-live="polite"></div><p class="form-error" role="alert"></p></div>`, '<button type="button" class="button quiet" data-action="close">取消</button><button type="submit" class="button primary">整理安排</button>', 'ai-form');
  const form = $('#ai-form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const submit = form.querySelector('[type=submit]');
    const errorBox = form.querySelector('.form-error');
    try {
      errorBox.textContent = '';
      $('#ai-preview').replaceChildren();
      form.querySelector('#ai-save')?.remove();
      const files = [...form.elements.images.files];
      if (files.length > 3 || files.reduce((sum, file) => sum + file.size, 0) > 5 * 1024 * 1024) throw new Error('请上传最多3张图片，总大小不超过5MB');
      if (files.some(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type))) throw new Error('支持 PNG、JPEG、WebP 图片');
      const text = form.elements.text.value.trim();
      if (!text && !files.length) throw new Error('请描述安排或选择截图');
      submit.disabled = true; submit.textContent = '正在整理…';
      const images = await Promise.all(files.map(file => new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file);
      })));
      const plan = await api('/api/ai/plan', 'POST', { text, images });
      if (!form.isConnected) return;
      if (!Array.isArray(plan.actions) || typeof plan.reply !== 'string') throw new Error('识别结果不完整，请重试');
      $('#ai-preview').innerHTML = `<p class="detail-notes">${escape(plan.reply)}</p>` + plan.actions.map(action => {
        const event = action.op === 'delete' ? state.events.find(item => item.id === action.id) : action.event;
        if (!event || !['create', 'update', 'delete'].includes(action.op)) throw new Error('识别结果不完整，请重试');
        return `<article class="ai-plan-item"><strong>${{ create: '添加', update: '修改', delete: '删除' }[action.op]} · ${escape(event.title)}</strong><p>${escape(event.date)} ${escape(event.time || '全天')} · ${escape(categoryNames[event.category] || '')} · ${escape(statusNames[event.status] || '')}</p><p>${money(event.incomeCents)} · ${event.payment === 'paid' ? '已到账' : '待到账'}</p><div class="detail-notes">${escape(event.notes)}</div></article>`;
      }).join('');
      if (plan.actions.length) {
        const requestId = crypto.randomUUID();
        const save = document.createElement('button');
        save.id = 'ai-save'; save.type = 'button'; save.className = 'button primary'; save.textContent = `确认保存 ${plan.actions.length} 项操作`;
        form.querySelector('.modal-actions').append(save);
        save.addEventListener('click', async () => {
          save.disabled = true; submit.disabled = true;
          try {
            await api('/api/events/batch', 'POST', { requestId, actions: plan.actions });
            if (form.isConnected) $('#modal').close();
            await load(); notify('安排已保存到日历');
          } catch (error) { errorBox.textContent = error.message; save.disabled = false; }
          finally { submit.disabled = false; }
        });
      }
    } catch (error) { if (form.isConnected) errorBox.textContent = error.message; }
    finally { submit.disabled = false; submit.textContent = '重新整理'; }
  });
}

function openEventForm(id, date = selectedDay) {
  if (!loaded) { notify('请等待数据加载完成'); return; }
  const event = id ? state.events.find(item => item.id === id) : { title: '', date, time: '', category: 'work', status: 'planned', incomeCents: 0, payment: 'pending', notes: '' };
  if (!event) { notify('这条日程已不存在'); return; }
  modal(id ? '编辑日程' : '新建日程', 'MAKE ROOM FOR WHAT MATTERS', `<div class="modal-body"><div class="form-grid">
    <label class="form-field full">日程标题 <input name="title" required maxlength="120" placeholder="例如：完成品牌设计初稿" value="${escape(event.title)}" autofocus></label>
    <label class="form-field">日期 / 截止日期<input type="date" name="date" required value="${event.date}"></label>
    <label class="form-field"><span>时间 <small class="field-note">不填即为全天</small></span><input type="time" name="time" value="${event.time}"></label>
    <label class="form-field">分类<select name="category">${Object.entries(categoryNames).map(([value, label]) => `<option value="${value}" ${event.category === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
    <label class="form-field">进度<select name="status">${Object.entries(statusNames).map(([value, label]) => `<option value="${value}" ${event.status === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
    <label class="form-field">关联收入（元）<input type="number" name="income" min="0" max="999999999.99" step="0.01" inputmode="decimal" required value="${(event.incomeCents / 100).toFixed(2)}"></label>
    <label class="form-field">到账状态<select name="payment"><option value="pending" ${event.payment === 'pending' ? 'selected' : ''}>待到账</option><option value="paid" ${event.payment === 'paid' ? 'selected' : ''}>已到账</option></select></label>
    <label class="form-field full">详细说明<textarea name="notes" maxlength="10000" rows="4" placeholder="具体要求或交付内容（可选）">${escape(event.notes)}</textarea></label>
    </div><p class="form-error" role="alert"></p></div>`, `${id ? `<button type="button" class="button danger" data-delete="${id}">删除日程</button>` : ''}<button type="button" class="button quiet" data-action="close">取消</button><button type="submit" class="button primary">保存日程</button>`, 'event-form');
  $('#event-form').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const submit = form.querySelector('[type=submit]');
    try {
      const incomeCents = parseIncome(values.income);
      submit.disabled = true;
      const payload = { title: values.title.trim(), date: values.date, time: values.time, category: values.category, status: values.status, payment: values.payment, notes: values.notes, incomeCents };
      const result = await api(`/api/events${id ? `/${id}` : ''}`, id ? 'PUT' : 'POST', payload);
      if (id) state.events = state.events.map(item => item.id === id ? { ...item, ...payload } : item);
      else state.events.push(result);
      selectDay(payload.date); render(); $('#modal').close(); notify(id ? '日程已更新' : '日程已创建');
    } catch (error) { form.querySelector('.form-error').textContent = error.message; }
    finally { submit.disabled = false; }
  });
}

function openDetail(id) {
  const event = state.events.find(item => item.id === id);
  if (!event) return;
  modal('日程详情', 'A LITTLE PLAN FOR YOUR DAY', `<div class="modal-body"><h3 class="detail-title">${escape(event.title)}</h3><div class="detail-grid">
    <div><small>日期</small><span>${event.date} · ${event.time || '全天'}</span></div><div><small>分类</small><span><i class="dot ${event.category}"></i> ${categoryNames[event.category]}</span></div>
    <div><small>进度</small><span class="${event.status === 'done' ? 'done-label' : ''}">${statusNames[event.status]}${isOverdue(event) ? ' · 已逾期' : ''}</span></div><div><small>关联收入</small><span>${money(event.incomeCents)} · ${event.payment === 'paid' ? '已到账' : '待到账'}</span></div></div>
    <p class="details-label">详细说明</p><div class="detail-notes ${event.notes ? '' : 'empty'}">${escape(event.notes || '无')}</div></div>`, `<button class="button quiet" data-action="close">关闭</button><button class="button primary" data-edit="${id}">编辑日程</button>`);
}

function confirmDelete(id) {
  const event = state.events.find(item => item.id === id);
  if (!event) return;
  modal('删除这条日程？', 'TAKE A MOMENT', `<div class="modal-body"><p class="detail-notes">${escape(event.title)}</p><p class="settings-caption">关联收入也会从统计中移除，此操作无法撤销。</p><p class="form-error" role="alert"></p></div>`, `<button class="button quiet" data-edit="${id}">保留日程</button><button class="button danger" id="confirm-delete">确认删除</button>`);
  $('#confirm-delete').addEventListener('click', async e => {
    e.currentTarget.disabled = true;
    try { await api(`/api/events/${id}`, 'DELETE'); state.events = state.events.filter(item => item.id !== id); render(); $('#modal').close(); notify('日程已删除'); }
    catch (error) { $('#modal .form-error').textContent = error.message; if ($('#confirm-delete')) $('#confirm-delete').disabled = false; }
  });
}

async function completeEvent(id, button) {
  const event = state.events.find(item => item.id === id);
  if (!event) return;
  button.disabled = true;
  const updated = { ...event, status: event.status === 'done' ? 'planned' : 'done' };
  try {
    await api(`/api/events/${id}`, 'PUT', updated);
    state.events = state.events.map(item => item.id === id ? updated : item);
    render(); notify(updated.status === 'done' ? '日程已完成' : '日程已重新打开');
  } catch (error) { notify(error.message); button.disabled = false; }
}

function readableColor(hex) {
  const rgb = hex.match(/[a-f\d]{2}/gi).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  const luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  return { dark: luminance < .18, text: luminance > .179 ? '#172018' : '#ffffff' };
}

function applyTheme(settings = state.settings) {
  const root = document.documentElement;
  const properties = ['--bg', '--surface', '--sidebar', '--text', '--muted', '--border', '--accent', '--accent-text', '--soft', '--hover', '--focus-track'];
  properties.forEach(property => root.style.removeProperty(property));
  root.dataset.theme = settings.theme;
  const custom = settings.custom;
  root.style.setProperty('--custom-bg', custom.background);
  root.style.setProperty('--custom-button', custom.button);
  root.style.setProperty('--custom-border', custom.border);
  if (settings.theme === 'custom') {
    const dark = readableColor(custom.background).dark;
    root.style.setProperty('--bg', custom.background);
    root.style.setProperty('--surface', `color-mix(in srgb, ${custom.background} 82%, #ffffff)`);
    root.style.setProperty('--sidebar', `color-mix(in srgb, ${custom.background} 95%, ${dark ? '#ffffff' : '#000000'})`);
    root.style.setProperty('--text', dark ? '#e8ece5' : '#28342d');
    root.style.setProperty('--muted', dark ? '#a9b3a6' : '#6d786e');
    root.style.setProperty('--border', custom.border);
    root.style.setProperty('--accent', custom.button);
    root.style.setProperty('--accent-text', readableColor(custom.button).text);
    root.style.setProperty('--soft', `color-mix(in srgb, ${custom.button} ${dark ? '18%' : '9%'}, ${custom.background})`);
    root.style.setProperty('--hover', `color-mix(in srgb, ${custom.button} 12%, ${custom.background})`);
    root.style.setProperty('--focus-track', `color-mix(in srgb, ${custom.border} 50%, ${custom.background})`);
    root.style.colorScheme = dark ? 'dark' : 'light';
  } else root.style.removeProperty('color-scheme');
  $('meta[name=theme-color]').content = settings.theme === 'dark' ? '#13151a' : settings.theme === 'custom' ? custom.background : '#f5f4ef';
  const colors = getComputedStyle(root);
  const icon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="19" fill="${colors.getPropertyValue('--accent').trim()}"/><path d="M19 17h12c22 0 22 30 0 30H19z" fill="none" stroke="${colors.getPropertyValue('--accent-text').trim()}" stroke-width="6"/><path d="m27 32 5 5 11-13" fill="none" stroke="${colors.getPropertyValue('--accent-text').trim()}" opacity=".75" stroke-width="4"/></svg>`;
  $('link[rel=icon]').href = `data:image/svg+xml,${encodeURIComponent(icon)}`;
}

async function saveSettings(settings) {
  if (!loaded) throw new Error('请先等待数据加载完成');
  const saved = await api('/api/settings', 'PUT', settings);
  state.settings = { dailyFocusGoal: 120, ...saved }; applyTheme(); renderFocusViews();
}

function openSettings() {
  if (!loaded) { notify('请等待数据加载完成'); return; }
  const draft = structuredClone(state.settings);
  modal('外观与设置', 'YOUR SPACE, YOUR WAY', `<div class="modal-body"><p class="settings-section-title">选择外观</p><div class="theme-options">${[['light', '明亮'], ['dark', '暗色'], ['custom', '个性化']].map(([value, label]) => `<label class="theme-option"><div class="theme-swatch ${value}"></div><input type="radio" name="theme" value="${value}" ${draft.theme === value ? 'checked' : ''}>${label}</label>`).join('')}</div>
    <p class="settings-section-title">个性化配色</p><div class="color-fields">${[['button', '按键颜色'], ['background', '背景主题颜色'], ['border', '描边颜色']].map(([key, label]) => `<label class="color-row">${label}<span class="color-control"><input type="color" name="${key}" value="${draft.custom[key]}"><output id="color-${key}">${draft.custom[key].toUpperCase()}</output></span></label>`).join('')}</div>
    <div class="daily-goal-settings"><p class="settings-section-title">每日专注目标</p><label class="form-field">目标时长（分钟）<input name="dailyFocusGoal" type="number" min="1" max="1440" step="1" required value="${draft.dailyFocusGoal}"></label><button type="button" class="button small quiet" data-action="duration">单次计时时长 · ${state.settings.focusMinutes} 分钟</button></div>
    <p class="settings-footer-note">配色会即时预览，点击保存后生效。</p><p class="form-error" role="alert"></p></div>`, '<button type="button" class="button quiet" data-action="close">取消</button><button type="submit" class="button primary">保存设置</button>', 'settings-form');
  const form = $('#settings-form');
  const preview = () => {
    const values = Object.fromEntries(new FormData(form));
    draft.theme = values.theme;
    draft.custom = { button: values.button, background: values.background, border: values.border };
    draft.dailyFocusGoal = Number(values.dailyFocusGoal);
    Object.entries(draft.custom).forEach(([key, color]) => $(`#color-${key}`).textContent = color.toUpperCase());
    applyTheme(draft);
  };
  form.addEventListener('input', e => {
    if (e.target.type === 'color') form.querySelector('[value=custom]').checked = true;
    preview();
  });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const submit = form.querySelector('[type=submit]'); submit.disabled = true;
    try { preview(); await saveSettings(draft); $('#modal').close(); notify('设置已保存'); }
    catch (error) { form.querySelector('.form-error').textContent = error.message; }
    finally { submit.disabled = false; }
  });
}

function freshTimer(minutes) {
  // getRandomValues also works on a self-hosted HTTP origin, before HTTPS is configured.
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  return { id, total: minutes * 60, remaining: minutes * 60, running: false, deadline: 0, completed: false };
}
function persistTimer() { writeLocal('ddl-focus-timer', timer); }
function restoreTimer() {
  if (Number.isInteger(timer?.version)) return;
  const saved = readLocal('ddl-focus-timer', null);
  timer = saved && typeof saved.id === 'string' && Number.isFinite(saved.total) && saved.total >= 60 && saved.total <= 14400 && Number.isFinite(saved.remaining) && saved.remaining >= 0 && saved.remaining <= saved.total && typeof saved.running === 'boolean' && Number.isFinite(saved.deadline) ? saved : freshTimer(state.settings.focusMinutes);
}

async function toggleTimer() {
  if (!loaded) { notify('请等待数据加载完成'); return; }
  if (!audio) {
    try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { /* Sound is optional. */ }
  }
  if (audio?.state === 'suspended') audio.resume().catch(() => {});
  await controlTimer(timer.running ? 'pause' : timer.completed || timer.remaining === timer.total ? 'start' : 'resume');
}

async function resetTimer() {
  if (timer?.running || (timer && timer.remaining !== timer.total && !timer.completed)) {
    modal('重新开始这一段专注？', 'A FRESH START', '<div class="modal-body"><p class="settings-caption">当前计时会清零；未完成的专注不会计入今日统计。</p></div>', '<button class="button quiet" data-action="close">继续当前计时</button><button class="button primary" id="confirm-reset">重新开始</button>');
    $('#confirm-reset').addEventListener('click', async () => {
      try { await controlTimer('reset'); $('#modal').close(); } catch (error) { notify(error.message); }
    });
  } else { await controlTimer('reset'); }
}

async function setDuration(minutes) {
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 240) throw new Error('请输入 1–240 之间的整数分钟');
  if (timer.running || (remainingSeconds(timer) !== timer.total && !timer.completed)) throw new Error('请先重置当前专注，再修改时长');
  if (settingsSaving) throw new Error('正在保存设置，请稍候');
  settingsSaving = true;
  try {
    await controlTimer('configure', { durationMinutes: minutes });
    state.settings.focusMinutes = minutes;
  } finally { settingsSaving = false; }
}

function openDuration() {
  modal('专注时长', 'MAKE TIME FOR FOCUS', `<div class="modal-body duration-body"><label class="form-field">专注时长（分钟）<input class="duration-input" type="number" name="minutes" min="1" max="240" step="1" required value="${timer.total / 60}" autofocus></label><div class="focus-presets"><button type="button" class="button quiet" data-duration-preset="15">15 分钟</button><button type="button" class="button quiet" data-duration-preset="25">25 分钟</button><button type="button" class="button quiet" data-duration-preset="45">45 分钟</button></div><p class="settings-caption">支持 1–240 分钟。修改前请先重置正在进行的专注。</p><p class="form-error" role="alert"></p></div>`, '<button type="button" class="button quiet" data-action="close">取消</button><button type="submit" class="button primary">应用时长</button>', 'duration-form');
  $('#duration-form').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.currentTarget; const button = form.querySelector('[type=submit]'); button.disabled = true;
    try { await setDuration(Number(new FormData(form).get('minutes'))); $('#modal').close(); notify('专注时长已更新'); }
    catch (error) { form.querySelector('.form-error').textContent = error.message; }
    finally { button.disabled = false; }
  });
}

let timerSyncing = false;
async function controlTimer(action, options = {}) {
  const value = await api('/api/focus-timer', 'POST', { action, expectedVersion: timer.version, ...options });
  if (value.timer.version >= timer.version) timer = value.timer;
  persistTimer(); tick();
}

async function syncTimer() {
  if (!loaded || timerSyncing || document.hidden) return;
  timerSyncing = true;
  try {
    const value = await api('/api/focus-timer');
    const justCompleted = value.timer.completed && value.timer.id === timer?.id && !timer.completed;
    if (!timer || value.timer.version >= timer.version) timer = value.timer;
    persistTimer(); tick();
    if (justCompleted) {
      notify('专注已完成'); acceptState(await api('/api/state')); render();
      if (audio) {
        const oscillator = audio.createOscillator(); const gain = audio.createGain();
        oscillator.connect(gain); gain.connect(audio.destination); oscillator.frequency.value = 660;
        gain.gain.setValueAtTime(.08, audio.currentTime); gain.gain.exponentialRampToValueAtTime(.001, audio.currentTime + .8);
        oscillator.start(); oscillator.stop(audio.currentTime + .8);
      }
    }
  } catch { /* Keep displaying the last server deadline during a temporary outage. */ }
  finally { timerSyncing = false; }
}

async function flushFocus() {
  focusOutbox = readPending(focusStorage, focusOutbox);
  if (syncingFocus || !loaded || !focusOutbox.length) return;
  syncingFocus = true;
  try {
    for (const session of [...focusOutbox]) {
      await api('/api/focus', 'POST', session);
    }
    acceptState(await api('/api/state'));
    renderFocusViews();
  } catch { /* Keep the outbox until reconnection; session ids make retries idempotent. */ }
  finally { syncingFocus = false; }
}

function renderFocusStats() {
  const daily = focusDay(focusStats, today, state.settings.dailyFocusGoal);
  $('#focus-goal-value').textContent = `${daily.minutes} / ${state.settings.dailyFocusGoal} 分钟`;
  $('#focus-goal-bar').style.width = `${daily.ratio * 100}%`;
  $('#focus-goal-progress').setAttribute('aria-valuenow', daily.percent);
  $('#focus-goal-progress').setAttribute('aria-valuetext', `今日专注 ${daily.minutes} 分钟，目标 ${state.settings.dailyFocusGoal} 分钟`);
  $('#focus-goal-percent').textContent = `已完成 ${daily.percent}%`;
  $('#focus-goal-remaining').textContent = daily.ratio === 1 ? '今日目标已完成' : `还差 ${daily.remainingMinutes} 分钟`;
  $('#focus-points-today').textContent = `今日 +${daily.points} 积分`;
  $('#focus-points-total').textContent = `累计 ${focusStats.points}`;
  $('#focus-page-stats').textContent = `今天已完成 ${daily.sessions} 次专注，共 ${daily.minutes} 分钟 · +${daily.points} 积分。`;
}

function tick() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(now).split(':');
  $('#clock-hm').textContent = `${parts[0]}:${parts[1]}`;
  $('#clock-ss').textContent = parts[2];
  const currentDay = dateKey(now);
  $('#clock-date').textContent = `${currentDay.replaceAll('-', ' . ')}　${new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', weekday: 'long' }).format(now)}`;
  $('#header-date').textContent = `${currentDay.replaceAll('-', ' / ')}　${new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', weekday: 'short' }).format(now)}`;
  if (currentDay !== today) { const wasToday = selectedDay === today; today = currentDay; if (wasToday) selectDay(today); render(); return; }
  if (!timer) return;
  let seconds = remainingSeconds(timer);
  if (timer.running && seconds === 0) syncTimer();
  const formatted = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('#focus-time').textContent = formatted;
  $('#focus-page-time').textContent = formatted;
  $('#focus-label').textContent = timer.completed ? '已完成' : timer.running ? '专注中' : seconds !== timer.total ? '已暂停' : '未开始';
  $('#focus-duration').textContent = `${timer.total / 60} 分钟 · ${timer.running ? '正在专注' : '专注时间'}`;
  const timerLabel = timer.running ? '暂停专注' : timer.completed ? '再次专注' : seconds !== timer.total ? '继续专注' : '开始专注';
  renderTimerButton($('#focus-toggle'), timer.running, timerLabel);
  renderTimerButton($('#focus-page-toggle'), timer.running, timerLabel);
  $('#focus-dial').style.setProperty('--progress', `${(1 - seconds / timer.total) * 360}deg`);
  document.querySelectorAll('[data-minutes]').forEach(button => button.classList.toggle('selected', Number(button.dataset.minutes) === timer.total / 60));
  document.title = timer.running ? `${formatted} · 专注中 — DDL` : 'DDL';
}

document.addEventListener('click', async e => {
  const button = e.target.closest('button');
  try {
    if (button?.dataset.view) { setView(button.dataset.view); return; }
    if (button?.dataset.event) { openDetail(button.dataset.event); return; }
    if (button?.dataset.edit) { openEventForm(button.dataset.edit); return; }
    if (button?.dataset.delete) { confirmDelete(button.dataset.delete); return; }
    if (button?.dataset.complete) { await completeEvent(button.dataset.complete, button); return; }
    if (button?.dataset.newDay) { openEventForm(null, button.dataset.newDay); return; }
    if (button?.dataset.selectDay) { selectDay(button.dataset.selectDay); return; }
    if (button?.dataset.durationPreset) { $('#duration-form [name=minutes]').value = button.dataset.durationPreset; return; }
    if (button?.dataset.minutes) { await setDuration(Number(button.dataset.minutes)); notify('专注时长已更新'); return; }
    switch (button?.dataset.action) {
      case 'new': openEventForm(null, today); return;
      case 'ai': openAI(); return;
      case 'new-selected': openEventForm(null, selectedDay); return;
      case 'close': $('#modal').close(); return;
      case 'settings': openSettings(); return;
      case 'duration': openDuration(); return;
      case 'toggle-timer': await toggleTimer(); return;
      case 'reset-timer': await resetTimer(); return;
      case 'prev-month': changeMonth(-1); return;
      case 'next-month': changeMonth(1); return;
      case 'today': selectDay(today); return;
      case 'reload': await load(); return;
      case 'theme-toggle':
        if (settingsSaving) return;
        settingsSaving = true;
        try { await saveSettings({ ...state.settings, theme: state.settings.theme === 'dark' ? 'light' : 'dark' }); notify(state.settings.theme === 'dark' ? '已切换为暗色' : '已切换为明亮'); }
        finally { settingsSaving = false; }
        return;
    }
    const cell = e.target.closest('[data-day]');
    if (cell) selectDay(cell.dataset.day);
  } catch (error) { notify(error.message); }
});

$('#agenda-search').addEventListener('input', renderAgenda);
$('#agenda-filter').addEventListener('change', renderAgenda);
$('#income-month').value = monthKey();
$('#income-month').addEventListener('change', renderIncome);
$('#modal').addEventListener('close', () => applyTheme());
$('#modal').addEventListener('click', e => { if (e.target === $('#modal')) { const rect = $('#modal').getBoundingClientRect(); if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) $('#modal').close(); } });
window.addEventListener('online', () => { flushFocus(); syncRemote(); if (!loaded) load(); });
window.addEventListener('storage', e => {
  if (!accountId) return;
  const key = accountEventKey(accountId, e.key);
  if (key === undefined) return;
  if (key === 'ddl-focus-timer') syncTimer();
  if (key === 'ddl-focus-outbox' || key?.startsWith('ddl-focus-pending:') || key === null) {
    renderFocusViews(); flushFocus();
  }
});
async function syncRemote() {
  if (!loaded || document.hidden || $('#modal').open || settingsSaving) return;
  try { acceptState(await api('/api/state')); applyTheme(); render(); } catch { /* Keep the current view during a temporary outage. */ }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) { tick(); flushFocus(); syncRemote(); } });
setInterval(syncRemote, 15000);
setInterval(syncTimer, 2000);
setInterval(tick, 250);
setInterval(flushFocus, 30000);
mountIcons();
renderCalendar(); renderDay(); tick();
load();
