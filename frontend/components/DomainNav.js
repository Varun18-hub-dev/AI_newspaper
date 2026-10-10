import React from 'react';
import { Layers } from 'lucide-react';

export default function DomainNav({
  domains = [],
  selectedDomain,
  onSelectDomain,
  selectedTopic,
  onSelectTopic,
}) {
  const currentDomainObj = domains.find(
    (d) => d.domain_id.toLowerCase() === (selectedDomain || '').toLowerCase()
  );

  return (
    <nav className="editorial-nav" aria-label="Department sections">
      <div className="container">
        {/* Department Links Bar */}
        <div className="nav-departments">
          <button
            className={`dept-link ${!selectedDomain || selectedDomain === 'all' ? 'active' : ''}`}
            onClick={() => {
              onSelectDomain('all');
              onSelectTopic('all');
            }}
          >
            Front Page
          </button>

          {domains.map((dom) => {
            const isActive = selectedDomain && selectedDomain.toLowerCase() === dom.domain_id.toLowerCase();
            return (
              <button
                key={dom.domain_id}
                className={`dept-link ${isActive ? 'active' : ''}`}
                onClick={() => {
                  onSelectDomain(dom.domain_id);
                  onSelectTopic('all');
                }}
              >
                {dom.display_name}
              </button>
            );
          })}
        </div>

        {/* Subtopic Filters (when filtered by domain) */}
        {currentDomainObj && currentDomainObj.topics && currentDomainObj.topics.length > 0 && (
          <div className="subtopic-bar">
            <span style={{ fontWeight: 600, color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Desk Focus:
            </span>
            <button
              className={`subtopic-pill ${!selectedTopic || selectedTopic === 'all' ? 'active' : ''}`}
              onClick={() => onSelectTopic('all')}
            >
              All {currentDomainObj.display_name}
            </button>
            {currentDomainObj.topics.map((t) => (
              <button
                key={t}
                className={`subtopic-pill ${selectedTopic === t ? 'active' : ''}`}
                onClick={() => onSelectTopic(t)}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
