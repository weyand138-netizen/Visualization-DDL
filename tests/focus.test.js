import test from 'node:test';
import assert from 'node:assert/strict';
import { focusSummary, focusDay, completedFocusRecord, isFocusSession } from '../public/domain.js';
import { readPending, queueFocus, acknowledgeFocus } from '../public/focus-store.js';

const day = '2026-10-12';
const record = (id, seconds, date = day) => ({ id, seconds, date });
class Storage {
  data = new Map();
  get length() { return this.data.size; }
  key(index) { return [...this.data.keys()][index] ?? null; }
  getItem(key) { return this.data.get(key) ?? null; }
  setItem(key, value) { this.data.set(key, String(value)); }
  removeItem(key) { this.data.delete(key); }
}

test('零记录、75 分钟、刚好目标和超额目标使用相同统计口径', () => {
  const empty = focusDay(focusSummary(), day);
  assert.deepEqual(empty, { seconds: 0, sessions: 0, points: 0, minutes: 0, ratio: 0, percent: 0, remainingMinutes: 120, intensity: 0 });
  const summary = focusSummary([record('a', 1500), record('b', 1500), record('c', 1500)]);
  assert.deepEqual(focusDay(summary, day), { seconds: 4500, sessions: 3, points: 15, minutes: 75, ratio: .625, percent: 63, remainingMinutes: 45, intensity: .625 });
  for (const [seconds, minutes, points] of [[7200, 120, 24], [9000, 150, 30]]) {
    const stats = focusDay(focusSummary([record('a', seconds)]), day);
    assert.equal(stats.minutes, minutes);
    assert.equal(stats.points, points);
    assert.equal(stats.ratio, 1);
    assert.equal(stats.percent, 100);
    assert.equal(stats.intensity, 1);
    assert.equal(stats.remainingMinutes, 0);
  }
});

test('积分先合并同一天的秒数再向下取整，跨日期分别取整', () => {
  const summary = focusSummary([record('a', 180), record('b', 180), record('c', 299, '2026-10-11'), record('d', 60, '2026-09-01')]);
  assert.equal(focusDay(summary, day).points, 1);
  assert.equal(focusDay(summary, '2026-10-11').points, 0);
  assert.equal(summary.points, 1);
});

test('历史颜色固定按120分钟封顶，调整每日目标只影响今日进度', () => {
  const summary = focusSummary([record('a', 4500)]);
  const smaller = focusDay(summary, day, 60);
  const larger = focusDay(summary, day, 240);
  assert.equal(smaller.ratio, 1);
  assert.equal(larger.ratio, .3125);
  assert.equal(smaller.intensity, larger.intensity);
  assert.equal(smaller.points, larger.points);
  assert.equal(focusDay(summary, day, 0).remainingMinutes, 45);
});

test('服务端、离线队列、重复提交按唯一编号合并，以服务端记录为准', () => {
  const canonical = record('same', 1500);
  const pending = [canonical, record('same', 3000, '2026-10-11'), record('new', 180), record('new', 180)];
  const summary = focusSummary([canonical, canonical], pending);
  assert.equal(focusDay(summary, day).seconds, 1680);
  assert.equal(focusDay(summary, day).sessions, 2);
  assert.equal(focusDay(summary, '2026-10-11').seconds, 0);
});

test('跨午夜按北京时间完成截止时间归属，休眠后恢复仍归属原完成日期', () => {
  const deadline = Date.parse('2026-10-12T16:00:01Z');
  const timer = { id: 'midnight', total: 1500, remaining: 1500, running: true, completed: false, deadline };
  assert.equal(completedFocusRecord(timer, deadline - 1), null);
  assert.deepEqual(completedFocusRecord(timer, deadline), record('midnight', 1500, '2026-10-13'));
  assert.equal(completedFocusRecord(timer, deadline + 86400000).date, '2026-10-13');
  assert.equal(completedFocusRecord({ ...timer, deadline: deadline - 2000 }, deadline).date, '2026-10-12');
  assert.equal(completedFocusRecord({ ...timer, running: false, remaining: 60 }, deadline), null);
  assert.equal(completedFocusRecord({ ...timer, running: false, remaining: 1500 }, deadline), null);
  assert.equal(completedFocusRecord({ ...timer, completed: true }, deadline), null);
});

test('日期、时长和编号异常的记录不会污染历史统计', () => {
  for (const invalid of [record('', 60), record('a', 59), record('a', 14401), record('a', 60.1), record('a', 60, '2026-02-30'), record('a', 60, '2026-2-01'), null]) {
    assert.ok(!isFocusSession(invalid));
    assert.equal(focusSummary([invalid]).points, 0);
  }
});

test('多标签页独立写入不会覆盖另一轮专注，刷新后队列完整', () => {
  const storage = new Storage();
  const tabA = queueFocus(storage, record('a', 180));
  const tabB = queueFocus(storage, record('b', 180));
  queueFocus(storage, record('c', 180), tabA);
  assert.equal(tabB.length, 2);
  assert.deepEqual(new Set(readPending(storage).map(item => item.id)), new Set(['a', 'b', 'c']));
  assert.equal(focusSummary([], readPending(storage)).points, 1);
});

test('请求成功但读取确认失败时保留待同步记录，收到服务端编号才移除', () => {
  const storage = new Storage();
  queueFocus(storage, record('a', 1500));
  // POST may have committed before a connection failure: retain until GET confirms.
  assert.equal(readPending(storage).length, 1);
  const canonical = [record('a', 1500)];
  assert.equal(focusDay(focusSummary(canonical, readPending(storage)), day).seconds, 1500);
  queueFocus(storage, record('b', 180));
  const remaining = acknowledgeFocus(storage, canonical);
  assert.deepEqual(remaining.map(item => item.id), ['b']);
  assert.deepEqual(readPending(storage), remaining);
});

test('旧队列与新队列合并、去重和确认，损坏的旧队列不掩盖新记录', () => {
  const storage = new Storage();
  storage.setItem('ddl-focus-outbox', JSON.stringify([record('a', 1500), record('a', 1500)]));
  queueFocus(storage, record('b', 180));
  assert.equal(readPending(storage).length, 2);
  acknowledgeFocus(storage, [record('a', 1500)]);
  assert.deepEqual(JSON.parse(storage.getItem('ddl-focus-outbox')), []);
  storage.setItem('ddl-focus-outbox', '{broken');
  storage.setItem('ddl-focus-pending:broken', '{broken');
  assert.deepEqual(readPending(storage), [record('b', 180)]);
});

test('浏览器禁止存储时仍保留当前页面的记录，确认后清除内存队列', () => {
  const denied = new Proxy({}, { get() { throw new Error('Storage denied'); } });
  const pending = queueFocus(denied, record('a', 1500));
  assert.deepEqual(readPending(denied, pending), pending);
  assert.deepEqual(acknowledgeFocus(denied, pending, pending), []);
});
