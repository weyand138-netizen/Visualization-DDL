export function dateKey(date = new Date()) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(date);
}

export function calendarDays(year, month) {
  const first = new Date(year, month, 1, 12);
  const offset = (first.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(year, month, index - offset + 1, 12);
    return { key: `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`,
      day: day.getDate(), current: day.getMonth() === month };
  });
}

// Parse decimal text as integer cents so totals never accumulate floating point error.
export function parseIncome(text) {
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(String(text))) throw new Error('收入请填写最多两位小数的非负金额');
  const [whole, fraction = ''] = String(text).split('.');
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}

export function incomeSummary(events, month) {
  const relevant = events.filter(event => !month || event.date.startsWith(month));
  return relevant.reduce((total, event) => {
    total.expected += event.incomeCents;
    total[event.payment === 'paid' ? 'paid' : 'pending'] += event.incomeCents;
    return total;
  }, { expected: 0, paid: 0, pending: 0 });
}

export function remainingSeconds(timer, now = Date.now()) {
  return timer.running ? Math.max(0, Math.ceil((timer.deadline - now) / 1000)) : timer.remaining;
}

export function money(cents) {
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(cents / 100);
}

export function isFocusSession(session) {
  return session && typeof session.id === 'string' && session.id.length > 0 && session.id.length <= 80 &&
    Number.isInteger(session.seconds) && session.seconds >= 60 && session.seconds <= 14400 &&
    typeof session.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(session.date) &&
    Number.isFinite(Date.parse(`${session.date}T00:00:00Z`)) && new Date(`${session.date}T00:00:00Z`).toISOString().slice(0, 10) === session.date;
}

export function focusSummary(records = [], pending = []) {
  // Canonical server records take precedence over their optimistic local copies.
  const unique = new Map();
  for (const record of [...records, ...pending]) if (isFocusSession(record) && !unique.has(record.id)) unique.set(record.id, record);
  const days = new Map();
  for (const record of unique.values()) {
    const day = days.get(record.date) || { seconds: 0, sessions: 0 };
    day.seconds += record.seconds; day.sessions += 1;
    days.set(record.date, day);
  }
  let points = 0;
  for (const day of days.values()) { day.points = Math.floor(day.seconds / 300); points += day.points; }
  return { days, points };
}

export function focusDay(summary, day, goal = 120) {
  const daily = summary.days.get(day) || { seconds: 0, sessions: 0, points: 0 };
  const target = Number.isInteger(goal) && goal >= 1 && goal <= 1440 ? goal : 120;
  return { ...daily, minutes: Math.floor(daily.seconds / 60),
    ratio: Math.min(1, daily.seconds / (target * 60)),
    percent: Math.min(100, Math.round(daily.seconds / (target * 60) * 100)),
    remainingMinutes: Math.max(0, Math.ceil((target * 60 - daily.seconds) / 60)),
    intensity: Math.min(1, daily.seconds / 7200) };
}

export function completedFocusRecord(timer, now = Date.now()) {
  if (!timer?.running || timer.completed || remainingSeconds(timer, now) > 0) return null;
  const record = { id: timer.id, seconds: timer.total, date: dateKey(new Date(timer.deadline)) };
  return isFocusSession(record) ? record : null;
}
