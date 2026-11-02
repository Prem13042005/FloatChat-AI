import { useEffect, useRef, useState } from "react";
import {
  MessageSquare,
  Plus,
  Send,
  Waves,
  Bot,
  UserRound,
  Database,
  Sparkles,
  Trash2,
  AlertTriangle,
  FileText,
  BarChart2,
  Clock,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  getConversations,
  getConversation,
  sendChatMessage,
  deleteConversation,
} from "../services/chatService";
import { getErrorMessage, getAiStatus } from "../services/api";
import DataVisualization from "../components/DataVisualization";
import "../styles/Chat.css";

const examples = [
  "How does ocean temperature change with depth?",
  "What is an ARGO float?",
  "Compare temperature and salinity profiles.",
];

export default function Chat() {
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [failedQuestion, setFailedQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState("");
  const [aiStatus, setAiStatus] = useState({ loading: true, mode: null, status: null });
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    let active = true;

    getAiStatus()
      .then((data) => {
        if (!active) return;
        setAiStatus({
          loading: false,
          mode: data?.mode || "unknown",
          status: data?.status || "unknown",
        });
      })
      .catch(() => {
        if (!active) return;
        setAiStatus({
          loading: false,
          mode: "unknown",
          status: "UNAVAILABLE",
        });
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    getConversations()
      .then(async (result) => {
        if (!active) return;
        const list = Array.isArray(result)
          ? result
          : result?.content || [];
        setConversations(list);

        const savedId = sessionStorage.getItem("floatchat_active_conversation_id");
        if (savedId) {
          const parsedId = Number(savedId);
          const found = list.find((c) => c.id === parsedId);
          if (found) {
            setConversationId(parsedId);
            setConversationLoading(true);
            try {
              const data = await getConversation(parsedId);
              if (!active) return;
              if (Array.isArray(data?.messages)) {
                setMessages(
                  data.messages.map((message) => ({
                    role: String(message.role || "assistant").toLowerCase(),
                    content: message.content || "",
                    createdAt: message.createdAt,
                    demo: false,
                    citations: message.citations || [],
                    sources: message.sources || [],
                    visualizationSpec: message.visualizationSpec || null,
                  }))
                );
              }
            } catch (err) {
              if (active) {
                setError(getErrorMessage(err, "Unable to restore previous conversation."));
              }
            } finally {
              if (active) setConversationLoading(false);
            }
          } else {
            sessionStorage.removeItem("floatchat_active_conversation_id");
          }
        }
      })
      .catch(() => {
        if (active) setConversations([]);
      });

    return () => {
      active = false;
    };
  }, []);

  // Timer for tracking inference duration during CPU-bound scientific processing
  useEffect(() => {
    if (loading) {
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [loading]);

  function newConversation() {
    if (loading || conversationLoading) return;

    sessionStorage.removeItem("floatchat_active_conversation_id");
    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setFailedQuestion("");
    setError("");
    setMobileSidebarOpen(false);
  }

  async function openConversation(item) {
    if (loading || conversationLoading) return;

    const targetId = typeof item === "object" ? item.id : item;
    if (!targetId) return;

    setConversationId(targetId);
    sessionStorage.setItem("floatchat_active_conversation_id", String(targetId));
    setConversationLoading(true);
    setError("");
    setMobileSidebarOpen(false);

    try {
      const data = await getConversation(targetId);
      if (Array.isArray(data?.messages)) {
        setMessages(
          data.messages.map((message) => ({
            role: String(message.role || "assistant").toLowerCase(),
            content: message.content || "",
            createdAt: message.createdAt,
            demo: false,
            citations: message.citations || [],
            sources: message.sources || [],
            visualizationSpec: message.visualizationSpec || null,
          }))
        );
      } else {
        setMessages([]);
      }
    } catch (err) {
      setError(getErrorMessage(err, "Unable to load conversation messages."));
      setMessages([]);
    } finally {
      setConversationLoading(false);
    }
  }

  async function handleDeleteConversation(e, id) {
    e.stopPropagation();
    if (loading || conversationLoading) return;

    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        sessionStorage.removeItem("floatchat_active_conversation_id");
        newConversation();
      }
    } catch (err) {
      setError(getErrorMessage(err, "Unable to delete conversation."));
    }
  }

  async function submitQuestion(event) {
    event.preventDefault();

    const text = question.trim();
    if (!text || loading || conversationLoading) return;

    setMessages((previous) => [
      ...previous,
      { role: "user", content: text },
    ]);

    setFailedQuestion(text);
    setQuestion("");
    setError("");
    setLoading(true);

    try {
      const result = await sendChatMessage(text, conversationId);

      const activeId = result.conversationId ?? conversationId;
      setConversationId(activeId);
      if (activeId) {
        sessionStorage.setItem("floatchat_active_conversation_id", String(activeId));
      }

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: result.answer || "No answer was returned.",
          demo: Boolean(result.demo),
          sql: result.sql,
          sources: result.sources || [],
          citations: result.citations || [],
          sqlMeta: result.sqlMeta || null,
          dataSummary: result.dataSummary || null,
          visualizationSpec: result.visualizationSpec || null,
          warnings: result.warnings || [],
          intentType: result.intentType,
          status: result.status,
        },
      ]);

      setFailedQuestion("");

      try {
        const items = await getConversations();
        setConversations(
          Array.isArray(items) ? items : items?.content || []
        );
      } catch {
        // Keep the current chat if refreshing history fails.
      }
    } catch (err) {
      setError(
        getErrorMessage(err, "Unable to get an AI response. Please try again.")
      );
    } finally {
      setLoading(false);
    }
  }

  function retryQuestion() {
    if (loading || conversationLoading) return;

    const questionToRestore = failedQuestion ||
      [...messages].reverse().find((m) => m.role === "user")?.content;

    if (questionToRestore) {
      setQuestion(questionToRestore);
      setError("");
    }
  }

  return (
    <main className="fc-chat-page">
      <div className="fc-chat-layout">
        {mobileSidebarOpen && (
          <div
            className="fc-sidebar-backdrop"
            onClick={() => setMobileSidebarOpen(false)}
            aria-hidden="true"
          />
        )}

        <aside className={`fc-chat-sidebar ${mobileSidebarOpen ? "fc-chat-sidebar-mobile-open" : ""}`}>
          <div className="fc-sidebar-brand">
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div className="fc-brand-icon">
                <Waves size={25} />
              </div>
              <div>
                <h2>FloatChat</h2>
                <span>Ocean intelligence</span>
              </div>
            </div>

            <button
              type="button"
              className="fc-mobile-sidebar-close"
              onClick={() => setMobileSidebarOpen(false)}
              aria-label="Close conversation history"
            >
              <X size={20} />
            </button>
          </div>

          <button
            type="button"
            className="fc-new-chat"
            onClick={newConversation}
            disabled={loading || conversationLoading}
          >
            <Plus size={18} />
            <span>New conversation</span>
          </button>

          <div className="fc-history-heading">
            <span>YOUR CONVERSATIONS</span>
            <MessageSquare size={15} />
          </div>

          <div className="fc-conversation-list">
            {conversations.map((item) => (
              <div
                key={item.id}
                className={`fc-conversation-item ${
                  conversationId === item.id ? "active" : ""
                }`}
                onClick={() => openConversation(item)}
                role="button"
                tabIndex={0}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", overflow: "hidden" }}>
                  <MessageSquare size={16} style={{ flexShrink: 0 }} />
                  <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {item.title || "New conversation"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={(e) => handleDeleteConversation(e, item.id)}
                  title="Delete conversation"
                  aria-label="Delete conversation"
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    padding: "4px",
                    color: "inherit",
                    opacity: 0.6,
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}

            {conversations.length === 0 && (
              <p className="fc-history-empty">
                Your conversations will appear here.
              </p>
            )}
          </div>

          <div className="fc-sidebar-footer">
            <Database size={16} />
            <span>ARGO Oceanographic Platform</span>
          </div>
        </aside>

        <section className="fc-chat-main">
          <header className="fc-chat-topbar">
            <div className="fc-topbar-title">
              <div className="fc-mobile-brand-icon">
                <Waves size={21} />
              </div>
              <div>
                <h1>AI Research Assistant</h1>
                <p>
                  Explore oceanographic data with FloatChat
                </p>
              </div>
            </div>

            {(() => {
              let dotBg = "#94a3b8";
              let dotShadow = "rgb(148 163 184 / 20%)";
              let bg = "#f8fafc";
              let border = "#e2e8f0";
              let color = "#64748b";
              let label = "Checking AI...";

              if (!aiStatus.loading) {
                if (aiStatus.mode === "real" && aiStatus.status === "CONNECTED") {
                  dotBg = "#35b681";
                  dotShadow = "rgb(53 182 129 / 12%)";
                  bg = "#f0fbf6";
                  border = "#d8f0e5";
                  color = "#328466";
                  label = "Real AI System";
                } else if (aiStatus.mode === "mock" || aiStatus.status === "DEMO_MODE") {
                  dotBg = "#f59e0b";
                  dotShadow = "rgb(245 158 11 / 15%)";
                  bg = "#fffbeb";
                  border = "#fef3c7";
                  color = "#b45309";
                  label = "Demo Mode (Mock)";
                } else {
                  dotBg = "#ef4444";
                  dotShadow = "rgb(239 68 68 / 15%)";
                  bg = "#fef2f2";
                  border = "#fee2e2";
                  color = "#b91c1c";
                  label = "AI Service Offline";
                }
              }

              return (
                <div
                  className="fc-status"
                  style={{
                    background: bg,
                    borderColor: border,
                    color: color,
                  }}
                  title={`AI Mode: ${aiStatus.mode || "unknown"} | Status: ${aiStatus.status || "unknown"}`}
                >
                  <span
                    className="fc-status-dot"
                    style={{
                      background: dotBg,
                      boxShadow: `0 0 0 3px ${dotShadow}`,
                    }}
                  />
                  {label}
                </div>
              );
            })()}

            <button
              type="button"
              className="fc-mobile-history-toggle"
              onClick={() => setMobileSidebarOpen((prev) => !prev)}
              aria-label={mobileSidebarOpen ? "Close history" : "Open conversation history"}
              aria-expanded={mobileSidebarOpen}
            >
              <MessageSquare size={16} />
              <span>History ({conversations.length})</span>
            </button>
          </header>

          <div className="fc-chat-messages">
            {conversationLoading && (
              <div
                className="fc-conversation-loading"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "40px",
                  color: "#64748b",
                  gap: "10px",
                  fontSize: "0.95rem",
                }}
              >
                <Clock className="fc-spin" size={18} />
                <span>Loading conversation history...</span>
              </div>
            )}

            {!conversationLoading && messages.length === 0 && (
              <div className="fc-welcome">
                <div className="fc-welcome-icon">
                  <Sparkles size={31} />
                </div>

                <span className="fc-welcome-eyebrow">
                  YOUR OCEAN DATA ASSISTANT
                </span>

                <h2>
                  Discover what lies
                  <br />
                  beneath the surface.
                </h2>

                <p className="fc-welcome-description">
                  Ask questions about ocean temperature,
                  salinity, depth profiles, and available
                  ARGO oceanographic datasets.
                </p>

                <div className="fc-suggestions">
                  {examples.map((example, index) => (
                    <button
                      type="button"
                      key={example}
                      className="fc-suggestion"
                      onClick={() => setQuestion(example)}
                      disabled={loading || conversationLoading}
                    >
                      <span className="fc-suggestion-number">
                        0{index + 1}
                      </span>
                      <span>{example}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <article
                key={`${conversationId ?? "new"}-${index}-${message.role}`}
                className={`fc-message ${
                  message.role === "user"
                    ? "fc-user-message"
                    : "fc-assistant-message"
                }`}
              >
                <div className="fc-message-avatar">
                  {message.role === "user" ? (
                    <UserRound size={18} />
                  ) : (
                    <Bot size={19} />
                  )}
                </div>

                <div className="fc-message-body">
                  <div className="fc-message-meta">
                    <strong>
                      {message.role === "user"
                        ? "You"
                        : "FloatChat Assistant"}
                    </strong>
                    {message.role !== "user" && message.demo && (
                      <span className="fc-demo-badge">Demo</span>
                    )}
                  </div>

                  <div className="fc-markdown">
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  </div>

                  {/* Render Scientific Citations */}
                  {Array.isArray(message.citations) && message.citations.length > 0 && (
                    <div className="fc-citations-container">
                      <div className="fc-citations-header">
                        <FileText size={14} />
                        <span>Scientific Citations & Sources</span>
                      </div>
                      <div className="fc-citations-list">
                        {message.citations.map((c, cIdx) => (
                          <div key={c.chunkId || cIdx} className="fc-citation-card">
                            <div className="fc-citation-title">
                              <strong>{c.documentTitle}</strong>
                              {c.sectionTitle && <span> &mdash; {c.sectionTitle}</span>}
                            </div>
                            {c.snippet && (
                              <blockquote className="fc-citation-snippet">
                                &ldquo;{c.snippet}&rdquo;
                              </blockquote>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Render Data Summary */}
                  {message.dataSummary && (
                    <div className="fc-data-summary">
                      <div className="fc-data-summary-title">
                        <BarChart2 size={14} />
                        <span>Dataset Summary ({message.dataSummary.totalRecords ?? 0} records analyzed)</span>
                      </div>
                      {Array.isArray(message.dataSummary.highlights) && message.dataSummary.highlights.length > 0 && (
                        <ul className="fc-data-highlights">
                          {message.dataSummary.highlights.map((h, hIdx) => (
                            <li key={hIdx}>{h}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}

                  {/* Render Interactive Data Visualization */}
                  {message.visualizationSpec && (
                    <DataVisualization spec={message.visualizationSpec} />
                  )}

                  {/* Render SQL Inspector (if SQL query was executed) */}
                  {message.sql && (
                    <details className="fc-sql-details">
                      <summary>
                        <Database size={13} />
                        <span>View Executed SQL Query</span>
                        {message.sqlMeta?.executionTimeMs && (
                          <span className="fc-sql-time">({message.sqlMeta.executionTimeMs.toFixed(1)} ms)</span>
                        )}
                      </summary>
                      <pre>
                        <code>{message.sql}</code>
                      </pre>
                    </details>
                  )}

                  {/* Render Warnings */}
                  {Array.isArray(message.warnings) && message.warnings.length > 0 && (
                    <div className="fc-message-warnings">
                      {message.warnings.map((w, wIdx) => (
                        <div key={wIdx} className="fc-warning-item">
                          <AlertTriangle size={13} />
                          <span>{w}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            ))}

            {loading && (
              <article className="fc-message fc-assistant-message">
                <div className="fc-message-avatar">
                  <Bot size={19} />
                </div>
                <div className="fc-message-body">
                  <div className="fc-message-meta">
                    <strong>FloatChat Assistant</strong>
                  </div>
                  <div className="fc-loading-box">
                    <div className="fc-loading-spinner" />
                    <div>
                      <p className="fc-loading-title">
                        Analyzing ARGO oceanographic observations...
                      </p>
                      <p className="fc-loading-subtitle">
                        <Clock size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: "4px" }} />
                        {elapsedSeconds < 15
                          ? `Querying data and synthesizing response (${elapsedSeconds}s elapsed)...`
                          : elapsedSeconds < 45
                          ? `Executing multi-agent deep scientific reasoning (${elapsedSeconds}s elapsed)...`
                          : `Synthesizing scientific citations on CPU (${elapsedSeconds}s elapsed - thank you for your patience)...`}
                      </p>
                    </div>
                  </div>
                </div>
              </article>
            )}

            {error && (
              <div className="fc-chat-error" role="alert">
                <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                  <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: "2px" }} />
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: 0, fontWeight: 500 }}>{error}</p>
                    {failedQuestion && (
                      <button
                        type="button"
                        onClick={retryQuestion}
                        className="fc-retry-btn"
                        disabled={loading || conversationLoading}
                      >
                        Retry Query
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="fc-chat-bottom">
            <form className="fc-chat-form" onSubmit={submitQuestion}>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Ask anything about oceanographic data (e.g. 'What is an ARGO float?')..."
                rows={2}
                aria-label="Your question"
                disabled={loading || conversationLoading}
                required
              />

              <button
                type="submit"
                className="fc-send-button"
                disabled={loading || conversationLoading || !question.trim()}
                aria-label="Send question"
              >
                <Send size={18} />
                <span>Send</span>
              </button>
            </form>

            <p className="fc-composer-hint">
              Press Enter to send · Shift + Enter for a new line
            </p>

            <p className="fc-disclaimer">
              Scientific observations retrieved directly from ARGO profiles and scientific documentation.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
