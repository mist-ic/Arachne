import { useState, useEffect, useRef } from 'react';

interface FeedEvent {
    id: number;
    time: string;
    type: 'success' | 'warning' | 'error' | 'info';
    tag: string;
    message: string;
    domain: string;
}

// Simulated live feed data
const MOCK_EVENTS: Omit<FeedEvent, 'id' | 'time'>[] = [
    { type: 'success', tag: 'EXTRACT', message: 'Extracted 47 products from listing page', domain: 'amazon.com' },
    { type: 'info', tag: 'CRAWL', message: 'Fetched product page via TLS-spoofed HTTP/2', domain: 'ebay.com' },
    { type: 'warning', tag: 'EVASION', message: 'Cloudflare challenge detected — switching to Camoufox', domain: 'shopify.com' },
    { type: 'success', tag: 'VISION', message: 'SAM 3 segmented 12 product cards, RF-DETR classified all', domain: 'bestbuy.com' },
    { type: 'error', tag: 'CAPTCHA', message: 'hCaptcha solver failed after 3 attempts', domain: 'target.com' },
    { type: 'success', tag: 'MERGE', message: 'HTML+Vision merge: 98.2% field agreement', domain: 'walmart.com' },
    { type: 'info', tag: 'DRIFT', message: 'Schema drift check passed — no changes detected', domain: 'newegg.com' },
    { type: 'success', tag: 'EXTRACT', message: 'Extracted 23 reviews with sentiment scores', domain: 'amazon.com' },
    { type: 'warning', tag: 'PROXY', message: 'Proxy pool rotated — 3 IPs marked unhealthy', domain: '—' },
    { type: 'success', tag: 'SCHEMA', message: 'Auto-discovered schema: 8 fields (name, price, sku...)', domain: 'etsy.com' },
    { type: 'info', tag: 'QUEUE', message: 'Redpanda consumer lag: 0 messages on crawl.results', domain: '—' },
    { type: 'error', tag: 'EVASION', message: 'Akamai Bot Manager blocked request — fingerprint mismatch', domain: 'nike.com' },
    { type: 'success', tag: 'EXTRACT', message: 'Confidence 0.97 — model: gemini-2.5-flash, cost: $0.0003', domain: 'bestbuy.com' },
    { type: 'warning', tag: 'DRIFT', message: 'Schema drift MODERATE: 2/4 signals triggered for product_v3', domain: 'amazon.com' },
    { type: 'success', tag: 'REPAIR', message: 'Auto-repaired schema: +1 field (delivery_date), validation passed', domain: 'amazon.com' },
];

function generateEvent(counter: number): FeedEvent {
    const base = MOCK_EVENTS[counter % MOCK_EVENTS.length];
    const now = new Date();
    return {
        id: counter,
        time: now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        ...base,
    };
}

export function LiveFeed() {
    const [events, setEvents] = useState<FeedEvent[]>(() => {
        const initial: FeedEvent[] = [];
        for (let i = 0; i < 8; i++) {
            initial.push(generateEvent(i));
        }
        return initial;
    });
    const counterRef = useRef(8);
    const [paused, setPaused] = useState(false);

    useEffect(() => {
        if (paused) return;
        const id = setInterval(() => {
            setEvents((prev) => {
                const next = [generateEvent(counterRef.current), ...prev.slice(0, 49)];
                counterRef.current += 1;
                return next;
            });
        }, 2200);
        return () => clearInterval(id);
    }, [paused]);

    const counts = {
        total: events.length,
        success: events.filter((e) => e.type === 'success').length,
        warnings: events.filter((e) => e.type === 'warning').length,
        errors: events.filter((e) => e.type === 'error').length,
    };

    return (
        <div className="page-enter">
            {/* Stats bar */}
            <div className="stat-grid">
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-primary)' } as React.CSSProperties}>
                    <div className="stat-label">Events / min</div>
                    <div className="stat-value">27</div>
                    <div className="stat-delta positive">↑ 12% vs last hour</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-secondary)' } as React.CSSProperties}>
                    <div className="stat-label">Success Rate</div>
                    <div className="stat-value">94.7%</div>
                    <div className="stat-delta positive">↑ 2.1%</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-danger)' } as React.CSSProperties}>
                    <div className="stat-label">Blocked</div>
                    <div className="stat-value">3</div>
                    <div className="stat-delta negative">↑ 1 this hour</div>
                </div>
                <div className="stat-card" style={{ '--stat-accent': 'var(--accent-info)' } as React.CSSProperties}>
                    <div className="stat-label">Queue Depth</div>
                    <div className="stat-value">0</div>
                    <div className="stat-delta positive">— healthy</div>
                </div>
            </div>

            {/* Feed */}
            <div className="card">
                <div className="card-header">
                    <div className="card-title">
                        <span className="card-icon">◉</span>
                        Pipeline Activity
                    </div>
                    <div className="flex items-center gap-3">
                        <span className={`card-badge ${paused ? 'warning' : 'success'}`}>
                            {paused ? '⏸ PAUSED' : '● LIVE'}
                        </span>
                        <button
                            onClick={() => setPaused(!paused)}
                            style={{
                                background: 'var(--surface-3)',
                                border: 'var(--border-default)',
                                color: 'var(--text-secondary)',
                                padding: '4px 12px',
                                borderRadius: 'var(--radius-sm)',
                                cursor: 'pointer',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '11px',
                            }}
                        >
                            {paused ? 'Resume' : 'Pause'}
                        </button>
                    </div>
                </div>

                <div className="feed-list">
                    {events.map((event, i) => (
                        <div
                            key={event.id}
                            className={`feed-entry type-${event.type}`}
                            style={{ animationDelay: `${i * 20}ms` }}
                        >
                            <span className="feed-time">{event.time}</span>
                            <span className="feed-message">
                                <span className="feed-tag">{event.tag}</span>
                                {event.message}
                            </span>
                            <span className="feed-domain">{event.domain}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
