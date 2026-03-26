import { useState, useEffect, useRef } from 'react'
import FilterPanel from './components/FilterPanel'
import Pagination from './components/Pagination'
import { applyFilter, runEnrich, saveMatch, removeMatch, manualEnrich, removeManualEnrich, searchContents, advancedSearch, dubbedSearch } from './api/client'

export default function App() {
  // Filter results state
  const [filterResult, setFilterResult]   = useState(null)  // { count, page, total_pages, contents }
  const [filterLoading, setFilterLoading] = useState(false)
  const [filterError, setFilterError]     = useState('')

  // Enrich state
  const [enrichLoading, setEnrichLoading] = useState(false)
  const [enrichError, setEnrichError]     = useState('')

  // Keep the last filter body so we can re-use it for pagination clicks
  const [lastFilter, setLastFilter]       = useState(null)
  const [enrichActive, setEnrichActive]   = useState(false)

  // Search
  const [searchQuery, setSearchQuery]       = useState('')
  const [suggestions, setSuggestions]       = useState([])
  const [searchOpen, setSearchOpen]         = useState(false)
  const [highlightId, setHighlightId]       = useState(null)
  const searchTimerRef                      = useRef(null)

  // ── handlers ──────────────────────────────────────────────────────────────

  const handleApply = async (filterBody) => {
    setFilterLoading(true)
    setFilterError('')
    setFilterResult(null)
    setEnrichActive(false)
    setLastFilter(filterBody)
    try {
      const data = await applyFilter(filterBody)
      setFilterResult(data)
    } catch (err) {
      setFilterError(err?.response?.data?.detail || 'Failed to apply filters.')
    } finally {
      setFilterLoading(false)
    }
  }

  const handlePageChange = async (newPage) => {
    if (!lastFilter) return
    const newFilter = { ...lastFilter, page: newPage }
    setLastFilter(newFilter)
    
    setFilterLoading(true)
    setFilterError('')
    try {
      const data = await applyFilter(newFilter)
      setFilterResult(data)
      
      // Auto-enrich if already active
      if (enrichActive) {
        handleEnrich(newFilter, true) // pass true to skip setting enrichActive again
      }
    } catch (err) {
      setFilterError(err?.response?.data?.detail || 'Failed to change page.')
    } finally {
      setFilterLoading(false)
    }
  }

  const handleEnrich = async (enrichBody, isAuto = false) => {
    setEnrichLoading(true)
    setEnrichError('')
    if (!isAuto) setEnrichActive(true)

    try {
      const data = await runEnrich(enrichBody)
      
      // Merge results into filterResult.contents
      setFilterResult(prev => {
        if (!prev || !data.results) return prev
        const enrichedContents = prev.contents.map(item => {
          const matchData = data.results.find(res => res.contentid === item.contentid)
          return matchData ? { ...item, matches: matchData.matches } : item
        })
        return { ...prev, contents: enrichedContents }
      })
    } catch (err) {
      setEnrichError(err?.response?.data?.detail || 'Enrichment failed.')
    } finally {
      setEnrichLoading(false)
    }
  }

  const handleSearchChange = (e) => {
    const q = e.target.value
    setSearchQuery(q)
    setSearchOpen(true)
    clearTimeout(searchTimerRef.current)
    if (!q.trim() || !lastFilter) { setSuggestions([]); return }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const res = await searchContents(lastFilter, q.trim())
        setSuggestions(res)
      } catch { setSuggestions([]) }
    }, 280)
  }

  const handleSuggestionClick = async (s) => {
    setSearchOpen(false)
    setSearchQuery('')
    setSuggestions([])
    if (s.page !== filterResult?.page) {
      await handlePageChange(s.page)
    }
    setHighlightId(s.contentid)
    setTimeout(() => setHighlightId(null), 2000)
  }

  // ── scroll FAB visibility ──────────────────────────────────────────────────
  const [showFab, setShowFab] = useState(false);
  useEffect(() => {
    const onScroll = () => {
      const scrolled = window.scrollY / (document.body.scrollHeight - window.innerHeight);
      setShowFab(scrolled >= 0.2);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // ── keyboard shortcuts for scroll ─────────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      if (e.altKey && e.key === 't') { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
      if (e.altKey && e.key === 'e') { e.preventDefault(); window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="header">
        <h1>Meta Enrichment</h1>
        <span className="badge">FAISS</span>
      </header>

      <main className="main-content">
        {/* Filter panel */}
        <FilterPanel
          onApply={handleApply}
          onEnrich={handleEnrich}
          loading={filterLoading}
          enrichLoading={enrichLoading}
          filterCount={filterResult?.count ?? null}
        />

        {/* Errors */}
        {filterError  && <div className="error-banner">⚠️ {filterError}</div>}
        {enrichError  && <div className="error-banner">⚠️ {enrichError}</div>}

        {/* Loading spinner */}
        {filterLoading && (
          <div className="spinner-wrap">
            <div className="spinner" />
            <p>Loading contents…</p>
          </div>
        )}

        {/* Content list */}
        {!filterLoading && filterResult && filterResult.count === 0 && (
          <div className="empty-state">
            <div className="icon">📭</div>
            No contents matched your filters.
          </div>
        )}

        {!filterLoading && filterResult && filterResult.contents?.length > 0 && (
          <>
            <div className="results-header">
              <h3>Contents — Page {filterResult.page} / {filterResult.total_pages}</h3>
              <div className="search-wrap">
                <input
                  className="search-input"
                  placeholder="Search by ID or title…"
                  value={searchQuery}
                  onChange={handleSearchChange}
                  onFocus={() => suggestions.length > 0 && setSearchOpen(true)}
                  onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
                />
                {searchOpen && suggestions.length > 0 && (
                  <ul className="search-suggestions">
                    {suggestions.map(s => (
                      <li key={s.contentid} className="search-suggestion-item" onMouseDown={() => handleSuggestionClick(s)}>
                        <span className="suggestion-name">{s.contentname}</span>
                        <span className="suggestion-meta">ID: {s.contentid} · p.{s.page}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {filterResult.contents.map((item) => (
              <ContentCard key={item.contentid} item={item} projectId={lastFilter.project_id} enrichActive={enrichActive} highlight={highlightId === item.contentid} />
            ))}

            <Pagination
              page={filterResult.page}
              totalPages={filterResult.total_pages}
              onPageChange={handlePageChange}
            />
          </>
        )}
      </main>

      {/* Enrich spinner while it runs */}
      {enrichLoading && (
        <div className="enrich-overlay" style={{ justifyContent: 'center' }}>
          <div className="spinner-wrap">
            <div className="spinner" />
            <p> Loading... this may take a moment on the first run.</p>
          </div>
        </div>
      )}

      {/* Scroll shortcut buttons */}
      <div className={`scroll-fab-group${showFab ? ' scroll-fab-group--visible' : ''}`}>
        <button
          className="scroll-fab"
          title="Scroll to top (Alt+T)"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        >▲</button>
        <button
          className="scroll-fab"
          title="Scroll to end (Alt+E)"
          onClick={() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })}
        >▼</button>
      </div>
    </div>
  )
}

// Modal for entering Manual Genre & Keywords before saving
function SelectModal({ match, onConfirm, onCancel, loading }) {
  const [genre, setGenre]       = useState(match.genres || '');
  const [keywords, setKeywords] = useState('');

  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Save — {match.title}</span>
          <button className="modal-close" onClick={onCancel}>✕</button>
        </div>
        <div className="modal-body">
          <label className="modal-label">
            Manual Genre
            <input
              className="modal-input"
              value={genre}
              onChange={e => setGenre(e.target.value)}
              placeholder="e.g. Action, Drama"
            />
          </label>
          <label className="modal-label">
            Manual Keywords
            <input
              className="modal-input"
              value={keywords}
              onChange={e => setKeywords(e.target.value)}
              placeholder="e.g. revenge, heist, friendship"
            />
          </label>
        </div>
        <div className="modal-footer">
          <button className="modal-btn modal-btn--cancel" onClick={onCancel} disabled={loading}>Cancel</button>
          <button className="modal-btn modal-btn--confirm" onClick={() => onConfirm(genre, keywords)} disabled={loading}>
            {loading ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

// A single match tile inside the carousel
function MatchCard({ match, projectId, contentId, isSelected, disableSelect, onSelect, onRemove }) {
  const [loading, setLoading]     = useState(false);
  const [showModal, setShowModal] = useState(false);

  const handleConfirm = async (genre, keywords) => {
    try {
      setLoading(true);
      await saveMatch(projectId, contentId, match, genre, keywords);
      setShowModal(false);
      onSelect(match.id);
    } catch (err) {
      console.error(err);
      alert("Failed to save match.");
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = async () => {
    try {
      setLoading(true);
      await removeMatch(projectId, contentId);
      onRemove();
    } catch (err) {
      console.error(err);
      alert("Failed to remove match.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {showModal && (
        <SelectModal
          match={match}
          onConfirm={handleConfirm}
          onCancel={() => setShowModal(false)}
          loading={loading}
        />
      )}
      <div className={`match-card${isSelected ? ' match-card--selected' : ''}`}>
        {match.poster_url ? (
          <img src={match.poster_url} alt={match.title} loading="lazy" />
        ) : (
          <div className="match-no-img">🎬</div>
        )}
        <div className="match-card-body">
          <div className="match-card-title">{match.title || '—'}</div>
          <div className="match-field">Director: <span>{match.director || '—'}</span></div>
          <div className="match-field match-cast">Cast: <span style={{ textTransform: 'capitalize' }}>{match.cast || '—'}</span></div>
          <div className="match-field">Genres: <span>{match.genres || '—'}</span></div>
          <div className="match-field">
            IMDb: <span>{match.imdb_rating != null ? match.imdb_rating : '—'}</span>
          </div>
          <div className="match-field">Year: <span>{match.release_date ? match.release_date.slice(0, 4) : '—'}</span></div>
          <span className="sim-badge">
            {(match.similarity * 100).toFixed(0)}% match
          </span>
        </div>
        <button
          className="match-select-btn"
          onClick={isSelected ? handleRemove : () => setShowModal(true)}
          disabled={loading || (!isSelected && disableSelect)}
        >
          {loading ? '...' : isSelected ? 'Remove' : 'Select'}
        </button>
      </div>
    </>
  )
}

// Advanced-search result tile (same shape as MatchCard, IMDB data)
function AdvSearchCard({ result, projectId, contentId, isSelected, disableSelect, onSelect, onRemove }) {
  const [loading, setLoading]     = useState(false);
  const [showModal, setShowModal] = useState(false);

  // Adapt IMDB result to the match shape expected by SelectModal / saveMatch
  const matchPayload = {
    id:                result.imdb_id,
    tmdb_id:           'not found',
    title:             result.title,
    poster_url:        result.poster_url,
    genres:            result.genres,
    imdb_rating:       result.imdb_rating || null,
    release_date:      result.year ? `${result.year}-01-01` : '',
    original_language: result.original_language || '',
    imdb_id:           result.imdb_id,
    similarity:        null,
    director:          result.director || '',
    cast:              result.cast || '',
  };

  const handleConfirm = async (genre, keywords) => {
    try {
      setLoading(true);
      await saveMatch(projectId, contentId, matchPayload, genre, keywords);
      setShowModal(false);
      onSelect(result.imdb_id);
    } catch (err) {
      console.error(err);
      alert('Failed to save match.');
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = async () => {
    try {
      setLoading(true);
      await removeMatch(projectId, contentId);
      onRemove();
    } catch (err) {
      console.error(err);
      alert('Failed to remove match.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {showModal && (
        <SelectModal
          match={matchPayload}
          onConfirm={handleConfirm}
          onCancel={() => setShowModal(false)}
          loading={loading}
        />
      )}
      <div className={`match-card${isSelected ? ' match-card--selected' : ''}`}>
        {result.poster_url ? (
          <img src={result.poster_url} alt={result.title} loading="lazy" />
        ) : (
          <div className="match-no-img">🎬</div>
        )}
        <div className="match-card-body">
          <div className="match-card-title">{result.title || '—'}</div>
          <div className="match-field">
            IMDb:&nbsp;
            <a href={`https://www.imdb.com/title/${result.imdb_id}`} target="_blank" rel="noreferrer"
              style={{ color: 'var(--accent)' }}>
              {result.imdb_id || '—'}
            </a>
          </div>
          <div className="match-field">Director: <span>{result.director || '—'}</span></div>
          <div className="match-field match-cast">Cast: <span style={{ textTransform: 'capitalize' }}>{result.cast || '—'}</span></div>
          <div className="match-field">Year: <span>{result.year || '—'}</span></div>
          {result.imdb_rating && <div className="match-field">Rating: <span>⭐ {result.imdb_rating}</span></div>}
          {result.genres && <div className="match-field">Genres: <span>{result.genres}</span></div>}
        </div>
        <button
          className="match-select-btn"
          onClick={isSelected ? handleRemove : () => setShowModal(true)}
          disabled={loading || (!isSelected && disableSelect)}
        >
          {loading ? '...' : isSelected ? 'Remove' : 'Select'}
        </button>
      </div>
    </>
  );
}

// Content preview card (filter list view + inline carousel)
function ContentCard({ item, projectId, enrichActive, highlight }) {
  const [selectedMatchId, setSelectedMatchId] = useState(null);
  const [manualSaved, setManualSaved]         = useState(false);
  const [manualLoading, setManualLoading]     = useState(false);
  const [advResults, setAdvResults]           = useState(null);   // null = not run yet
  const [advLoading, setAdvLoading]           = useState(false);
  const [advSelectedId, setAdvSelectedId]     = useState(null);
  const [dubbedResults, setDubbedResults]     = useState(null);  // null = not run yet
  const [dubbedLoading, setDubbedLoading]     = useState(false);
  const [dubbedSelectedId, setDubbedSelectedId] = useState(null);

  const handleAdvancedSearch = async () => {
    try {
      setAdvLoading(true);
      const data = await advancedSearch(projectId, item.contentid);
      setAdvResults(data.results);
    } catch (err) {
      console.error(err);
      alert('Advanced search failed.');
    } finally {
      setAdvLoading(false);
    }
  };

  const handleDubbedSearch = async () => {
    try {
      setDubbedLoading(true);
      const data = await dubbedSearch(projectId, item.contentid);
      setDubbedResults(data.matches);
    } catch (err) {
      console.error(err);
      alert('Dubbed search failed.');
    } finally {
      setDubbedLoading(false);
    }
  };

  const handleManualEnrich = async () => {
    try {
      setManualLoading(true);
      await manualEnrich(projectId, item.contentid);
      setManualSaved(true);
    } catch (err) {
      console.error(err);
      alert("Failed to save manual enrichment.");
    } finally {
      setManualLoading(false);
    }
  };

  const handleManualRemove = async () => {
    try {
      setManualLoading(true);
      await removeManualEnrich(projectId, item.contentid);
      setManualSaved(false);
    } catch (err) {
      console.error(err);
      alert("Failed to remove manual enrichment.");
    } finally {
      setManualLoading(false);
    }
  };

  return (
    <div className={`content-card${highlight ? ' content-card--highlight' : ''}`} style={{ position: 'relative' }}>
      {enrichActive && (
        <div className="manual-enrich-actions">
          <button
            className={`manual-enrich-btn${manualSaved ? ' manual-enrich-btn--saved' : ''}`}
            onClick={handleManualEnrich}
            disabled={manualLoading || manualSaved}
          >
            {manualLoading && !manualSaved ? '...' : manualSaved ? 'Saved' : 'Manual Enrich'}
          </button>
          {manualSaved && (
            <button
              className="manual-remove-btn"
              onClick={handleManualRemove}
              disabled={manualLoading}
            >
              {manualLoading ? '...' : 'Remove'}
            </button>
          )}
          <button
            className="adv-search-btn"
            onClick={handleAdvancedSearch}
            disabled={advLoading}
          >
            {advLoading ? '...' : 'Advanced Search'}
          </button>
          <button
            className="dubbed-search-btn"
            onClick={handleDubbedSearch}
            disabled={dubbedLoading}
          >
            {dubbedLoading ? '...' : 'Dubbed Content?'}
          </button>
        </div>
      )}
      <div className="content-card-top">
        {item.imgurl ? (
          <img
            className="content-poster"
            src={item.imgurl}
            alt={item.contentname}
            onError={e => { e.target.style.display = 'none' }}
          />
        ) : (
          <div className="content-poster-placeholder">🎬</div>
        )}

        <div className="content-info">
          <div className="content-title">{item.contentname || '—'}</div>
          <div className="content-meta">
            {item.director && (
              <span className="meta-pill">🎬 <span>{item.director}</span></span>
            )}
            {item.cast && (
              <span className="meta-pill meta-pill-cast" title={item.cast}>
                🎭 <span>{item.cast}</span>
              </span>
            )}
            {item.contenttype && (
              <span className="meta-pill">📁 <span>{item.contenttype}</span></span>
            )}
            {item.partnername && (
              <span className="meta-pill">🤝 <span>{item.partnername}</span></span>
            )}
          </div>
          <div className="content-id">ID: {item.contentid}</div>
        </div>
      </div>

      {advResults && (
        <div className="carousel-section" style={{ padding: '16px 0 0 0', marginTop: '16px', borderTop: '1px solid var(--border)' }}>
          <div className="carousel-label">🔍 Advanced Search Results ({advResults.length})</div>
          {advResults.length === 0 ? (
            <p style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>No results found.</p>
          ) : (
            <div className="carousel-track">
              {advResults.map((r) => (
                <AdvSearchCard
                  key={r.imdb_id}
                  result={r}
                  projectId={projectId}
                  contentId={item.contentid}
                  isSelected={advSelectedId === r.imdb_id}
                  disableSelect={advSelectedId !== null && advSelectedId !== r.imdb_id}
                  onSelect={(id) => setAdvSelectedId(id)}
                  onRemove={() => setAdvSelectedId(null)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {dubbedResults && (
        <div className="carousel-section" style={{ padding: '16px 0 0 0', marginTop: '16px', borderTop: '1px solid var(--border)' }}>
          <div className="carousel-label">🎙️ Dubbed Matches ({dubbedResults.length})</div>
          {dubbedResults.length === 0 ? (
            <p style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>No dubbed matches found.</p>
          ) : (
            <div className="carousel-track">
              {dubbedResults.map((m, idx) => (
                <MatchCard
                  key={idx}
                  match={m}
                  projectId={projectId}
                  contentId={item.contentid}
                  isSelected={dubbedSelectedId === m.id}
                  disableSelect={dubbedSelectedId !== null && dubbedSelectedId !== m.id}
                  onSelect={(id) => setDubbedSelectedId(id)}
                  onRemove={() => setDubbedSelectedId(null)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {item.matches && (
        <div className="carousel-section" style={{ padding: '16px 0 0 0', marginTop: '16px', borderTop: '1px solid var(--border)' }}>
          <div className="carousel-label">
            🔗 Top {item.matches.length} match{item.matches.length !== 1 ? 'es' : ''}
          </div>
          {item.matches.length === 0 ? (
            <p style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>No matches returned.</p>
          ) : (
            <div className="carousel-track">
              {item.matches.map((m, idx) => (
                <MatchCard 
                  key={idx} 
                  match={m} 
                  projectId={projectId} 
                  contentId={item.contentid} 
                  isSelected={selectedMatchId === m.id}
                  disableSelect={selectedMatchId !== null && selectedMatchId !== m.id}
                  onSelect={(id) => setSelectedMatchId(id)}
                  onRemove={() => setSelectedMatchId(null)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
