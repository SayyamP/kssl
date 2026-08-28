import { useAppState, PILLARS, PILLAR_LABEL } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

export default function TopBar() {
  const { pillar, setPillar } = useAppState();
  const { data } = useData();

  const goMainPage = () => {
    setPillar("competitive");
  };

  return (
    <div className="topbar">
      <div
        className="brand"
        onClick={goMainPage}
        role="button"
        tabIndex={0}
        style={{ cursor: "pointer" }}
        title="Go to main page"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            goMainPage();
          }
        }}
      >
        <span className="wordmark">
          137<span className="wm-prod">Parallax</span>
        </span>
      </div>
      <div className="topnav">
        {PILLARS.map((p) => (
          <div
            className={`pill${pillar === p ? " active" : ""}`}
            key={p}
            onClick={() => setPillar(p)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setPillar(p);
              }
            }}
          >
            <span className="dot" />
            {PILLAR_LABEL[p]}
          </div>
        ))}
      </div>
      <div className="topright">
        <div className="statusbox client">
          <span className="v">{data.client?.name || "the client"}</span>
        </div>
        <div className="statusbox">
          <span className="k">Feed</span>
          <span className="v">
            <span className="live" />
            Live
          </span>
        </div>
      </div>
    </div>
  );
}
