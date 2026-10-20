import { dateKey, money } from './domain.js';
import { dayEvents, isCalendarDate, monthView, shiftMonth } from './calendar-view.js';
import { connectAppearance, widgetToken } from './widget.js';

const $ = selector => document.querySelector(selector);
const token = widgetToken('calendar');
connectAppearance();
const initial = new URLSearchParams(location.search).get('date');
let today = dateKey(), selected = isCalendarDate(initial) ? initial : today;
let events = [], detailId = null, loadedRange = '', account, controller, expired = false;
const categories = {work: '工作', personal: '生活', study: '学习'};
const statuses = {planned: '待开始', active: '进行中', done: '已完成'};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function message(text = '', retry = false) { $('#message').textContent = text; $('#retry').hidden = !retry; }
function range() {
  const days = monthView(selected, [], today);
  return new URLSearchParams({date_from: days[0].key, date_to: days[41].key}).toString();
}
function render() {
  const [year, month, day] = selected.split('-').map(Number);
  $('#month-label').textContent = `${year} 年 ${month} 月`;
  $('#month-view').hidden = !!detailId;
  $('#agenda').hidden = !!detailId;
  $('#details').hidden = !detailId;
  $('#calendar').replaceChildren(...monthView(selected, events, today).map(date => {
    const button = element('button', undefined, ['calendar-day', !date.current && 'outside', date.today && 'today', date.selected && 'selected'].filter(Boolean).join(' '));
    button.type = 'button'; button.dataset.day = date.key;
    button.setAttribute('aria-label', `${date.key}，${date.count} 项日程`);
    button.setAttribute('aria-pressed', String(date.selected));
    button.append(element('span', date.day));
    if (date.count) button.append(element('span', `${date.count} 项`, 'day-badge'));
    return button;
  }));
  const daily = dayEvents(events, selected);
  $('#day-label').textContent = selected === today ? '今日日程' : `${month} 月 ${day} 日日程`;
  $('#day-count').textContent = `${daily.length} 项`;
  $('#events').replaceChildren(...daily.map(event => {
    const button = element('button', undefined, `event${event.status === 'done' ? ' done' : ''}`);
    button.type = 'button'; button.dataset.event = event.id;
    button.append(element('time', event.time || '全天'));
    const info = element('span');
    info.append(element('strong', event.title), element('small', `${categories[event.category]} · ${statuses[event.status]}`));
    button.append(info); return button;
  }));
  if (!daily.length) $('#events').append(element('p', loadedRange === range() ? '当天暂无日程' : '正在读取日程…', 'empty'));
  const detail = detailId && events.find(event => event.id === detailId);
  if (detail) {
    const meta = element('div', undefined, 'detail-meta');
    const fields = [['日期', detail.date], ['时间', detail.time || '全天'], ['分类', categories[detail.category]], ['状态', statuses[detail.status]]];
    if (detail.incomeCents) fields.push(['金额', money(detail.incomeCents)], ['收款', detail.payment === 'paid' ? '已收款' : '待收款']);
    for (const [label, value] of fields) {
      const field = element('div'); field.append(element('small', label), element('span', value)); meta.append(field);
    }
    $('#detail-content').replaceChildren(element('h1', detail.title), meta,
      element('p', detail.notes || '暂无备注', `notes${detail.notes ? '' : ' empty'}`));
  }
}

async function poll(force = false) {
  if (document.hidden || expired || (controller && !force)) return;
  controller?.abort();
  const active = new AbortController(); controller = active;
  const requested = range();
  const timeout = setTimeout(() => active.abort(), 10000);
  try {
    const response = await fetch(`/api/calendar-widget?${requested}`, {
      headers: {...(token ? {Authorization: `Bearer ${token}`} : {}), ...(account ? {'X-DDL-Account': account} : {})}, signal: active.signal,
    });
    if (response.status === 401) { expired = true; throw Error('连接已失效，请让 AIRI 重新打开日历'); }
    if (!response.ok) throw Error('日历暂时无法连接，显示最近的数据');
    const data = await response.json();
    if (controller !== active || requested !== range()) return;
    if (!Array.isArray(data.events) || typeof data.account !== 'string' || (account && data.account !== account))
      throw Error('账户连接发生变化，请让 AIRI 重新打开日历');
    account = data.account; events = data.events; today = dateKey(new Date(data.beijingNow)); loadedRange = requested;
    message();
    if (detailId && !events.some(event => event.id === detailId)) {
      detailId = null; message('这条日程已删除或移至其他日期');
    }
    render();
  } catch (error) {
    if (controller !== active || document.hidden) return;
    message(expired ? error.message : '日历暂时无法连接，显示最近的数据', !expired);
  } finally {
    clearTimeout(timeout);
    if (controller === active) controller = null;
  }
}
function select(day) { selected = day; detailId = null; render(); poll(true); }
$('#previous').addEventListener('click', () => select(shiftMonth(selected, -1)));
$('#next').addEventListener('click', () => select(shiftMonth(selected, 1)));
$('#today').addEventListener('click', () => select(dateKey()));
$('#calendar').addEventListener('click', event => { const day = event.target.closest('[data-day]')?.dataset.day; if (day) select(day); });
$('#events').addEventListener('click', event => { const id = event.target.closest('[data-event]')?.dataset.event; if (id) { detailId = id; render(); } });
$('#back').addEventListener('click', () => { detailId = null; render(); });
$('#retry').addEventListener('click', () => poll(true));
document.addEventListener('visibilitychange', () => { if (document.hidden) controller?.abort(); else poll(true); });
setInterval(poll, 5000);
render(); poll();
