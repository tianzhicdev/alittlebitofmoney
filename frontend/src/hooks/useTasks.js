import { useEffect, useState } from 'react';

export function useTasks() {
  const [tasks, setTasks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch('/api/v1/ai-for-hire/tasks', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Tasks fetch failed');
        }
        return response.json();
      })
      .then((data) => {
        setTasks(data.tasks);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          return;
        }
        setError(err);
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, []);

  return { tasks, loading, error };
}

export function useTaskDetail(taskId) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!taskId) {
      setDetail(null);
      return;
    }

    setLoading(true);
    const controller = new AbortController();

    fetch(`/api/v1/ai-for-hire/tasks/${taskId}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Task detail fetch failed');
        }
        return response.json();
      })
      .then((data) => {
        setDetail(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          return;
        }
        setError(err);
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [taskId]);

  return { detail, loading, error };
}
