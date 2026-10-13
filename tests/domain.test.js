import test from 'node:test';
import assert from 'node:assert/strict';
import { calendarDays, dateKey, incomeSummary, parseIncome, remainingSeconds } from '../public/domain.js';

test('月历从周一开始，正确跨年且无遗漏或重复日期', () => {
  const days = calendarDays(2027, 0);
  assert.equal(days[0].key, '2026-12-28');
  assert.equal(days.at(-1).key, '2027-02-07');
  assert.equal(new Set(days.map(day => day.key)).size, 42);
  assert.equal(days.filter(day => day.current).length, 31);
});

test('闰年二月包含 29 日，普通年二月只包含 28 日', () => {
  assert.equal(calendarDays(2028, 1).filter(day => day.current).length, 29);
  assert.equal(calendarDays(2027, 1).filter(day => day.current).length, 28);
  assert.equal(calendarDays(2028, 1).find(day => day.key === '2028-02-29').current, true);
});

test('北京时间跨日，不受服务器或浏览器所在时区影响', () => {
  assert.equal(dateKey(new Date('2026-10-10T15:59:59Z')), '2026-10-10');
  assert.equal(dateKey(new Date('2026-10-10T16:00:00Z')), '2026-10-11');
});

test('收入使用整数分，处理零、零头和最大金额', () => {
  assert.equal(parseIncome('0'), 0);
  assert.equal(parseIncome('0.1') + parseIncome('0.2'), 30);
  assert.equal(parseIncome('120.05'), 12005);
  assert.equal(parseIncome('999999999.99'), 99999999999);
  for (const input of ['-1', '1.001', '1e3', 'NaN', '', '1000000000']) assert.throws(() => parseIncome(input));
});

test('收入按日程月份与到账状态汇总，完成状态不冒充到账状态', () => {
  const events = [
    { date: '2026-10-01', incomeCents: 10, payment: 'paid', status: 'planned' },
    { date: '2026-10-31', incomeCents: 20, payment: 'pending', status: 'done' },
    { date: '2026-11-01', incomeCents: 990, payment: 'paid', status: 'done' },
  ];
  assert.deepEqual(incomeSummary(events, '2026-10'), { expected: 30, paid: 10, pending: 20 });
  assert.deepEqual(incomeSummary(events, '2026-12'), { expected: 0, paid: 0, pending: 0 });
});

test('计时基于截止时间：页面休眠后补齐 elapsed，暂停不继续减少', () => {
  assert.equal(remainingSeconds({ running: true, deadline: 60000 }, 30001), 30);
  assert.equal(remainingSeconds({ running: true, deadline: 60000 }, 90000), 0);
  assert.equal(remainingSeconds({ running: false, deadline: 60000, remaining: 25 }, 90000), 25);
});
