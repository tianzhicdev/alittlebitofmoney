function toSats(modelConfig) {
  if (modelConfig && typeof modelConfig === 'object') {
    return Number(modelConfig.price_sats || 0);
  }
  return Number(modelConfig || 0);
}

export default function ModelTable({ endpoint, satsToDisplay }) {
  const models = endpoint?.models || {};
  const entries = Object.entries(models);

  const regularRows = entries
    .filter(([name]) => name !== '_default')
    .sort(([a], [b]) => a.localeCompare(b));

  const defaultRow = entries.find(([name]) => name === '_default');
  if (defaultRow) {
    regularRows.push(['other models', defaultRow[1]]);
  }

  if (!regularRows.length) {
    return <div className="status-note">No model pricing configured.</div>;
  }

  return (
    <div className="model-table-wrap">
      <table className="model-table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Sats</th>
            <th>USD</th>
          </tr>
        </thead>
        <tbody>
          {regularRows.map(([name, config]) => {
            const sats = toSats(config);
            const usd = satsToDisplay ? satsToDisplay(sats) : null;

            return (
              <tr key={name}>
                <td>{name}</td>
                <td>
                  <span className="sats-value">{sats} sats</span>
                </td>
                <td>
                  <span className="usd-value">{usd || '-'}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
