import { useEffect, useState } from 'react';

export function useCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch('/api/v1/catalog', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Catalog fetch failed');
        }
        return response.json();
      })
      .then((data) => {
        setCatalog(data);
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

  const satsToDisplay = (sats) => {
    if (!catalog?.btc_usd) {
      return null;
    }

    const usdCents = (Number(sats) * catalog.btc_usd) / 100_000_000 * 100;
    if (usdCents < 100) {
      return `~${usdCents.toFixed(1)}\u00a2`;
    }
    return `~$${(usdCents / 100).toFixed(2)}`;
  };

  return { catalog, loading, error, satsToDisplay };
}
