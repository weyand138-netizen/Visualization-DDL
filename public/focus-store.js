import { isFocusSession } from './domain.js';

const PREFIX = 'ddl-focus-pending:';
const LEGACY = 'ddl-focus-outbox';

// Store each completed session under its own key so concurrent tabs cannot
// overwrite one another while appending to a shared JSON array.
export function readPending(storage, fallback = []) {
  const unique = new Map(fallback.filter(isFocusSession).map(record => [record.id, record]));
  try {
    const legacy = JSON.parse(storage.getItem(LEGACY) || '[]');
    if (Array.isArray(legacy)) for (const record of legacy) if (isFocusSession(record)) unique.set(record.id, record);
  } catch { /* A damaged legacy queue must not hide the per-session entries. */ }
  try {
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key?.startsWith(PREFIX)) continue;
      try {
        const record = JSON.parse(storage.getItem(key));
        if (isFocusSession(record)) unique.set(record.id, record);
      } catch { /* One malformed entry must not hide other completed sessions. */ }
    }
  } catch { /* Use the in-memory queue when browser storage is unavailable. */ }
  return [...unique.values()];
}

export function queueFocus(storage, record, fallback = []) {
  const pending = readPending(storage, fallback);
  if (!isFocusSession(record)) return pending;
  try { storage.setItem(PREFIX + record.id, JSON.stringify(record)); } catch { /* Keep an in-memory copy. */ }
  return [...new Map([...pending, record].map(item => [item.id, item])).values()];
}

export function acknowledgeFocus(storage, records, fallback = []) {
  const confirmed = new Set(records.map(record => record.id));
  const remaining = readPending(storage, fallback).filter(record => !confirmed.has(record.id));
  try {
    for (const id of confirmed) storage.removeItem(PREFIX + id);
    const legacy = JSON.parse(storage.getItem(LEGACY) || '[]');
    if (Array.isArray(legacy)) storage.setItem(LEGACY, JSON.stringify(legacy.filter(record => !confirmed.has(record.id))));
  } catch { /* The server id still prevents double counting on future retries. */ }
  return remaining;
}
