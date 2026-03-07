export function ExtractionStats() {
    // Simulated model performance data
    const models = [
        { name: 'gemini-2.5-flash', extractions: 1847, avgConfidence: 0.94, avgLatency: 1.2, costPer1k: 0.15, fields: 12.3 },
        { name: 'gpt-5', extractions: 423, avgConfidence: 0.97, avgLatency: 2.8, costPer1k: 4.20, fields: 14.1 },
        { name: 'qwen3-vl (local)', extractions: 892, avgConfidence: 0.82, avgLatency: 3.5, costPer1k: 0.00, fields: 9.8 },
        { name: 'claude-4-sonnet', extractions: 312, avgConfidence: 0.95, avgLatency: 2.1, costPer1k: 1.80, fields: 13.7 },
    ];

    // Simulated hourly throughput (last 24 bars)
    const throughput = [12, 18, 25, 31, 28, 22, 35, 42, 38, 45, 52, 48, 55, 61, 58, 49, 63, 71, 67, 59, 72, 68, 54, 47];

    // Simulated accuracy by domain
    const domains = [
        { domain: 'amazon.com', crawls: 892, accuracy: 96.2, schema: 'product_v4' },
        { domain: 'ebay.com', crawls: 445, accuracy: 93.8, schema: 'listing_v2' },
        { domain: 'bestbuy.com', crawls: 312, accuracy: 97.1, schema: 'product_v1' },
        { domain: 'walmart.com', crawls: 278, accuracy: 91.4, schema: 'product_v3' },
        { domain: 'etsy.com', crawls: 189, accuracy: 88.6, schema: 'product_v1' },
        { domain: 'target.com', crawls: 156, accuracy: 85.2, schema: 'product_v2' },
    ];

    const maxThroughput = Math.max(...throughput);

    return (
        <div className="page-enter">
            {/* Top stats */}
            <div className="stat-grid">
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-primary)' } as React.CSSProperties}>
                    <div className="stat-label">Total Extractions</div>
                    <div className="stat-value">3,474</div>
                    <div className="stat-delta positive">↑ 340 today</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-secondary)' } as React.CSSProperties}>
                    <div className="stat-label">Avg Confidence</div>
                    <div className="stat-value">0.93</div>
                    <div className="stat-delta positive">↑ 0.02</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-info)' } as React.CSSProperties}>
                    <div className="stat-label">Vision Fallbacks</div>
                    <div className="stat-value">127</div>
                    <div className="stat-delta positive">3.7% of total</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-primary)' } as React.CSSProperties}>
                    <div className="stat-label">Est. Cost Today</div>
                    <div className="stat-value">$2.14</div>
                    <div className="stat-delta negative">↑ $0.30</div>
                </div>
            </div>

            {/* Charts row */}
            <div className="chart-grid">
                {/* Throughput chart */}
                <div className="card">
                    <div className="card-header">
                        <div className="card-title">
                            <span className="card-icon">▤</span>
                            Extraction Throughput (24h)
                        </div>
                        <span className="card-badge success">Live</span>
                    </div>
                    <div className="mini-bars" style={{ height: '120px' }}>
                        {throughput.map((val, i) => (
                            <div
                                key={i}
                                className="mini-bar"
                                style={{ height: `${(val / maxThroughput) * 100}%` }}
                                title={`${val} extractions`}
                            />
                        ))}
                    </div>
                    <div className="flex justify-between" style={{ marginTop: '8px' }}>
                        <span className="text-mono text-mute" style={{ fontSize: '10px' }}>24h ago</span>
                        <span className="text-mono text-mute" style={{ fontSize: '10px' }}>now</span>
                    </div>
                </div>

                {/* Model comparison */}
                <div className="card">
                    <div className="card-header">
                        <div className="card-title">
                            <span className="card-icon">◇</span>
                            Model Performance
                        </div>
                    </div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Model</th>
                                <th>Runs</th>
                                <th>Confidence</th>
                                <th>$/1K</th>
                            </tr>
                        </thead>
                        <tbody>
                            {models.map((m) => (
                                <tr key={m.name}>
                                    <td className="mono">{m.name}</td>
                                    <td className="mono">{m.extractions.toLocaleString()}</td>
                                    <td>
                                        <span className={m.avgConfidence >= 0.9 ? 'text-green' : m.avgConfidence >= 0.8 ? 'text-accent' : 'text-red'}>
                                            {m.avgConfidence.toFixed(2)}
                                        </span>
                                    </td>
                                    <td className="mono">${m.costPer1k.toFixed(2)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Domain accuracy table */}
            <div className="card">
                <div className="card-header">
                    <div className="card-title">
                        <span className="card-icon">◎</span>
                        Domain Accuracy
                    </div>
                </div>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>Domain</th>
                            <th>Crawls</th>
                            <th>Accuracy</th>
                            <th>Active Schema</th>
                            <th>Health</th>
                        </tr>
                    </thead>
                    <tbody>
                        {domains.map((d) => (
                            <tr key={d.domain}>
                                <td className="mono">{d.domain}</td>
                                <td className="mono">{d.crawls.toLocaleString()}</td>
                                <td>
                                    <span className={d.accuracy >= 95 ? 'text-green' : d.accuracy >= 90 ? 'text-accent' : 'text-red'}>
                                        {d.accuracy}%
                                    </span>
                                </td>
                                <td className="mono text-dim">{d.schema}</td>
                                <td>
                                    <div className="progress-bar" style={{ width: '100px' }}>
                                        <div
                                            className={`progress-fill ${d.accuracy >= 95 ? 'success' : d.accuracy >= 90 ? 'warning' : 'danger'}`}
                                            style={{ width: `${d.accuracy}%` }}
                                        />
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
