import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getQueryHistory } from "../services/historyService";
import { getErrorMessage } from "../services/api";

export default function QueryHistory() {
  const [result, setResult] = useState({ content: [], totalPages: 1 });
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");

    getQueryHistory(page, 10)
      .then((data) => {
        const items = Array.isArray(data) ? data : (data?.content || []);
        const totalPages = Array.isArray(data)
          ? (items.length < 10 ? page + 1 : page + 2)
          : (data?.totalPages || 1);

        setResult({
          content: items,
          totalPages: Math.max(1, totalPages),
        });
      })
      .catch((err) => {
        setError(getErrorMessage(err, "Unable to load query history."));
      })
      .finally(() => setLoading(false));
  }, [page]);

  return (
    <div className="dashboard-page">
      <span className="eyebrow">YOUR ACTIVITY</span>
      <h1>Query History</h1>
      <p>Review queries saved to your account.</p>

      {loading && <p>Loading history...</p>}
      {error && <p className="error-message">{error}</p>}


        {!loading && !error && result.content.length === 0 && (
          <section className="notice-panel">
            <h2>No saved queries yet</h2>
            <p>Your submitted queries will appear here.</p>
            <Link to="/chat">Start a conversation →</Link>
          </section>
        )}

        {!loading && result.content.length > 0 && (
          <>
            <div className="history-list">
              {result.content.map((item) => (
                <article className="history-item" key={item.id}>
                  <h3>{item.question}</h3>
                  <p>{item.createdAt || "Date unavailable"}</p>
                  {item.answer && <p>{item.answer}</p>}
                </article>
              ))}
            </div>

            <div className="pagination">
              <button
                className="button button-outline"
                disabled={page === 0}
                onClick={() => setPage((value) => value - 1)}
              >
                Previous
              </button>

              <span>Page {page + 1} of {Math.max(1, result.totalPages)}</span>

              <button
                className="button button-outline"
                disabled={page + 1 >= result.totalPages}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </button>
            </div>
          </>
        )}
    </div>
  );
}