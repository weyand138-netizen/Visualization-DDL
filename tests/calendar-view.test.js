import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { dayEvents, isCalendarDate, monthView, shiftMonth } from '../public/calendar-view.js';

test('calendar spans six Monday-first weeks, including leap day and year boundaries', () => {
  const days = monthView('2032-02-29', [{date: '2032-02-29'}, {date: '2032-02-29'}], '2032-02-29');
  assert.equal(days.length, 42);
  assert.equal(days[0].key, '2032-01-26');
  assert.equal(days[41].key, '2032-03-07');
  assert.deepEqual(days.find(d => d.key === '2032-02-29'), {key: '2032-02-29', day: 29, current: true, count: 2, selected: true, today: true});
  assert.equal(shiftMonth('2030-12-31', 1), '2031-01-01');
  assert.equal(shiftMonth('2031-01-01', -1), '2030-12-01');
  assert.equal(isCalendarDate('2032-02-29'), true);
  assert.equal(isCalendarDate('2031-02-29'), false);
  assert.equal(isCalendarDate('2031-1-01'), false);
});

test('daily agenda sorts times and keeps all-day events last without mutating input', () => {
  const events = [{id: 'all', date: '2032-02-29', time: ''}, {id: 'late', date: '2032-02-29', time: '14:00'},
    {id: 'early', date: '2032-02-29', time: '08:00'}, {id: 'other', date: '2032-03-01', time: '07:00'}];
  assert.deepEqual(dayEvents(events, '2032-02-29').map(e => e.id), ['early', 'late', 'all']);
  assert.equal(events[0].id, 'all');
  assert.deepEqual(dayEvents(events, '2033-01-01'), []);
});
