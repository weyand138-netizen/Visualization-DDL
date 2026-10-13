import test from 'node:test';
import assert from 'node:assert/strict';
import { accountStorage, accountEventKey, accountKey } from '../public/account-store.js';
import { queueFocus, readPending, acknowledgeFocus } from '../public/focus-store.js';

class Storage {
  data = new Map();
  get length() { return this.data.size; }
  key(index) { return [...this.data.keys()][index] ?? null; }
  getItem(key) { return this.data.get(key) ?? null; }
  setItem(key, value) { this.data.set(key, String(value)); }
  removeItem(key) { this.data.delete(key); }
}

test('原账户保留旧计时和旧队列，第二账户无法读取它们', () => {
  const shared = new Storage();
  const primary = accountStorage(shared, 'admin');
  const secondary = accountStorage(shared, 'user2');
  shared.setItem('ddl-focus-timer', 'original-timer');
  shared.setItem('ddl-focus-outbox', JSON.stringify([{ id: 'old', seconds: 1500, date: '2026-10-12' }]));
  assert.equal(primary.getItem('ddl-focus-timer'), 'original-timer');
  assert.equal(secondary.getItem('ddl-focus-timer'), null);
  assert.equal(readPending(primary).length, 1);
  assert.equal(readPending(secondary).length, 0);
  secondary.setItem('ddl-focus-timer', 'second-timer');
  assert.equal(primary.getItem('ddl-focus-timer'), 'original-timer');
  assert.equal(secondary.getItem('ddl-focus-timer'), 'second-timer');
});

test('两人使用相同记录编号时，确认同步只清理自己的待同步记录', () => {
  const shared = new Storage();
  const primary = accountStorage(shared, 'admin');
  const secondary = accountStorage(shared, 'user2');
  const first = { id: 'same', seconds: 1500, date: '2026-10-12' };
  const second = { ...first, seconds: 600 };
  queueFocus(primary, first); queueFocus(secondary, second);
  assert.deepEqual(readPending(primary), [first]);
  assert.deepEqual(readPending(secondary), [second]);
  acknowledgeFocus(secondary, [second]);
  assert.deepEqual(readPending(secondary), []);
  assert.deepEqual(readPending(primary), [first]);
});

test('跨标签页只响应当前账户的存储事件，拒绝异常账户标识', () => {
  assert.equal(accountEventKey('admin', 'ddl-account:user2:ddl-focus-timer'), undefined);
  assert.equal(accountEventKey('user2', 'ddl-focus-timer'), undefined);
  assert.equal(accountEventKey('user2', 'ddl-account:user2:ddl-focus-timer'), 'ddl-focus-timer');
  assert.equal(accountEventKey('user2', 'ddl-account:user22:ddl-focus-timer'), undefined);
  assert.equal(accountEventKey('user2', null), null);
  assert.throws(() => accountKey('../admin', 'ddl-focus-timer'));
});
