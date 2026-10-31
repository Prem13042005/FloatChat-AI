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
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  getConversations,
  sendChatMessage,
  deleteConversation,
} from "../services/chatService";
import { getErrorMessage } from "../services/api";
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
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState("");
  const timerRef = useRef(null);

  useEffect(() => {
    let active = true;

    getConversations()
      .then((result) => {
        if (!active) return;
        setConversations(
          Array.isArray(result)
            ? result
            : result?.content || []
        );
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
    if (loading) return;

    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setFailedQuestion("");
    setError("");
  }

  function openConversation(item) {
    if (loading) return;

    setConversationId(item.id);
    if (Array.isArray(item.messages) && item.messages.length > 0) {
      setMessages(
        item.messages.map((message) => ({
          role: String(message.role || "assistant").toLowerCase(),
          content: message.content || "",
          demo: Boolean(message.demo),
          sql: message.sql,
          sources: message.sources || [],
          citations: message.citations || [],
          sqlMeta: message.sqlMeta || null,
          dataSummary: message.dataSummary || null,
          visualizationSpec: message.visualizationSpec || null,
          warnings: message.warnings || [],
        }))
      );
    } else {
      setMessages([
        {
          role: "assistant",
          content: `Resumed conversation: **${item.title || "Observation Session"}**. Ask any follow-up question below.`,
          demo: false,
          citations: [],
          sources: [],
        },
      ]);
    }
    setError("");
  }

  async function handleDeleteConversation(e, id) {
    e.stopPropagation();
    if (loading) return;

    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        newConversation();
      }
    } catch (err) {
      setError(getErrorMessage(err, "Unable to delete conversation."));
    }
  }

  async function submitQuestion(event) {
    event.preventDefault();

    const text = question.trim();
    if (!text || loading) return;

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

      setConversationId(result.conversationId ?? conversationId);

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
    if (loading) return;

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
        <aside className="fc-chat-sidebar">
          <div className="fc-sidebar-brand">
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
            className="fc-new-chat"
            onClick={newConversation}
            disabled={loading}
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

            <div className="fc-status">
              <span className="fc-status-dot" />
              Real AI System
            </div>
          </header>

          <div className="fc-chat-messages">
            {messages.length === 0 && (
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
                      disabled={loading}
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
                        : "FloatChat AI"}
                    </strong>

                    {message.demo && (
                      <span className="fc-demo-label">
                        DEMO RESPONSE
                      </span>
                    )}

                    {message.intentType && (
                      <span style={{
                        fontSize: "10px",
                        letterSpacing: "0.5px",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        background: "#e0f2fe",
                        color: "#0369a1",
                        fontWeight: 600,
                        marginLeft: "6px"
                      }}>
                        {message.intentType}
                      </span>
                    )}
                  </div>

                  <div className="fc-markdown">
                    <ReactMarkdown>
                      {message.content}
                    </ReactMarkdown>
                  </div>

                  {/* Scientific Warnings */}
                  {message.warnings?.length > 0 && (
                    <div style={{
                      marginTop: "10px",
                      padding: "8px 12px",
                      borderRadius: "6px",
                      background: "#fffbeb",
                      border: "1px solid #fef3c7",
                      color: "#92400e",
                      fontSize: "12px",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px"
                    }}>
                      <AlertTriangle size={15} style={{ flexShrink: 0 }} />
                      <div>
                        {message.warnings.map((w, wi) => (
                          <div key={wi}>{w}</div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Scientific Citations */}
                  {message.citations?.length > 0 && (
                    <details className="fc-detail-panel" open={message.citations.length <= 3}>
                      <summary style={{ cursor: "pointer", fontWeight: 600, color: "#1c5bb0", display: "flex", alignItems: "center", gap: "6px" }}>
                        <FileText size={14} />
                        Scientific Sources & Citations ({message.citations.length})
                      </summary>
                      <div style={{ padding: "8px 12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                        {message.citations.map((c, i) => (
                          <div key={i} style={{ borderBottom: "1px solid #eef2f6", paddingBottom: "6px" }}>
                            <div style={{ fontWeight: 600, fontSize: "12px", color: "#182c42" }}>
                              {c.documentTitle || "Scientific Source"}
                              {c.sectionTitle ? ` — ${c.sectionTitle}` : ""}
                            </div>
                            {c.snippet && (
                              <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#475569", fontStyle: "italic", lineHeight: 1.5 }}>
                                "{c.snippet}"
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Legacy Sources Fallback */}
                  {(!message.citations || message.citations.length === 0) && message.sources?.length > 0 && (
                    <details className="fc-detail-panel">
                      <summary>Sources ({message.sources.length})</summary>
                      <ul>
                        {message.sources.map((source, sourceIndex) => (
                          <li key={sourceIndex}>
                            {source.title || source.url || String(source)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {/* Data Summary & SQL Execution Details */}
                  {(message.dataSummary || message.sqlMeta || message.sql) && (
                    <details className="fc-detail-panel">
                      <summary style={{ cursor: "pointer", fontWeight: 600, color: "#0284c7", display: "flex", alignItems: "center", gap: "6px" }}>
                        <Database size={14} />
                        Observation Data & SQL Metrics
                      </summary>
                      <div style={{ padding: "8px 12px", fontSize: "12px" }}>
                        {message.dataSummary && (
                          <div style={{ marginBottom: "8px" }}>
                            <div>
                              <strong>Records Extracted:</strong> {message.dataSummary.totalRecords ?? "N/A"}
                              {message.dataSummary.variablesPresent?.length > 0 && (
                                <span> · <strong>Variables:</strong> {message.dataSummary.variablesPresent.join(", ")}</span>
                              )}
                            </div>
                            {message.dataSummary.highlights?.length > 0 && (
                              <ul style={{ margin: "4px 0", paddingLeft: "18px" }}>
                                {message.dataSummary.highlights.map((h, hi) => (
                                  <li key={hi}>{h}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}

                        {(message.sqlMeta?.generatedSql || message.sql) && (
                          <>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", color: "#64748b" }}>
                              <span>Generated SQL:</span>
                              {message.sqlMeta?.executionTimeMs && <span>{message.sqlMeta.executionTimeMs} ms</span>}
                            </div>
                            <pre style={{ margin: 0 }}>{message.sqlMeta?.generatedSql || message.sql}</pre>
                          </>
                        )}
                      </div>
                    </details>
                  )}

                  {/* Visualization Specification */}
                  {message.visualizationSpec && (
                    <div style={{
                      marginTop: "12px",
                      padding: "12px 14px",
                      borderRadius: "10px",
                      border: "1px solid #e0e8f1",
                      background: "#f8fafc"
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600, fontSize: "13px", color: "#0f172a", marginBottom: "4px" }}>
                        <BarChart2 size={16} color="#2563eb" />
                        <span>{message.visualizationSpec.title || "Observation Visualization"}</span>
                      </div>
                      {message.visualizationSpec.description && (
                        <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#64748b" }}>
                          {message.visualizationSpec.description}
                        </p>
                      )}
                      <div style={{ fontSize: "12px", color: "#475569" }}>
                        <strong>Type:</strong> {message.visualizationSpec.chartType || "Chart"} ·
                        <strong> X:</strong> {message.visualizationSpec.xAxis || "value"} ·
                        <strong> Y:</strong> {message.visualizationSpec.yAxis || "depth"}
                        {message.visualizationSpec.invertY && <span> (Depth Inverted)</span>}
                      </div>
                    </div>
                  )}
                </div>
              </article>
            ))}

            {loading && (
              <div className="fc-message fc-assistant-message">
                <div className="fc-message-avatar">
                  <Bot size={19} />
                </div>
                <div className="fc-message-body">
                  <div className="fc-message-meta">
                    <strong>FloatChat AI</strong>
                  </div>
                  <div className="fc-thinking">
                    <span />
                    <span />
                    <span />
                    <p style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <Clock size={14} />
                      Analyzing scientific question and query path... ({elapsedSeconds}s)
                    </p>
                  </div>
                  <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#94a3b8" }}>
                    Deep scientific analysis on local ARGO datasets typically requires 40–65 seconds.
                  </p>
                </div>
              </div>
            )}

            {error && (
              <div className="fc-error" role="alert">
                <p>{error}</p>
                <button
                  type="button"
                  onClick={retryQuestion}
                  disabled={loading}
                >
                  Try again
                </button>
              </div>
            )}
          </div>

          <div className="fc-composer-area">
            <form
              className="fc-composer"
              onSubmit={submitQuestion}
            >
              <textarea
                value={question}
                onChange={(event) =>
                  setQuestion(event.target.value)
                }
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Ask anything about oceanographic data (e.g. 'What is an ARGO float?')..."
                rows={2}
                aria-label="Your question"
                disabled={loading}
                required
              />

              <button
                type="submit"
                className="fc-send-button"
                disabled={loading || !question.trim()}
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
