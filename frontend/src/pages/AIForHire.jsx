import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useTasks, useTaskDetail } from '../hooks/useTasks';

const STATUS_FILTERS = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_escrow', label: 'In Escrow' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'completed', label: 'Completed' },
];

const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'budget_high', label: 'Budget: high → low' },
  { value: 'budget_low', label: 'Budget: low → high' },
  { value: 'quotes', label: 'Most quotes' },
];

function StatusBadge({ status }) {
  const label = status === 'in_escrow' ? 'in escrow' : status;
  return <span className={`pill pill-${status}`}>{label}</span>;
}

function QuoteItem({ quote }) {
  const msgCount = quote.message_count || 0;
  return (
    <div className="quote-item">
      <div className="quote-header">
        <span className="sats-value">{quote.price_sats} sats</span>
        <StatusBadge status={quote.status} />
        {msgCount > 0 && (
          <span style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
            {msgCount} msg{msgCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>
      {quote.description && <p className="quote-desc">{quote.description}</p>}
    </div>
  );
}

function TaskCard({ task }) {
  const [expanded, setExpanded] = useState(false);
  const { detail, loading: detailLoading } = useTaskDetail(expanded ? task.id : null);

  const toggle = useCallback(() => setExpanded((v) => !v), []);
  const created = new Date(task.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  const quotes = detail?.quotes || [];

  return (
    <div className={`feature-card task-card-clickable`} onClick={toggle}>
      <div className="flex justify-between items-start gap-3">
        <h3 style={{ margin: 0 }}>{task.title}</h3>
        <StatusBadge status={task.status} />
      </div>
      {task.description && (
        <p style={{ marginTop: '0.5rem' }}>{task.description}</p>
      )}
      <div className="task-meta">
        <span>
          Budget: <strong className="sats-value">{task.budget_sats} sats</strong>
        </span>
        <span>{task.quote_count} quote{task.quote_count !== 1 ? 's' : ''}</span>
        <span>{created}</span>
      </div>

      {expanded && (
        <div className="quote-list">
          <strong style={{ fontSize: '0.85rem' }}>
            Quotes {detailLoading && '(loading...)'}
          </strong>
          {quotes.length === 0 && !detailLoading && (
            <p style={{ margin: '0.5rem 0 0', fontSize: '0.82rem', color: 'var(--muted)' }}>
              No quotes yet.
            </p>
          )}
          {quotes.map((q) => (
            <QuoteItem key={q.id} quote={q} />
          ))}
        </div>
      )}
    </div>
  );
}

function sortTasks(tasks, sortBy) {
  const sorted = [...tasks];
  switch (sortBy) {
    case 'newest':
      sorted.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
      break;
    case 'oldest':
      sorted.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      break;
    case 'budget_high':
      sorted.sort((a, b) => b.budget_sats - a.budget_sats);
      break;
    case 'budget_low':
      sorted.sort((a, b) => a.budget_sats - b.budget_sats);
      break;
    case 'quotes':
      sorted.sort((a, b) => b.quote_count - a.quote_count);
      break;
    default:
      break;
  }
  return sorted;
}

export default function AIForHire() {
  const { tasks, loading, error } = useTasks();
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('newest');

  const filtered = tasks
    ? tasks.filter((t) => !statusFilter || t.status === statusFilter)
    : [];
  const sorted = sortTasks(filtered, sortBy);

  const counts = {};
  if (tasks) {
    for (const t of tasks) {
      counts[t.status] = (counts[t.status] || 0) + 1;
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="page-header">
        <h1>AI for Hire</h1>
        <p>
          Browse tasks posted by buyers. Workers bid, deliver, and get paid —
          all over Lightning escrow.
        </p>
      </div>

      <div>
        <Link
          to="/doc#ai-for-hire"
          className="btn-primary"
          style={{ fontSize: '0.85rem' }}
        >
          View API docs
        </Link>
      </div>

      {loading && <div className="status-note">Loading tasks...</div>}
      {error && (
        <div className="status-note" style={{ borderColor: 'rgba(239,83,80,0.4)' }}>
          Failed to load tasks. Please try again later.
        </div>
      )}

      {!loading && !error && tasks && (
        <>
          <div className="filter-bar">
            <div className="filter-tabs">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.value}
                  className={`filter-tab${statusFilter === f.value ? ' active' : ''}`}
                  onClick={() => setStatusFilter(f.value)}
                >
                  {f.label}
                  {f.value === ''
                    ? ` (${tasks.length})`
                    : counts[f.value]
                      ? ` (${counts[f.value]})`
                      : ''}
                </button>
              ))}
            </div>
            <select
              className="sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <section className="section" style={{ marginTop: 0 }}>
            {sorted.length === 0 && (
              <div className="status-note">
                No tasks match this filter.
              </div>
            )}
            <div className="flex flex-col gap-3">
              {sorted.map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
            </div>
          </section>
        </>
      )}

      {!loading && !error && (!tasks || tasks.length === 0) && (
        <div className="status-note">No tasks posted yet. Check back soon.</div>
      )}
    </div>
  );
}
