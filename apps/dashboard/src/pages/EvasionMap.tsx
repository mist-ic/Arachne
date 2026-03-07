export function EvasionMap() {
    const vendors = [
        {
            name: 'Cloudflare',
            icon: '🛡️',
            encounters: 342,
            evaded: 318,
            blocked: 24,
            strategy: 'TLS Spoof + Camoufox',
            lastSeen: '2 min ago',
        },
        {
            name: 'Akamai Bot Manager',
            icon: '🔒',
            encounters: 187,
            evaded: 159,
            blocked: 28,
            strategy: 'Pydoll + Cookie Replay',
            lastSeen: '8 min ago',
        },
        {
            name: 'PerimeterX',
            icon: '⚡',
            encounters: 94,
            evaded: 88,
            blocked: 6,
            strategy: 'TLS Spoof + Fingerprint Rotation',
            lastSeen: '15 min ago',
        },
        {
            name: 'DataDome',
            icon: '🎯',
            encounters: 63,
            evaded: 55,
            blocked: 8,
            strategy: 'Browser Stealth + Proxy Rotation',
            lastSeen: '22 min ago',
        },
        {
            name: 'Kasada',
            icon: '🔐',
            encounters: 41,
            evaded: 31,
            blocked: 10,
            strategy: 'Camoufox + CAPTCHA Solver',
            lastSeen: '1 hr ago',
        },
        {
            name: 'Shape Security',
            icon: '🧬',
            encounters: 28,
            evaded: 24,
            blocked: 4,
            strategy: 'Full Browser + Cookie Jar',
            lastSeen: '3 hr ago',
        },
    ];

    const strategies = [
        { name: 'TLS Fingerprint Spoofing', uses: 489, successRate: 96.3 },
        { name: 'Camoufox Browser', uses: 234, successRate: 91.4 },
        { name: 'Pydoll Stealth', uses: 156, successRate: 88.2 },
        { name: 'Proxy Rotation', uses: 412, successRate: 94.7 },
        { name: 'CAPTCHA Solving (2Captcha)', uses: 67, successRate: 78.5 },
        { name: 'Cookie Replay', uses: 198, successRate: 97.1 },
    ];

    return (
        <div className="page-enter">
            {/* Stats */}
            <div className="stat-grid">
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-secondary)' } as React.CSSProperties}>
                    <div className="stat-label">Total Encounters</div>
                    <div className="stat-value">755</div>
                    <div className="stat-delta positive">Last 24h</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-secondary)' } as React.CSSProperties}>
                    <div className="stat-label">Evasion Rate</div>
                    <div className="stat-value">89.4%</div>
                    <div className="stat-delta positive">↑ 1.8%</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-danger)' } as React.CSSProperties}>
                    <div className="stat-label">Blocks Today</div>
                    <div className="stat-value">80</div>
                    <div className="stat-delta negative">↑ 12</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-info)' } as React.CSSProperties}>
                    <div className="stat-label">Healthy Proxies</div>
                    <div className="stat-value">47</div>
                    <div className="stat-delta positive">of 50 pool</div>
                </div>
            </div>

            {/* Vendor cards grid */}
            <div className="mb-6">
                <div className="flex items-center gap-3 mb-4">
                    <span style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: '14px' }}>
                        Anti-Bot Vendor Map
                    </span>
                    <span className="text-mono text-mute" style={{ fontSize: '11px' }}>
            // encounter frequency & evasion success
                    </span>
                </div>

                <div className="evasion-grid">
                    {vendors.map((v) => {
                        const rate = ((v.evaded / v.encounters) * 100).toFixed(1);
                        const rateNum = parseFloat(rate);
                        return (
                            <div className="evasion-card" key={v.name}>
                                <div className="evasion-vendor">
                                    <span>{v.icon}</span>
                                    {v.name}
                                </div>

                                <div className="evasion-stat-row">
                                    <span className="evasion-stat-label">Encounters</span>
                                    <span className="evasion-stat-value">{v.encounters}</span>
                                </div>
                                <div className="evasion-stat-row">
                                    <span className="evasion-stat-label">Evasion Rate</span>
                                    <span className={`evasion-stat-value ${rateNum >= 90 ? 'text-green' : rateNum >= 80 ? 'text-accent' : 'text-red'}`}>
                                        {rate}%
                                    </span>
                                </div>
                                <div className="evasion-stat-row">
                                    <span className="evasion-stat-label">Blocked</span>
                                    <span className="evasion-stat-value text-red">{v.blocked}</span>
                                </div>
                                <div className="evasion-stat-row">
                                    <span className="evasion-stat-label">Strategy</span>
                                    <span className="evasion-stat-value text-dim" style={{ fontSize: '11px' }}>{v.strategy}</span>
                                </div>

                                <div className="progress-bar" style={{ marginTop: '12px' }}>
                                    <div
                                        className={`progress-fill ${rateNum >= 90 ? 'success' : rateNum >= 80 ? 'warning' : 'danger'}`}
                                        style={{ width: `${rateNum}%` }}
                                    />
                                </div>
                                <div className="text-mono text-mute" style={{ fontSize: '10px', marginTop: '6px' }}>
                                    Last: {v.lastSeen}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Strategy effectiveness table */}
            <div className="card">
                <div className="card-header">
                    <div className="card-title">
                        <span className="card-icon">⚔</span>
                        Strategy Effectiveness
                    </div>
                </div>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>Strategy</th>
                            <th>Uses</th>
                            <th>Success Rate</th>
                            <th>Health</th>
                        </tr>
                    </thead>
                    <tbody>
                        {strategies.map((s) => (
                            <tr key={s.name}>
                                <td>{s.name}</td>
                                <td className="mono">{s.uses}</td>
                                <td>
                                    <span className={s.successRate >= 95 ? 'text-green' : s.successRate >= 85 ? 'text-accent' : 'text-red'}>
                                        {s.successRate}%
                                    </span>
                                </td>
                                <td>
                                    <div className="progress-bar" style={{ width: '120px' }}>
                                        <div
                                            className={`progress-fill ${s.successRate >= 95 ? 'success' : s.successRate >= 85 ? 'warning' : 'danger'}`}
                                            style={{ width: `${s.successRate}%` }}
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
