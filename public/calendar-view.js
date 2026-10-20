import { calendarDays } from './domain.js';

/** Strict date validation for a URL-selected day, including leap years. */
export function isCalendarDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(`${value}T12:00:00Z`)) &&
    new Date(`${value}T12:00:00Z`).toISOString().slice(0, 10) === value;
}

/** Month navigation always selects its first day, including across year boundaries. */
export function shiftMonth(day, offset) {
  const next = new Date(`${day.slice(0, 7)}-01T12:00:00Z`);
  next.setUTCMonth(next.getUTCMonth() + offset);
  return next.toISOString().slice(0, 10);
}

/** Keep timed events chronological and all-day events last, with stable ties. */
export function dayEvents(events, day) {
  return events.filter(e => e.date === day).sort((a, b) =>
    (a.time || '99:99').localeCompare(b.time || '99:99') ||
    (a.createdAt || '').localeCompare(b.createdAt || '') || a.id.localeCompare(b.id));
}

/** Project one six-week Monday-first month without discarding adjacent-day events. */
export function monthView(selected, events, today) {
  const [year, month] = selected.split('-').map(Number);
  const counts = new Map();
  for (const event of events) counts.set(event.date, (counts.get(event.date) || 0) + 1);
  return calendarDays(year, month - 1).map(day => ({...day, count: counts.get(day.key) || 0,
    selected: day.key === selected, today: day.key === today}));
}
