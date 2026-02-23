import CodeTabs from '../components/CodeTabs';
import Collapsible from '../components/Collapsible';
import ModelTable from '../components/ModelTable';
import { useCatalog } from '../hooks/useCatalog';
import { useReveal } from '../hooks/useReveal';
import { generateSnippets } from '../utils/snippets';

function formatUpdated(updatedAt) {
  if (!updatedAt) {
    return 'updated time unavailable';
  }

  const updatedMs = Date.parse(updatedAt);
  if (Number.isNaN(updatedMs)) {
    return `updated ${updatedAt}`;
  }

  const diffMinutes = Math.max(0, Math.floor((Date.now() - updatedMs) / 60_000));
  if (diffMinutes < 1) {
    return 'updated just now';
  }
  if (diffMinutes === 1) {
    return 'updated 1 min ago';
  }
  if (diffMinutes < 60) {
    return `updated ${diffMinutes} min ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours === 1) {
    return 'updated 1 hour ago';
  }
  return `updated ${diffHours} hours ago`;
}

function endpointPath(apiName, endpointPathValue) {
  const path = endpointPathValue || '';
  if (path.startsWith('/')) {
    return `/${apiName}${path}`;
  }
  return `/${apiName}/${path}`;
}

function flatPriceText(endpoint, satsToDisplay) {
  const sats = Number(endpoint?.price_sats || 0);
  const usd = satsToDisplay ? satsToDisplay(sats) : null;
  return usd ? `${sats} sats ${usd}` : `${sats} sats`;
}

export default function Catalog() {
  const { catalog, loading, error, satsToDisplay } = useCatalog();
  const revealRef = useReveal([loading, error, catalog]);

  return (
    <div ref={revealRef} className="flex flex-col gap-5">
      <section className="hero-panel reveal" style={{ minHeight: '45vh' }}>
        <div className="hero-content">
          <p className="eyebrow">Pricing</p>
          <h1 className="glow-title">API Catalog</h1>
          <p className="hero-sub">Live pricing in sats. USD estimates at current BTC rate.</p>
        </div>
      </section>

      <section className="section reveal">
        <div className="flex flex-wrap items-baseline gap-3 mb-3">
          <h2 className="section-title mb-0">Endpoints</h2>
          {typeof catalog?.btc_usd === 'number' ? (
            <>
              <span className="text-[var(--accent)] font-semibold">
                BTC/USD ${catalog.btc_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
              <span className="text-[var(--muted)] text-sm">{formatUpdated(catalog?.btc_usd_updated_at)}</span>
            </>
          ) : (
            <span className="text-[var(--muted)] text-sm">BTC/USD unavailable. Sats are source of truth.</span>
          )}
        </div>

        {loading ? <div className="status-note">Loading...</div> : null}
        {error ? <div className="status-note">Failed to load catalog.</div> : null}

        {!loading && !error ? (
          <div className="grid gap-4">
            {Object.entries(catalog?.apis || {}).map(([apiName, api]) => (
              <article key={apiName} className="api-card reveal">
                <h3>{api?.name || apiName}</h3>
                <span className="api-badge">{apiName}</span>

                <div className="grid gap-3 mt-3">
                  {(api?.endpoints || []).map((endpoint, index) => {
                    const snippets = endpoint.example
                      ? generateSnippets(apiName, endpoint.path, endpoint.example)
                      : null;

                    return (
                      <section key={`${endpoint.path}-${index}`} className="endpoint-card">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <span className="method-tag">{(endpoint.method || 'POST').toUpperCase()}</span>
                          <span className="endpoint-path">{endpointPath(apiName, endpoint.path)}</span>
                        </div>

                        {endpoint.description ? <p className="text-[#8db0c4] text-sm mb-2">{endpoint.description}</p> : null}

                        {endpoint.price_type === 'per_model' ? (
                          <Collapsible title="Model Pricing" defaultOpen={false}>
                            <ModelTable endpoint={endpoint} satsToDisplay={satsToDisplay} />
                          </Collapsible>
                        ) : (
                          <div className="flat-price">{flatPriceText(endpoint, satsToDisplay)}</div>
                        )}

                        <div className="mt-3">
                          <Collapsible title="Code Examples" defaultOpen={false}>
                            {snippets ? (
                              <CodeTabs
                                tabs={[
                                  { label: 'curl', language: 'curl', code: snippets.curl },
                                  { label: 'python', language: 'python', code: snippets.python },
                                  { label: 'javascript', language: 'javascript', code: snippets.javascript },
                                ]}
                              />
                            ) : (
                              <div className="status-note">No endpoint example is configured.</div>
                            )}
                          </Collapsible>
                        </div>
                      </section>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
