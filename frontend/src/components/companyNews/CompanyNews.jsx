import { useState, useEffect } from "react";
import Thumb from "../thumb/Thumb.jsx";

const formatNewsDate = (item) => {
  if (!item) return "Recent";
  if (item.date) {
    try {
      const d = new Date(item.date);
      if (!isNaN(d.getTime())) {
        return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
      }
    } catch (e) {}
    return String(item.date);
  }
  return item.ago || "Recent";
};

const renderCalendarIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, opacity: 0.7, margin: "0 4px 0 6px" }}>
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
    <line x1="16" y1="2" x2="16" y2="6" />
    <line x1="8" y1="2" x2="8" y2="6" />
    <line x1="3" y1="10" x2="21" y2="10" />
  </svg>
);

const renderSourceLink = (item) => {
  if (!item || !item.url) {
    const src = (item && item.source) ? item.source.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0] : "source";
    return (
      <span className="cn-source-plain">
        <span className="cn-src-dot" />
        {src}
      </span>
    );
  }
  let domain = item.source || "source";
  try {
    const u = new URL(item.url);
    domain = u.hostname.replace(/^www\./, "");
  } catch (e) {
    if (item.source) domain = item.source.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
  }
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      title={`Open ${domain} in a new tab`}
      className="cn-source-link"
    >
      <span className="cn-src-dot" />
      <span>{domain}</span>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ opacity: 0.7, marginLeft: "3px" }}>
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
        <polyline points="15 3 21 3 21 9"></polyline>
        <line x1="10" y1="14" x2="21" y2="3"></line>
      </svg>
    </a>
  );
};

export default function CompanyNews({
  displayName = "Company",
  topStory = null,
  newsFilter = "All",
  setNewsFilter,
  filteredArticles = [],
  companyArticles = [],
  corpusArticles = [],
  openNewsArticle = () => {},
}) {
  const [internalFilter, setInternalFilter] = useState("All");
  const activeFilter = newsFilter !== undefined ? newsFilter : internalFilter;
  const handleFilterChange = setNewsFilter || setInternalFilter;

  const [heroStoryIndex, setHeroStoryIndex] = useState(0);

  useEffect(() => {
    setHeroStoryIndex(0);
  }, [displayName, activeFilter]);

  if (!topStory) {
    return (
      <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
        No sourced article in the corpus names {displayName}.
      </div>
    );
  }

  const articles = filteredArticles.length > 0 ? filteredArticles : companyArticles;

  const getBoxArticle = (index) => {
    if (articles && articles[index]) return articles[index];
    if (companyArticles && companyArticles[index]) return companyArticles[index];
    const offset = index - (articles ? articles.length : 0);
    if (corpusArticles && corpusArticles[offset]) return corpusArticles[offset];
    if (articles && articles.length > 0) return articles[index % articles.length];
    return null;
  };

  // 3 Hero Stories for Carousel
  const heroPool = [getBoxArticle(0), getBoxArticle(1), getBoxArticle(2)].filter(Boolean);
  const heroCount = Math.max(1, Math.min(3, heroPool.length));
  const currentHero = heroPool[heroStoryIndex % heroCount] || topStory;

  // Grid Cards (2 cards below hero card)
  const gridCards = [getBoxArticle(3), getBoxArticle(4)].filter(Boolean);

  // Trending Articles for Right Sidebar (8 items)
  const trendingArticles = [];
  for (let i = 0; i < 8; i++) {
    const art = getBoxArticle(5 + i);
    if (art) trendingArticles.push(art);
  }

  return (
    <div className="cn-dashboard-wrapper">
      {/* Category Pills Row matching PHOTO-2026-09-06-16-56-43.jpg */}
      <div className="cn-pills-row">
        {["All", `${displayName} Updates`, "Defence", "Aerospace", "Technology", "Business", "Government", "International"].map((cat) => (
          <button
            key={cat}
            type="button"
            className={`cn-pill${activeFilter === cat ? " active" : ""}`}
            onClick={() => handleFilterChange(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Main 2-Column Layout Grid */}
      <div className="cn-main-layout">
        {/* LEFT COLUMN */}
        <div className="cn-left-col">
          {/* HERO TOP STORY CARD */}
          {currentHero && (
            <div className="cn-hero-card">
              {/* Left Side: Image */}
              <div
                className="cn-hero-media"
                onClick={() => openNewsArticle(currentHero)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openNewsArticle(currentHero);
                  }
                }}
              >
                {currentHero.image ? (
                  <Thumb src={currentHero.image} alt={currentHero.title} className="cn-hero-img" />
                ) : (
                  <div className="cn-no-image">NO IMAGE PUBLISHED WITH THIS ARTICLE</div>
                )}
                <span className="cn-top-story-badge">TOP STORY</span>
              </div>

              {/* Right Side: Text & Actions */}
              <div className="cn-hero-body">
                <div>
                  <div className="cn-card-meta">
                    <span className="cn-cat-red">
                      {(currentHero.category || "DEFENCE").toUpperCase()}
                    </span>
                    <span className="cn-date-str">
                      {renderCalendarIcon()}
                      {formatNewsDate(currentHero)}
                    </span>
                  </div>

                  <h3
                    className="cn-hero-title"
                    onClick={() => openNewsArticle(currentHero)}
                  >
                    {currentHero.title}
                  </h3>

                  {currentHero.excerpt && (
                    <p className="cn-hero-desc">
                      {currentHero.excerpt}
                    </p>
                  )}
                </div>

                {/* Hero Footer */}
                <div className="cn-hero-footer">
                  <button
                    type="button"
                    className="cn-read-btn"
                    onClick={() => openNewsArticle(currentHero)}
                  >
                    Read Article →
                  </button>

                  <div className="cn-carousel-controls">
                    <div className="cn-dots">
                      {[0, 1, 2].slice(0, heroCount).map((idx) => (
                        <span
                          key={idx}
                          className={`cn-dot${(heroStoryIndex % heroCount) === idx ? " active" : ""}`}
                          onClick={() => setHeroStoryIndex(idx)}
                          role="button"
                          tabIndex={0}
                          title={`Story ${idx + 1}`}
                        />
                      ))}
                    </div>
                    <div className="cn-arrows">
                      <button
                        type="button"
                        className="cn-arrow-btn"
                        onClick={() => setHeroStoryIndex((prev) => (prev > 0 ? prev - 1 : heroCount - 1))}
                        title="Previous story"
                      >
                        ‹
                      </button>
                      <button
                        type="button"
                        className="cn-arrow-btn"
                        onClick={() => setHeroStoryIndex((prev) => (prev + 1) % heroCount)}
                        title="Next story"
                      >
                        ›
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 2-CARDS PER ROW GRID BELOW HERO CARD */}
          <div className="cn-cards-grid">
            {gridCards.map((item, idx) => (
              <div
                key={item.id || `grid-${idx}`}
                className="cn-sub-card"
                onClick={() => openNewsArticle(item)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openNewsArticle(item);
                  }
                }}
              >
                <div className="cn-sub-media">
                  {item.image ? (
                    <Thumb src={item.image} alt={item.title} className="cn-sub-img" />
                  ) : (
                    <div className="cn-no-image">NO IMAGE PUBLISHED WITH THIS ARTICLE</div>
                  )}
                </div>
                <div className="cn-sub-body">
                  <div className="cn-card-meta">
                    <span className="cn-cat-red">
                      {(item.category || "DEFENCE").toUpperCase()}
                    </span>
                    <span className="cn-date-str">
                      {renderCalendarIcon()}
                      {formatNewsDate(item)}
                    </span>
                  </div>
                  <h4 className="cn-sub-title">{item.title}</h4>
                  {item.excerpt && <p className="cn-sub-desc">{item.excerpt}</p>}
                  <div className="cn-sub-footer">
                    {renderSourceLink(item)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT COLUMN: TRENDING NOW SIDEBAR */}
        <div className="cn-right-col">
          <div className="cn-trending-box">
            <div className="cn-trending-head">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="#f0593c" stroke="#f0593c" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 3z" />
              </svg>
              <span className="cn-trending-title">TRENDING NOW</span>
            </div>

            <div className="cn-trending-list">
              {trendingArticles.map((item, idx) => (
                <div
                  key={item.id || `trending-${idx}`}
                  className="cn-trending-item"
                  onClick={() => openNewsArticle(item)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openNewsArticle(item);
                    }
                  }}
                >
                  <span className="cn-rank-num">{idx + 1}</span>
                  <div className="cn-trending-thumb-wrap">
                    {item.image ? (
                      <Thumb src={item.image} alt={item.title} className="cn-trending-thumb" />
                    ) : (
                      <div className="cn-no-image-mini">NO...</div>
                    )}
                  </div>
                  <div className="cn-trending-info">
                    <h5 className="cn-trending-item-title">{item.title}</h5>
                    <span className="cn-trending-date">
                      {renderCalendarIcon()}
                      {formatNewsDate(item)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
