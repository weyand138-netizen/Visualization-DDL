// The original account keeps its existing timer and pending-session keys.
// Other accounts only see keys inside their own namespace on this origin.
export function accountKey(account, key) {
  if (!/^[a-z][a-z0-9_-]{0,31}$/.test(account)) throw new Error('账户标识不正确');
  return account === 'admin' ? key : `ddl-account:${account}:${key}`;
}

export function accountEventKey(account, key) {
  if (key === null) return null;
  if (account === 'admin') return key.startsWith('ddl-account:') ? undefined : key;
  const prefix = `ddl-account:${account}:`;
  return key.startsWith(prefix) ? key.slice(prefix.length) : undefined;
}

export function accountStorage(storage, account) {
  const keys = () => {
    const result = [];
    for (let index = 0; index < storage.length; index++) {
      const key = accountEventKey(account, storage.key(index));
      if (key !== undefined && key !== null) result.push(key);
    }
    return result;
  };
  return {
    getItem: key => storage.getItem(accountKey(account, key)),
    setItem: (key, value) => storage.setItem(accountKey(account, key), value),
    removeItem: key => storage.removeItem(accountKey(account, key)),
    key: index => keys()[index] ?? null,
    get length() { return keys().length; },
  };
}
