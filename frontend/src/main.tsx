import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { HttpAgent } from "@ag-ui/client";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import "./styles.css";

function ToolCall({
  toolName,
  argsText,
  result,
  status,
}: ToolCallMessagePartProps) {
  const label =
    status.type === "incomplete"
      ? "Stopped"
      : result === undefined
        ? "Running"
        : "Complete";
  return (
    <details className="tool-call">
      <summary>
        {toolName}
        <span>{label}</span>
      </summary>
      <p className="detail-label">Arguments</p>
      <pre>{argsText}</pre>
      {result !== undefined && (
        <>
          <p className="detail-label">Result</p>
          <pre>
            {typeof result === "string"
              ? result
              : JSON.stringify(result, null, 2)}
          </pre>
        </>
      )}
    </details>
  );
}

function MarkdownText() {
  return <MarkdownTextPrimitive />;
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message assistant-message">
      <span className="message-label">SQL Agent</span>
      <MessagePrimitive.Parts
        components={{
          Text: MarkdownText,
          tools: { Fallback: ToolCall },
        }}
      />
    </MessagePrimitive.Root>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <span className="message-label">You</span>
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function App() {
  const [agent] = useState(
    () =>
      new HttpAgent({
        url: new URL("/agui", window.location.origin).href,
        threadId: crypto.randomUUID(),
        headers: { Accept: "text/event-stream" },
      }),
  );
  const [error, setError] = useState(false);
  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
    onError: () => setError(true),
  });

  useEffect(
    () =>
      runtime.thread.subscribe(() => {
        if (runtime.thread.getState().isRunning) setError(false);
      }),
    [runtime],
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="app">
        <header>
          <div className="app-mark" aria-hidden="true">
            SQL
          </div>
          <div>
            <h1>SQL Agent</h1>
            <p>Answers grounded in your database</p>
          </div>
        </header>
        <ThreadPrimitive.Root className="thread">
          <ThreadPrimitive.Viewport className="viewport">
            <ThreadPrimitive.Empty>
              <section className="welcome">
                <h2>What would you like to know?</h2>
                <p>
                  Ask about the connected database. I’ll discover its schema and
                  query it read-only.
                </p>
              </section>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages
              components={{ UserMessage, AssistantMessage }}
            />
            <ThreadPrimitive.If running>
              <p role="status" className="working">
                Working…
              </p>
            </ThreadPrimitive.If>
            {error && (
              <p role="alert" className="error">
                Request failed. Please try again.
              </p>
            )}
            <ThreadPrimitive.ViewportFooter className="footer">
              <ThreadPrimitive.ScrollToBottom className="scroll-button">
                Latest messages ↓
              </ThreadPrimitive.ScrollToBottom>
              <ComposerPrimitive.Root className="composer">
                <ComposerPrimitive.Input
                  aria-label="Question"
                  placeholder="Ask a question about your data…"
                  autoFocus
                  rows={2}
                />
                <div className="composer-actions">
                  <span>Read-only database access</span>
                  <ThreadPrimitive.If running={false}>
                    <ComposerPrimitive.Send>Send</ComposerPrimitive.Send>
                  </ThreadPrimitive.If>
                  <ThreadPrimitive.If running>
                    <ComposerPrimitive.Cancel>Stop</ComposerPrimitive.Cancel>
                  </ThreadPrimitive.If>
                </div>
              </ComposerPrimitive.Root>
              <p className="disclaimer">
                Check important answers. This conversation is not saved after a
                reload.
              </p>
            </ThreadPrimitive.ViewportFooter>
          </ThreadPrimitive.Viewport>
        </ThreadPrimitive.Root>
      </main>
    </AssistantRuntimeProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
