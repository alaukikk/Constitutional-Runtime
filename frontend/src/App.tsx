import { useState } from "react";
import { Answer } from "./components/Answer";
import { AppNav, type Page } from "./components/AppNav";
import { Button } from "./components/Button";
import { Composer } from "./components/Composer";
import { Notice } from "./components/Notice";
import { useRuntime } from "./lib/useRuntime";

export function App() {
  const [page, setPage] = useState<Page>("workspace");
  const rt = useRuntime();
  const { state, dispatch } = rt;
  const view = state.view;

  return (
    <div className="shell">
      <AppNav page={page} onNavigate={setPage} sessionStatus={state.session.status} />
      <main className="main">
        {page === "policy" ? (
          <>
            <p className="eyebrow">Policy</p>
            <h1 className="display">How requests are handled</h1>
            <Notice title="Coming in a later build step.">
              <p className="caption">This page is built from the Policy frame in a later chunk.</p>
            </Notice>
          </>
        ) : (
          <>
            <p className="eyebrow">Workspace</p>
            <h1 className="display">What needs an answer?</h1>
            <p className="lede">Use the simplest adequate method, with one response from the runtime.</p>

            {state.session.status === "expired" && (
              <Notice title="Your session has expired. Your draft is kept.">
                <div><Button onClick={rt.restartSession}>Start a new session</Button></div>
              </Notice>
            )}
            {(state.session.status === "rate_limited" || state.session.status === "unavailable") && (
              <Notice
                title={
                  state.session.status === "rate_limited"
                    ? "Too many sessions have been started. Try again shortly."
                    : "The runtime is unavailable right now."
                }
              >
                <div><Button onClick={rt.restartSession}>Try again</Button></div>
              </Notice>
            )}

            {view?.kind === "answer" ? (
              <Answer view={view} onNewRequest={() => dispatch({ type: "new_request" })} />
            ) : view ? (
              // Confirmation, stopped, unsupported and withheld frames arrive in later chunks.
              <Notice title="Runtime message">
                <p className="plain">{view.message}</p>
                <div>
                  <Button variant="quiet" onClick={() => dispatch({ type: "edit_request" })}>
                    Edit request
                  </Button>
                </div>
              </Notice>
            ) : (
              <Composer
                draft={state.draft}
                inFlight={state.inFlight}
                emptyWarning={state.emptyWarning}
                failure={state.failure}
                sessionReady={state.session.status === "active"}
                onChange={(t) => dispatch({ type: "draft_changed", text: t })}
                onSend={rt.submit}
              />
            )}
          </>
        )}
      </main>
      <footer className="footnote">Capstone prototype</footer>
    </div>
  );
}
